"""
Full-app tests for GET /v1/events.

The TestClient buffers a streaming response completely - the request returns
only when the generator terminates - so every request here carries `timeout`
and/or `max_events`, and events are published from a threading.Timer while
the stream is open. Real hook delivery, reload survival, and uvicorn drain
are Qt/uvicorn territory, covered by the manual smoke checklist.
"""
import json
import threading

import pytest

from tsunagi.adapters.events import broker

pytestmark = pytest.mark.usefixtures("review_events")


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


def parse_frames(body: str):
    """[(event_name, data_dict|None), ...] - comments/retry lines skipped."""
    frames = []
    for block in body.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name is not None:
            frames.append((name, data))
    return frames


def publish_soon(*events, delay=0.1):
    def fire():
        for type_, payload in events:
            broker.publish(type_, **payload)
    threading.Timer(delay, fire).start()


class TestStream:
    def test_timeout_only_stream_closes_cleanly(self, client):
        resp = client.get("/v1/events?timeout=0.3")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.text.startswith("retry: 3000")
        assert [f[0] for f in parse_frames(resp.text)] == ["ready", "close"]
        assert parse_frames(resp.text)[-1] == ("close", {"reason": "timeout"})

    def test_events_arrive_with_id_lines_and_close_on_max(self, client):
        publish_soon(("cards.answered", {"card_id": 42, "ease": 3}))
        resp = client.get("/v1/events?max_events=1&timeout=5")
        frames = parse_frames(resp.text)
        assert frames[0][0] == "ready"
        assert frames[1][0] == "cards.answered"
        assert frames[1][1]["card_id"] == 42
        assert frames[1][1]["ease"] == 3
        assert frames[-1] == ("close", {"reason": "max_events"})
        assert f"id: {frames[1][1]['session_id']}:{frames[1][1]['seq']}\n" in resp.text

    def test_multiple_events_keep_publish_order(self, client):
        publish_soon(("sync", {"phase": "started"}),
                     ("sync", {"phase": "finished"}),
                     ("reset", {}))
        resp = client.get("/v1/events?max_events=3&timeout=5")
        frames = parse_frames(resp.text)
        assert [f[0] for f in frames] == ["ready", "sync", "sync", "cards.stale", "close"]
        assert [f[1].get("phase") for f in frames[1:3]] == ["started", "finished"]

    def test_ready_states_the_heartbeat_interval(self, client):
        # Clients treat a few intervals without bytes as a dead stream.
        ready = parse_frames(client.get("/v1/events?timeout=0.2").text)[0]
        assert ready[0] == "ready"
        assert ready[1]["heartbeat_ms"] == 15000

    def test_framing(self, client, monkeypatch):
        # What docs/events.md promises small parsers.
        from tsunagi.http.v1 import events
        monkeypatch.setattr(events, "HEARTBEAT_SECONDS", 0.1)
        publish_soon(("sync", {"phase": "started"}))
        text = client.get("/v1/events?timeout=0.5").text
        assert "\r" not in text
        assert text.startswith("retry: 3000\n\n")
        assert "\n\n: ping\n\n" in text
        blocks = [b for b in text.split("\n\n") if b.startswith("event: ")]
        assert [b.split("\n", 1)[0] for b in blocks] == [
            "event: ready", "event: sync", "event: close"]
        for block in blocks:
            data = [line for line in block.split("\n") if line.startswith("data: ")]
            assert len(data) == 1 and isinstance(json.loads(data[0][6:]), dict)
        assert "\nid: " not in blocks[0] and "\nid: " in blocks[1]
        assert parse_frames(text)[-1] == ("close", {"reason": "timeout"})

    def test_drain_closes_an_open_stream(self, client):
        # The shutdown path: stop_server flips this flag before should_exit;
        # a stream must end for shutdown before its timeout expires.
        threading.Timer(0.1, broker.begin_drain).start()
        resp = client.get("/v1/events?timeout=5")
        assert parse_frames(resp.text)[-1] == ("close", {"reason": "shutdown"})

    def test_subscribers_are_cleaned_up(self, client):
        client.get("/v1/events?timeout=0.2")
        assert broker._subscribers == {}

    def test_role_change_closes_an_open_stream(self, client, reset_settings):
        # Auth is checked at connection time only; a credential change must
        # not leave streams running under the old rules (found in smoke: an
        # open stream survived setting a key and kept receiving events).
        threading.Timer(0.1, lambda: reset_settings.update(no_key_local_role="read_only")).start()
        resp = client.get("/v1/events?timeout=5")
        assert parse_frames(resp.text)[-1] == ("close", {"reason": "auth"})


class TestOpenApi:
    def test_route_is_mounted_and_documented(self, client):
        assert "/v1/events" in {r.path for r in client.app.routes}
        spec = client.get("/openapi.json").json()
        operation = spec["paths"]["/v1/events"]["get"]
        assert operation["tags"] == ["Events"]
        assert "text/event-stream" in operation["responses"]["200"]["content"]
        assert "Events" in {t["name"] for t in spec["tags"]}

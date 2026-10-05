"""access.changed: an app learns its access may have changed and fetches
/v1/capabilities again (backlog 6.100), and the report says what the event
stream would send it (6.83)."""
import threading

import pytest
from anki.collection import OpChanges
from test_v1_events import parse_frames

from tsunagi.adapters.events import broker, dispatch_op

pytestmark = pytest.mark.usefixtures("review_events")

GUI_ONLY = {"roles": {"gui_only": {"name": "GUI only", "grants": ["gui"]}},
            "no_key_local_role": "gui_only"}


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


def soon(action, delay=0.2):
    threading.Timer(delay, action).start()


def test_an_app_that_cant_read_may_still_watch_its_access(client, reset_settings):
    reset_settings.update(**GUI_ONLY)
    r = client.get("/v1/events?types=access.changed&timeout=0.3")
    assert r.status_code == 200
    ready = parse_frames(r.text)[0]
    assert ready[0] == "ready" and ready[1]["resources"] == []
    for query in ("", "?types=sync", "?resources=notes", "?types=access.changed&resources=notes"):
        denied = client.get("/v1/events" + query)
        assert denied.status_code == 403
        assert "does not allow read:collection" in denied.json()["detail"]


def test_losing_access_sends_access_changed_then_closes(client, reset_settings):
    soon(lambda: reset_settings.update(no_key_local_role="read_only"))
    frames = parse_frames(client.get("/v1/events?types=access.changed&timeout=5").text)
    assert [name for name, _ in frames] == ["ready", "access.changed", "close"]
    assert set(frames[1][1]) == {"type", "ts"}
    assert frames[-1][1] == {"reason": "auth"}


def test_an_add_on_approval_tells_every_stream_and_keeps_it_open(client, reset_settings):
    # A destructive item joins only Everything, so this caller's own grants stay the same.
    soon(lambda: reset_settings.update(addon_enabled={"provider/item": "destructive"}))
    frames = parse_frames(client.get("/v1/events?resources=notes&timeout=1").text)
    assert [name for name, _ in frames] == ["ready", "access.changed", "close"]
    assert frames[-1][1] == {"reason": "timeout"}


def test_access_changed_does_not_count_toward_max_events(client, reset_settings):
    soon(lambda: reset_settings.update(addon_enabled={"provider/item": "destructive"}))
    frames = parse_frames(client.get("/v1/events?max_events=1&timeout=1").text)
    assert frames[-1][1] == {"reason": "timeout"}


def test_turning_fsrs_on_or_off_tells_every_stream(col):
    broker.start_session(col)
    token = broker.subscribe(types=frozenset({"sync"}))
    dispatch_op(OpChanges(config=True), object())
    assert broker.drain(token) == []  # nothing changed
    for enabled in (True, False):
        col.set_config("fsrs", enabled)
        dispatch_op(OpChanges(deck_config=True), object())
        assert [event["type"] for event in broker.drain(token)] == ["access.changed"]


def test_the_report_says_what_the_stream_would_send(client, reset_settings):
    reset_settings.update(no_key_local_role="default")
    events = client.get("/v1/capabilities").json()["operations"]["GET /v1/events"]
    assert events["status"] == "available"
    options = events["options"]
    assert set(options) == {"access.changed", "sync", "cards.answered", "notes", "cards", "note_types",
                            "decks", "tags", "reviews", "scheduler", "config"}
    assert {name for name, option in options.items() if option["status"] == "available"} == {
        "access.changed", "sync", "notes", "cards", "note_types", "decks", "tags", "scheduler", "config"}
    assert options["cards.answered"]["setting"] == options["reviews"]["setting"] == "permissions.events:reviews"
    assert options["notes"]["setting"] == "permissions.events:changes"

    reset_settings.update(**GUI_ONLY)
    options = client.get("/v1/capabilities").json()["operations"]["GET /v1/events"]["options"]
    assert options["access.changed"]["status"] == "available"
    assert all(option["status"] == "disabled" and option["setting"] == "permissions.read:collection"
               for name, option in options.items() if name != "access.changed")

"""
The event stream's messages are in the API description (6.105): each type has
a schema, and what the server sends matches it, so clients can generate their
decoding instead of keeping it by hand.
"""
import threading
from types import SimpleNamespace

import pytest

from tsunagi.adapters.events import (
    ACCESS_CHANGED,
    EVENT_TYPES,
    broker,
    publish_review,
    publish_sync,
)
from tsunagi.http.v1.events import event_catalog

from .test_v1_events import parse_frames

pytestmark = pytest.mark.usefixtures("review_events")


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


def test_every_message_the_stream_sends_has_a_schema_in_the_description(client):
    events = client.get("/openapi.json").json()["paths"]["/v1/events"]["get"]["x-events"]
    components = client.get("/openapi.json").json()["components"]["schemas"]
    expected = (EVENT_TYPES - {"change"}) | {"ready", "gap", "close", ACCESS_CHANGED}
    assert set(events) == expected
    for entry in events.values():
        assert entry["schema"].rsplit("/", 1)[1] in components


def test_what_the_stream_sends_matches_its_schema(client):
    card = SimpleNamespace(id=11, ivl=3, due=20512, queue=2,
                           memory_state=SimpleNamespace(stability=2.5, difficulty=5.0))

    def fire():
        broker.publish("change", changes={"notes": {"created": [1], "updated": [2]}, "cards": {"deleted": [3]}},
                       by="api", app="Yomitan", affected=["notes", "cards", "tags"],
                       anki={"changes": ["note"], "label": "Add Note"})
        broker.publish("change", by=None, affected=["decks"], anki={"changes": ["deck"]})
        broker.publish("reset")
        broker.publish("decks.counts", decks=[{"deck_id": 1, "new_count": 2, "learn_count": 0,
                                               "review_count": 5, "total_in_deck": 9}])
        publish_review(card, 3)
        publish_sync("started")
        broker.publish_access()
    threading.Timer(0.1, fire).start()
    frames = parse_frames(client.get("/v1/events?timeout=1").text)
    catalog = event_catalog()
    seen = set()
    for name, data in frames:
        catalog[name]["schema"].parse_obj(data)   # extra fields are refused too
        seen.add(name)
    assert {"ready", "notes.created", "notes.updated", "cards.deleted", "tags.stale", "decks.stale",
            "reviews.stale", "decks.counts", "cards.answered", "sync", ACCESS_CHANGED, "close"} <= seen


def test_x_from_names_resources(client):
    spec = client.get("/openapi.json").json()
    resources = {"notes", "cards", "decks", "note_types", "tags", "reviews"}
    named = [name for path in ("/v1/cards", "/v1/notes", "/v1/reviews")
             for p in spec["paths"][path]["get"]["parameters"] if p.get("name") == "search"
             for name in p["schema"]["x-from"]]
    named += [name for schema in spec["components"]["schemas"].values()
              for field in schema.get("properties", {}).values() for name in field.get("x-from", [])]
    assert named and set(named) <= resources

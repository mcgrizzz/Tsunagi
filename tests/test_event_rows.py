"""select=<resource>:<columns> on GET /v1/events: the events naming rows carry
them, read when the event is sent (issue #23)."""
import pytest
from test_v1_events import parse_frames, publish_soon

from tsunagi.adapters.events import broker
from tsunagi.shared import route_factory

pytestmark = pytest.mark.usefixtures("review_events")

NO_NOTES = {"roles": {"changes": {"name": "Changes", "grants": ["read:collection", "events:changes"]}},
            "no_key_local_role": "changes"}


@pytest.fixture(autouse=True)
def clean_broker():
    broker.reset()
    yield
    broker.reset()


@pytest.fixture()
def note(client):
    body = {"deckName": "Default", "noteTypeName": "Basic", "fields": {"Front": "犬", "Back": "dog"}, "tags": ["mined"]}
    response = client.post("/v1/notes?include=cards", json=body)
    assert response.status_code in (200, 201), response.text
    created = response.json()["created"][0]
    return created["id"], created["cards"][0]


def stream(client, query, *changes):
    publish_soon(*(("change", {"changes": change, "affected": sorted(change)}) for change in changes))
    response = client.get(f"/v1/events?timeout=0.6&{query}")
    assert response.status_code == 200, response.text
    return {name: data for name, data in parse_frames(response.text)}


def test_an_event_carries_the_rows_as_get_returns_them(client, note):
    nid, _ = note
    frames = stream(client, "select=notes:fields,tags", {"notes": {"updated": [nid]}})
    expected = client.get(f"/v1/notes?where=id in [{nid}]&select=id,fields,tags").json()["items"]
    assert frames["notes.updated"]["notes"] == expected
    assert expected[0]["tags"] == ["mined"]


def test_id_comes_once_and_first(client, note):
    nid, _ = note
    frames = stream(client, "select=notes:first_field,id", {"notes": {"created": [nid]}})
    assert frames["notes.created"]["notes"] == [{"first_field": "犬", "id": nid}]
    frames = stream(client, "select=notes:first_field", {"notes": {"created": [nid]}})
    assert list(frames["notes.created"]["notes"][0]) == ["id", "first_field"]


def test_fields_narrow_as_on_get(client, note):
    nid, _ = note
    frames = stream(client, 'select=notes:fields[name in ["Front"]].value,tags', {"notes": {"updated": [nid]}})
    assert frames["notes.updated"]["notes"] == [{"id": nid, "fields": ["犬"], "tags": ["mined"]}]


def test_each_resource_has_its_own_columns(client, note):
    nid, cid = note
    frames = stream(client, "select=notes:first_field&select=cards:queue",
                    {"notes": {"updated": [nid]}, "cards": {"updated": [cid]}})
    assert frames["notes.updated"]["notes"] == [{"id": nid, "first_field": "犬"}]
    assert frames["cards.updated"]["cards"] == [{"id": cid, "queue": 0}]
    assert "notes" not in frames["cards.updated"]


def test_only_events_naming_existing_rows_carry_them(client, note):
    nid, cid = note
    frames = stream(client, "select=notes:first_field&select=reviews:rating",
                    {"notes": {"updated": [nid, 999]}}, {"notes": {"deleted": [nid]}},
                    {"reviews": {"created": [1]}}, {"cards": {"updated": [cid]}})
    assert frames["notes.updated"]["notes"] == [{"id": nid, "first_field": "犬"}]  # 999 doesn't exist
    assert "notes" not in frames["notes.deleted"]
    assert frames["reviews.created"]["reviews"] == []
    assert "cards" not in frames["cards.updated"]


def test_without_select_events_are_unchanged(client, note):
    nid, _ = note
    frames = stream(client, "resources=notes", {"notes": {"updated": [nid]}})
    assert set(frames["notes.updated"]) == {"type", "ids", "seq", "session_id", "ts"}


def test_rows_that_cant_be_read_leave_the_event_as_it_was(client, note, monkeypatch, caplog):
    nid, _ = note
    reader = route_factory.ROW_READERS["notes"]

    def fail(ids, select):
        raise RuntimeError("collection closed")
    monkeypatch.setitem(route_factory.ROW_READERS, "notes", reader._replace(read=fail))
    frames = stream(client, "select=notes:fields", {"notes": {"updated": [nid]}})
    assert frames["notes.updated"]["ids"] == [nid] and "notes" not in frames["notes.updated"]
    assert "Could not read the notes of notes.updated" in caplog.text


@pytest.mark.parametrize("query, status, detail", [
    ("select=fields", 422, "select must be <resource>:<columns>, for one of: cards, notes, reviews"),
    ("select=decks:name", 422, "for one of: cards, notes, reviews"),
    ("select=notes:", 422, "select must be"),
    ("select=notes:fields&select=notes:tags", 422, "select names notes more than once"),
    ("types=cards.updated&select=notes:fields", 422, "this stream sends no notes events"),
    ("select=notes:nope", 400, "Unknown field nope"),
    ("select=notes:fields[", 400, ""),
])
def test_a_select_that_cant_work_is_refused(client, query, status, detail):
    response = client.get(f"/v1/events?timeout=0.1&{query}")
    assert response.status_code == status, response.text
    assert detail in response.json()["detail"]


def test_select_needs_read_permission_for_its_resource(client, reset_settings):
    reset_settings.update(**NO_NOTES)
    assert client.get("/v1/events?timeout=0.1&resources=notes").status_code == 200
    denied = client.get("/v1/events?timeout=0.1&select=notes:fields")
    assert denied.status_code == 403
    assert "read:notes" in denied.json()["detail"]

"""Keys and cursors belong to a profile's collection (6.120): after a switch, a
keyed retry is a new request and an old cursor is refused; on the same profile
reopened, both still work."""
import pytest
from anki.collection import Collection
from fakes.anki_stubs import mw

from tsunagi.adapters import idempotency
from tsunagi.adapters.events import broker


@pytest.fixture(autouse=True)
def clean_keys():
    idempotency.store.reset()
    idempotency._journals.reset()
    yield
    idempotency.store.reset()
    idempotency._journals.reset()


@pytest.fixture()
def switch(col, tmp_path):
    """Switch Anki to a second profile's collection, as a profile switch does."""
    other = []

    def to_other():
        other.append(Collection(str(tmp_path / "other.anki2")))
        mw.col = other[0]
        broker.start_session(mw.col)
        return mw.col

    yield to_other
    if other:
        mw.col = col  # the col fixture closes its own
        other[0].close()


NOTE = {"noteTypeName": "Basic", "deckName": "Default", "fields": {"Front": "a", "Back": ""}}


def test_a_note_retried_after_a_switch_is_created_in_the_new_profile(client, switch):
    client.post("/v1/notes", json=NOTE, headers={"Idempotency-Key": "k1"})
    other = switch()
    again = client.post("/v1/notes", json=NOTE, headers={"Idempotency-Key": "k1"})
    assert "idempotent-replayed" not in again.headers
    assert other.note_count() == 1


def test_a_write_retried_after_a_switch_is_made_in_the_new_profile(client, switch):
    client.post("/v1/decks", json={"name": "Mined"}, headers={"Idempotency-Key": "k1"})
    other = switch()
    again = client.post("/v1/decks", json={"name": "Mined"}, headers={"Idempotency-Key": "k1"})
    assert "idempotent-replayed" not in again.headers
    assert other.decks.id_for_name("Mined")



def test_a_retry_on_the_same_profile_reopened_is_still_replayed(client, col):
    first = client.post("/v1/notes", json=NOTE, headers={"Idempotency-Key": "k1"})
    col.close(downgrade=False)
    mw.col = Collection(col.path)  # the profile reopened: a new object, the same collection
    try:
        again = client.post("/v1/notes", json=NOTE, headers={"Idempotency-Key": "k1"})
        assert again.headers["idempotent-replayed"] == "true" and again.json() == first.json()
        assert mw.col.note_count() == 1
    finally:
        mw.col.close()
        mw.col = Collection(col.path)  # for the col fixture to close


def test_a_cursor_from_another_profile_is_refused(client, switch):
    for front in "ab":
        client.post("/v1/notes", json={**NOTE, "fields": {"Front": front, "Back": ""}})
    cursor = client.get("/v1/notes", params={"limit": 1}).json()["next_cursor"]
    other = switch()
    other.add_note(other.new_note(other.models.by_name("Basic")), 1)
    resp = client.get("/v1/notes", params={"limit": 1, "cursor": cursor})
    assert resp.status_code == 400 and "another profile" in resp.json()["detail"]


@pytest.mark.parametrize("order", [None, "id:desc", "sort_field", "modified"])
def test_a_cursor_works_on_the_same_profile_reopened(client, col, order):
    for front in "abc":
        client.post("/v1/notes", json={**NOTE, "fields": {"Front": front, "Back": ""}})
    params = {"limit": 1, **({"order": order} if order else {})}
    first = client.get("/v1/notes", params=params).json()
    col.close(downgrade=False)
    mw.col = Collection(col.path)
    page = client.get("/v1/notes", params={**params, "cursor": first["next_cursor"]})
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] != first["items"][0]["id"]


def test_a_column_ordered_cursor_works_on_the_same_profile_reopened(client, col, answer_cards):
    for front in "abc":
        client.post("/v1/notes", json={**NOTE, "fields": {"Front": front, "Back": ""}})
    assert answer_cards(3) == 3
    params = {"limit": 1, "order": "rating"}
    first = client.get("/v1/reviews", params=params).json()
    col.close(downgrade=False)
    mw.col = Collection(col.path)
    page = client.get("/v1/reviews", params={**params, "cursor": first["next_cursor"]})
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] != first["items"][0]["id"]

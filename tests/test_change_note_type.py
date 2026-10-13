"""POST /v1/notes:change-note-type (6.118): Anki's Change Note Type, with a dry run
that answers what the change would do."""
import pytest
from test_events_broker import recorded_ops as recorded_ops

from tsunagi.adapters.events import broker, dispatch_op

ROUTE = "/v1/notes:change-note-type"
REVERSED = "Basic (and reversed card)"


_made = iter(range(1000))


def add(client, note_type="Basic", **fields):
    """A note with its first field made unique, so a second one isn't a duplicate."""
    fields = dict(fields or {"Front": "f", "Back": "b"})
    first = next(iter(fields))
    n = next(_made)
    fields[first] += f" {n}" if n else ""
    return client.post("/v1/notes", json={"noteTypeName": note_type, "deckName": "Default",
                                          "fields": fields}).json()["created"][0]["id"]


def add_in_anki(col, note_type, **fields):
    """A note the API would refuse to create, such as a cloze in Basic (6.85),
    added as an import or another add-on could."""
    note = col.new_note(col.models.by_name(note_type))
    for name, value in fields.items():
        note[name] = value
    col.add_note(note, 1)
    return note.id


def change(client, note_ids, note_type, **body):
    return client.post(ROUTE, json={"note_ids": note_ids, "note_type_name": note_type, **body})


def cards_of(col, nids):
    return {cid for nid in nids for cid in col.card_ids_of_note(nid)}


def test_a_dry_run_answers_the_maps_and_changes_nothing(client, col):
    nids = [add(client), add(client)]
    undo = col.undo_status().undo
    resp = change(client, nids, REVERSED, dry_run=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["affected"] == 2 and body["dry_run"] is True
    assert body["fields"] == {"Front": "Front", "Back": "Back"}
    assert body["templates"] == {"Card 1": "Card 1", "Card 2": None}
    assert body["lost_fields"] == [] and body["cards_removed"] == 0
    assert {col.get_note(n).note_type()["name"] for n in nids} == {"Basic"}
    assert col.undo_status().undo == undo


def test_the_change_keeps_reviews_adds_cards_and_is_one_undo_step(client, col):
    nid = add(client)
    [cid] = col.card_ids_of_note(nid)
    front = col.get_note(nid)["Front"]
    client.post("/v1/cards:answer", json={"answers": [{"card_id": cid, "rating": 3}]})
    resp = change(client, [nid], REVERSED)
    assert resp.status_code == 200 and resp.json()["affected"] == 1, resp.text
    note = col.get_note(nid)
    assert note.note_type()["name"] == REVERSED and note["Front"] == front
    assert cid in note.card_ids() and len(note.card_ids()) == 2  # Card 2 made
    assert col.get_card(cid).reps == 1
    assert col.undo_status().undo == "Change Note Type"
    col.undo()
    assert col.get_note(nid).note_type()["name"] == "Basic"


@pytest.mark.parametrize("old, new, fields, removed", [
    (REVERSED, "Basic", {"Front": "f", "Back": "b"}, 1),
    ("Cloze", "Basic", {"Text": "{{c1::a}} {{c2::b}} {{c3::c}}"}, 2),
    ("Basic", "Cloze", {"Front": "{{c1::a}}", "Back": "b"}, 0),
    (REVERSED, "Cloze", {"Front": "{{c1::a}}", "Back": "b"}, 0),
])
def test_the_dry_run_counts_the_cards_the_change_removes(client, col, old, new, fields, removed):
    nids = [add_in_anki(col, old, **fields), add_in_anki(col, old, **fields)]
    plan = change(client, nids, new, dry_run=True).json()
    before = cards_of(col, nids)
    done = change(client, nids, new).json()
    assert plan["cards_removed"] == done["cards_removed"] == removed * 2
    assert len(before - cards_of(col, nids)) == removed * 2
    assert {k: v for k, v in plan.items() if k not in ("dry_run", "stats")} == \
        {k: v for k, v in done.items() if k not in ("dry_run", "stats")}


def test_named_maps_move_content_and_cards(client, col):
    nid = add(client, REVERSED)
    first, second = sorted(col.card_ids_of_note(nid), key=lambda c: col.get_card(c).ord)
    resp = change(client, [nid], REVERSED, fields={"Front": "Back", "Back": None},
                  templates={"Card 1": "Card 2", "Card 2": None})
    assert resp.json()["lost_fields"] == ["Front"] and resp.json()["cards_removed"] == 1
    note = col.get_note(nid)
    assert (note["Front"], note["Back"]) == ("b", "")
    assert col.get_card(second).ord == 0 and first not in col.card_ids_of_note(nid)


@pytest.mark.parametrize("body, words", [
    ({"fields": {"Nope": "Front"}}, "no field 'Nope'"),
    ({"fields": {"Front": "Nope"}}, "no field 'Nope'"),
    ({"templates": {"Card 9": "Card 1"}}, "no card template 'Card 9'"),
])
def test_unknown_names_are_refused(client, col, body, words):
    nid = add(client)
    resp = change(client, [nid], REVERSED, **body)
    assert resp.status_code == 400 and words in resp.json()["detail"], resp.text
    assert col.get_note(nid).note_type()["name"] == "Basic"


def test_templates_with_a_cloze_note_type_are_refused(client, col):
    nid = add(client)
    resp = change(client, [nid], "Cloze", templates={"Cloze": "Card 1"})
    assert resp.status_code == 400 and "cloze" in resp.json()["detail"]


def test_notes_of_two_note_types_are_refused(client, col):
    nids = [add(client), add(client, REVERSED)]
    resp = change(client, nids, "Cloze")
    assert resp.status_code == 409 and "Basic" in resp.json()["detail"] \
        and REVERSED in resp.json()["detail"]
    assert col.get_note(nids[0]).note_type()["name"] == "Basic"


def test_an_unknown_note_type_is_404(client, col):
    assert change(client, [add(client)], "Nope").status_code == 404


def test_missing_notes_are_skipped_and_none_writes_nothing(client, col):
    nid = add(client)
    assert change(client, [nid, 1], REVERSED).json()["affected"] == 1
    undo = col.undo_status().undo
    resp = change(client, [1, 2], "Basic")
    assert resp.status_code == 200 and resp.json()["affected"] == 0
    assert col.undo_status().undo == undo


def test_a_note_type_is_required(client, col):
    assert client.post(ROUTE, json={"note_ids": [add(client)]}).status_code == 422


@pytest.mark.usefixtures("review_events")
def test_events_name_the_notes_and_cards(client, col, recorded_ops):
    nid = add(client, REVERSED)
    old = set(col.card_ids_of_note(nid))
    broker.start_session(col)
    token = broker.subscribe(types={"change"})
    change(client, [nid], "Basic")
    op = recorded_ops[-1]
    dispatch_op(op.result.changes, op.initiator)
    events = {e["type"]: e for e in broker.drain(token)}
    kept = set(col.card_ids_of_note(nid))
    assert events["notes.updated"]["ids"] == [nid]
    assert set(events["cards.deleted"]["ids"]) == old - kept
    assert set(events["cards.updated"]["ids"]) == kept
    broker.begin_drain()


def test_a_change_that_changes_nothing_writes_nothing(client, col):
    nid = add(client, REVERSED)
    undo = col.undo_status().undo
    resp = change(client, [nid], REVERSED)
    assert resp.status_code == 200 and resp.json()["affected"] == 1
    assert col.undo_status().undo == undo
    swapped = change(client, [nid], REVERSED, fields={"Front": "Back", "Back": "Front"})
    assert swapped.status_code == 200 and col.undo_status().undo == "Change Note Type"

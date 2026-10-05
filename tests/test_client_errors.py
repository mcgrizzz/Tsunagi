"""
A client's mistake is never a 500 (backlog 6.70). Each case here answered 500
when a probe sent typical bad input to every /v1 write: duplicate ids, card id
0, integers SQLite can't store, unusable file paths.
"""
import pytest

DUPLICABLE = [
    ("/v1/cards:suspend", {}),
    ("/v1/cards:unsuspend", {}),
    ("/v1/cards:bury", {}),
    ("/v1/cards:unbury", {}),
    ("/v1/cards:set-flag", {"flag": 1}),
    ("/v1/cards:change-deck", {"deck_id": 1}),
]


@pytest.fixture()
def note(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "front"
    col.add_note(note, 1)
    return note


@pytest.mark.parametrize("path,extra", DUPLICABLE, ids=[p for p, _ in DUPLICABLE])
def test_a_repeated_card_id_counts_once(client, note, path, extra):
    cid = note.cards()[0].id
    resp = client.post(path, json={"card_ids": [cid, cid], **extra})
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected"] <= 1


@pytest.mark.parametrize("path", ["/v1/tags:bulk-add", "/v1/tags:bulk-remove"])
def test_a_repeated_note_id_counts_once(client, note, path):
    resp = client.post(path, json={"note_ids": [note.id, note.id], "tags": "verb"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected"] <= 1


@pytest.mark.parametrize("path,entry", [
    ("/v1/cards:answer", {"answers": [{"card_id": 0, "rating": 3}]}),
    ("/v1/cards:set-ease", {"cards": [{"id": 0, "ease_factor": 2500}]}),
    ("/v1/cards:set-memory-state", {"cards": [{"id": 0, "desired_retention": 0.9}]}),
])
def test_card_id_zero_is_a_missing_card(client, reset_settings, path, entry):
    # Anki's get_card(0) builds a blank card instead of raising NotFoundError.
    reset_settings.update(no_key_local_role="everything")
    resp = client.post(path, json=entry)
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected"] == 0


@pytest.mark.parametrize("field", ["id", "card_id", "interval", "ease_factor", "duration_ms"])
def test_review_values_beyond_64_bits_are_refused(client, note, field):
    row = {"id": 1700000000000, "card_id": note.cards()[0].id, field: 2 ** 63}
    resp = client.post("/v1/reviews", json={"reviews": [row]})
    assert resp.status_code == 422, resp.text
    assert client.get("/v1/reviews?include=total&limit=0").json()["total"] == 0


UNUSABLE_PATHS = ["", "\u0000", "missing/x.apkg"]


@pytest.mark.parametrize("path", UNUSABLE_PATHS)
def test_an_unusable_import_path_is_a_400(client, tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)  # relative paths resolve here, never in the checkout
    resp = client.post("/v1/collection:import", json={"path": path})
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize("path", UNUSABLE_PATHS)
def test_an_unusable_export_path_is_a_400(client, tmp_path, monkeypatch, path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    resp = client.post("/v1/collection:export", json={"deck_name": "Default", "path": path})
    assert resp.status_code == 400, resp.text
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("value", ["x", 1.5])
def test_a_column_value_of_the_wrong_type_is_a_400(client, note, value):
    resp = client.post("/v1/cards:set-values",
                       json={"card_id": note.cards()[0].id, "values": {"due": value}})
    assert resp.status_code == 400, resp.text
    assert "integer" in resp.json()["detail"]

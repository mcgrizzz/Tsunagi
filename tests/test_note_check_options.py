"""Skipping duplicate IDs must retain validation and the caller's duplicate policy."""
from copy import deepcopy

import pytest

from tsunagi.adapters.anki import notes
from tsunagi.shared.schemas.notes import NoteCreate


def candidate(front="word", **options):
    return {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": front, "Back": "meaning"}, **options}


def test_response_schema_still_validates_and_filters_adapter_records(client, monkeypatch):
    from fastapi.exceptions import ResponseValidationError

    records = [{"index": "0", "can_add": True, "state": "normal",
                "duplicate_note_ids": [], "internal": "hidden"}]
    monkeypatch.setattr("tsunagi.http.v1.notes.check_notes", lambda *args, **kwargs: records)
    response = client.post("/v1/notes:check", json={"notes": [candidate()]})
    assert response.status_code == 200
    assert response.json()["results"] == [{
        "index": 0, "can_add": True, "state": "normal", "reason": None,
        "duplicate_note_ids": [],
    }]

    records[0]["index"] = "invalid"
    with pytest.raises(ResponseValidationError):
        client.post("/v1/notes:check", json={"notes": [candidate()]})


def test_skipping_ids_preserves_all_other_results(client, col, monkeypatch):
    client.post("/v1/notes", json=candidate())
    submitted = [candidate(), candidate(allowDuplicate=True), candidate("new"),
                 candidate(""), candidate(modelName="missing"), candidate(deckName="missing"),
                 candidate(fields={"Missing": "field"})]
    original = deepcopy(submitted)
    expected = client.post("/v1/notes:check", json={"notes": submitted}).json()["results"]
    before = col.undo_status()
    def unexpected(*args):
        pytest.fail("Validation-only requests must not search for duplicate IDs")
    monkeypatch.setattr(notes, "_duplicate_ids", unexpected)
    response = client.post("/v1/notes:check?include_duplicate_ids=false", json={"notes": submitted})
    assert response.status_code == 200, response.text
    for row in expected:
        row["duplicate_note_ids"] = None
    assert response.json()["results"] == expected
    assert submitted == original
    assert col.note_count() == 1
    assert col.undo_status() == before


def test_default_and_explicit_ids_use_live_collection(client, col):
    body = {"notes": [candidate()]}
    assert client.post("/v1/notes:check", json=body).json()["results"][0]["duplicate_note_ids"] == []
    nid = client.post("/v1/notes", json=candidate()).json()["created"][0]["id"]
    for suffix in ["", "?include_duplicate_ids=true"]:
        result = client.post("/v1/notes:check" + suffix, json=body).json()["results"][0]
        assert result["state"] == "duplicate"
        assert result["duplicate_note_ids"] == [nid]
    col.undo()
    result = client.post("/v1/notes:check", json=body).json()["results"][0]
    assert result["state"] == "normal"
    assert result["duplicate_note_ids"] == []


def test_adapter_reuses_validated_candidate_without_converting_or_changing_it(col, monkeypatch):
    req = NoteCreate.parse_obj(candidate(fields=[{"name": "Front", "value": "word"}]))
    original = req.copy(deep=True)
    def unexpected(*args, **kwargs):
        pytest.fail("Already validated input should not be serialized or parsed again")
    monkeypatch.setattr(NoteCreate, "dict", unexpected)
    monkeypatch.setattr(NoteCreate, "parse_obj", unexpected)
    result = notes.check_notes.__wrapped__(col, [req], include_duplicate_ids=False)
    assert result[0]["can_add"] is True
    assert req.__dict__ == original.__dict__


@pytest.mark.parametrize("params,body", [
    ({"include_duplicate_ids": "invalid"}, {"notes": [candidate()]}),
    ({"include_duplicate_ids": "false"}, {"notes": [{}]}),
])
def test_malformed_request_does_not_reach_anki(client, monkeypatch, params, body):
    def unexpected(*args, **kwargs):
        pytest.fail("Request validation must happen before collection work")
    monkeypatch.setattr("tsunagi.http.v1.notes.check_notes", unexpected)
    assert client.post("/v1/notes:check", params=params, json=body).status_code == 422


@pytest.mark.parametrize("path", ["/v1/notes", "/v1/notes:check"])
@pytest.mark.parametrize("scope", ["deck", "unknown"])
def test_unsupported_duplicate_scope_is_not_silently_treated_as_collection(client, col, path, scope):
    submitted = [candidate("valid"), candidate("scoped", duplicateScope=scope)]
    body = {"notes": submitted} if path.endswith(":check") else submitted
    response = client.post(path, json=body)
    assert response.status_code == 422, response.text
    assert "duplicateScope" in response.text
    assert col.note_count() == 0


@pytest.mark.parametrize("scope", [None, "collection"])
def test_supported_scope_values_remain_accepted(client, scope):
    note = candidate(duplicateScope=scope)
    assert client.post("/v1/notes:check", json={"notes": [note]}).json()["results"][0]["can_add"]
    assert client.post("/v1/notes", json=note).json()["created"]

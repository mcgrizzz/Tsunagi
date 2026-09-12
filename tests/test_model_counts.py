"""Live derived model counts must not make ordinary metadata queries expensive."""
from unittest.mock import Mock, patch

import pytest

from tsunagi.adapters.anki.models import get_models_by_ids


def add(col, model, text):
    note = col.new_note(model)
    note.fields = [text, "back"]
    col.add_note(note, 1)
    return note.id


@pytest.mark.parametrize("method", ["get", "post"])
def test_counts_filter_before_pagination_and_stay_live(client, col, method):
    model = col.models.by_name("Basic (and reversed card)")
    ids = [add(col, model, str(i)) for i in range(2)]
    assert sum(len(col.card_ids_of_note(nid)) for nid in ids) == 4

    def query():
        data = {"select": "id,name,note_count", "where": ["note_count>0"], "limit": 1}
        response = (client.get("/v1/models", params=data) if method == "get" else
                    client.post("/v1/models/query", json=data))
        assert response.status_code == 200, response.text
        return response.json()

    assert query()["items"] == [{"id": model["id"], "name": model["name"], "note_count": 2}]
    col.remove_notes([ids[0]])
    assert query()["items"][0]["note_count"] == 1
    col.undo()
    assert query()["items"][0]["note_count"] == 2
    col.remove_notes(ids)
    assert query()["items"] == []


@pytest.mark.parametrize("where", [None, 'name=="Basic"'])
def test_metadata_counts_do_not_load_models(client, col, where):
    params = {"select": "id,name,note_count"}
    if where:
        params["where"] = where
    with patch.object(col.models, "all_use_counts", wraps=col.models.all_use_counts) as count:
        with patch.object(col.models, "get", side_effect=AssertionError("full model load")):
            response = client.get("/v1/models", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["items"]
    assert all(row["note_count"] == 0 for row in response.json()["items"])
    count.assert_called_once()


def test_names_only_do_not_count(client, col, monkeypatch):
    monkeypatch.setattr(col.models, "all_use_counts", Mock(side_effect=AssertionError))
    monkeypatch.setattr(col.models, "use_count", Mock(side_effect=AssertionError))
    response = client.get("/v1/models", params={"select": "id,name"})
    assert response.status_code == 200
    assert all(set(row) == {"id", "name"} for row in response.json()["items"])


def test_rich_and_full_reads_count_only_hydrated_models(client, col):
    for select in [None, "id,name,fields[].name,note_count"]:
        params = {"limit": 1}
        if select:
            params["select"] = select
        with patch.object(col.models, "get", wraps=col.models.get) as get:
            with patch.object(col.models, "use_count", wraps=col.models.use_count) as count:
                response = client.get("/v1/models", params=params)
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["note_count"] == 0
        assert get.call_count == count.call_count == 1


def test_shared_fetch_does_not_add_counts_or_mutate_anki_model(col):
    model = col.models.by_name("Basic")
    with patch.object(col.models, "use_count", side_effect=AssertionError):
        info = get_models_by_ids([model["id"]])[0]
    assert info.note_count is None
    assert "note_count" not in col.models.get(model["id"])


def test_count_filter_is_loaded_even_when_not_returned(client, col):
    model = col.models.by_name("Basic")
    add(col, model, "only used model")
    response = client.get("/v1/models", params={"select": "id,name", "where": "note_count>0"})
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": model["id"], "name": "Basic"}]


def test_missing_id_does_not_become_zero_count_model(client):
    response = client.get("/v1/models", params={
        "select": "id,note_count", "where": "id in [1,2]",
    })
    assert response.status_code == 200
    assert response.json()["items"] == []

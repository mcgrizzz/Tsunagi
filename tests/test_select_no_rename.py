"""
`select` doesn't rename fields (backlog 6.76): `name:label` renamed the output
key, a second name for every field that a client can give in one line itself.
"""
import pytest


@pytest.mark.parametrize("select", [
    "name:label",
    "id,name:label",
    "fields[].name:names",
    "fields[].(name:n,ord)",
    "fields[].(name,ord):pairs",
])
def test_renaming_in_select_is_a_400(client, select):
    resp = client.get("/v1/models", params={"select": select})
    assert resp.status_code == 400, resp.text
    assert "rename" in resp.json()["detail"]


def test_a_colon_in_a_filter_value_is_still_text(client):
    client.post("/v1/notes", json={"model_name": "Basic", "deck_name": "Default",
                                   "fields": {"Front": "x:y", "Back": "z"}})
    resp = client.get("/v1/notes", params={"select": 'fields[value in ["x:y"]].name'})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == [{"fields": ["Front"]}]

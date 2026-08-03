"""
Full-app tests for /v1/notes over the fake collection.
"""
import pytest


def add(client, front="犬", back="dog", model="Basic", deck="Default", tags=None):
    body = {"modelName": model, "deckName": deck, "fields": {"Front": front, "Back": back}}
    if model == "Cloze":
        body["fields"] = {"Text": front, "Back Extra": back}
    if tags is not None:
        body["tags"] = tags
    return client.post("/v1/notes", json=body)


@pytest.fixture()
def seeded(client):
    add(client, "犬", "dog", tags=["vocab"])
    add(client, "猫", "cat", tags=["vocab", "verb"])
    return client


class TestReads:
    def test_bare_list_uses_scan_tier(self, seeded):
        body = seeded.get("/v1/notes").json()
        assert len(body["items"]) == 2
        assert body["items"][0]["model_name"] == "Basic"

    def test_pagination_walks_all(self, seeded):
        seen, cursor = [], None
        while True:
            params = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = seeded.get("/v1/notes", params=params).json()
            seen += [n["id"] for n in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 2

    def test_search_by_tag(self, seeded):
        body = seeded.get("/v1/notes", params={"search": "tag:verb"}).json()
        assert [n["fields"][0]["value"] for n in body["items"]] == ["猫"]

    def test_search_by_text(self, seeded):
        body = seeded.get("/v1/notes", params={"search": "犬"}).json()
        assert len(body["items"]) == 1

    def test_search_by_deck(self, seeded):
        assert len(seeded.get("/v1/notes", params={"search": "deck:Default"}).json()["items"]) == 2

    def test_malformed_search_is_400(self, seeded):
        # zzz:nope is legal to Anki and simply matches nothing; an unbalanced
        # quote is what the parser refuses.
        assert seeded.get("/v1/notes", params={"search": '"unbalanced'}).status_code == 400

    def test_id_index_avoids_search(self, seeded, col):
        nid = seeded.get("/v1/notes").json()["items"][0]["id"]
        calls = []
        original = col.find_notes
        col.find_notes = lambda q, **kw: calls.append(q) or original(q, **kw)
        body = seeded.get("/v1/notes", params={"where": f"id=={nid}"}).json()
        assert [n["id"] for n in body["items"]] == [nid]
        assert calls == []                     # index tier, no search

    def test_where_on_nested_fields(self, seeded):
        body = seeded.get("/v1/notes", params={"where": "fields[].value==犬"}).json()
        assert len(body["items"]) == 1

    def test_select_projection(self, seeded):
        body = seeded.get("/v1/notes", params={
            "select": "id,fields[].(name,value)", "shape": "object"}).json()
        assert set(body["items"][0]) == {"id", "fields"}

    def test_cards_only_computed_when_requested(self, seeded):
        # Demand-driven hydration: `cards` costs a backend call per note
        full = seeded.get("/v1/notes").json()["items"][0]
        assert full["cards"]  # no select -> whole record
        lean = seeded.get("/v1/notes", params={"select": "id,model_name", "shape": "object"}).json()
        assert "cards" not in lean["items"][0]

    def test_limit_counts_returned_items_not_rows_scanned(self, client):
        # Contract: `limit` bounds the RESULTS. It is never a bound on how
        # much of the collection is examined - matches buried past the first
        # `limit` rows must still be found (see the completeness guarantee).
        for i in range(20):
            add(client, front=("犬" if i % 7 == 0 else "other") + str(i))
        body = client.get("/v1/notes", params={
            "where": "fields[].value~=犬", "limit": 2}).json()
        assert len(body["items"]) == 2               # exactly the page asked for
        assert all("犬" in n["fields"][0]["value"] for n in body["items"])
        assert body["next_cursor"] is not None       # a third match remains

    def test_get_post_parity(self, seeded):
        get_body = seeded.get("/v1/notes", params={"search": "tag:vocab", "select": "id"}).json()
        post_body = seeded.post("/v1/notes/query",
                                json={"search": "tag:vocab", "select": "id"}).json()
        assert get_body["items"] == post_body["items"]


class TestCreate:
    def test_create_with_field_map(self, client):
        resp = add(client)
        assert resp.status_code == 201
        note = resp.json()["result"]
        assert [f["value"] for f in note["fields"]] == ["犬", "dog"]
        assert note["cards"]

    def test_create_with_field_array(self, client):
        resp = client.post("/v1/notes", json={
            "modelName": "Basic", "deckName": "Default",
            "fields": [{"name": "Front", "value": "鳥"}, {"name": "Back", "value": "bird"}],
        })
        assert resp.status_code == 201
        assert [f["value"] for f in resp.json()["result"]["fields"]] == ["鳥", "bird"]

    def test_create_by_ids(self, client):
        mid = client.get("/v1/models", params={
            "where": "name==Basic", "select": "id", "shape": "scalar"}).json()["items"][0]
        resp = client.post("/v1/notes", json={
            "modelId": mid, "deckId": 1, "fields": {"Front": "鳥"}})
        assert resp.status_code == 201, resp.text

    def test_unknown_field_is_400(self, client):
        resp = client.post("/v1/notes", json={
            "modelName": "Basic", "deckName": "Default", "fields": {"Nope": "x"}})
        assert resp.status_code == 400

    def test_unknown_model_is_400(self, client):
        assert add(client, model="Nope").status_code == 400

    def test_unknown_deck_does_not_create_it(self, client):
        assert add(client, deck="Nope").status_code == 400
        names = [d["name"] for d in client.get("/v1/decks").json()["items"]]
        assert "Nope" not in names

    def test_empty_first_field_is_400(self, client):
        assert add(client, front="").status_code == 400

    def test_cloze_without_marker_is_400(self, client):
        assert add(client, front="no cloze here", model="Cloze").status_code == 400

    def test_cloze_with_marker_is_created(self, client):
        assert add(client, front="{{c1::犬}}", model="Cloze").status_code == 201

    def test_duplicate_is_409(self, client):
        add(client)
        resp = add(client)
        assert resp.status_code == 409
        assert "duplicat" in resp.json()["detail"].lower()

    def test_duplicate_allowed_when_requested(self, client):
        add(client)
        resp = client.post("/v1/notes", json={
            "modelName": "Basic", "deckName": "Default",
            "fields": {"Front": "犬"}, "allowDuplicate": True})
        assert resp.status_code == 201


class TestPatch:
    def test_patch_fields_is_partial(self, client):
        nid = add(client).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}", json={"fields": {"Back": "hound"}})
        values = [f["value"] for f in resp.json()["result"]["fields"]]
        assert values == ["犬", "hound"]  # Front untouched

    def test_patch_tags_replaces(self, client):
        nid = add(client, tags=["a", "b"]).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}", json={"tags": ["c"]})
        assert resp.json()["result"]["tags"] == ["c"]

    def test_add_and_remove_tags(self, client):
        nid = add(client, tags=["a"]).json()["result"]["id"]
        client.patch(f"/v1/notes/{nid}", json={"addTags": ["b"]})
        resp = client.patch(f"/v1/notes/{nid}", json={"removeTags": ["a"]})
        assert resp.json()["result"]["tags"] == ["b"]

    def test_tags_with_add_tags_is_400(self, client):
        nid = add(client).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}", json={"tags": ["x"], "addTags": ["y"]})
        assert resp.status_code == 400

    def test_patch_missing_is_404(self, client):
        assert client.patch("/v1/notes/999999", json={"tags": []}).status_code == 404


class TestChangeModel:
    """Retyping a note - the native home for AnkiConnect's updateNoteModel."""

    def test_change_model_by_name(self, client):
        nid = add(client, tags=["keep"]).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}", json={
            "modelName": "Cloze", "fields": {"Text": "{{c1::犬}}"}})
        assert resp.status_code == 200
        note = resp.json()["result"]
        assert note["model_name"] == "Cloze"
        assert [f["name"] for f in note["fields"]] == ["Text", "Back Extra"]
        assert note["fields"][0]["value"] == "{{c1::犬}}"
        assert note["tags"] == ["keep"]        # tags survive the retype

    def test_change_model_by_id(self, client):
        cloze_id = client.get("/v1/models", params={
            "where": "name==Cloze", "select": "id", "shape": "scalar"}).json()["items"][0]
        nid = add(client).json()["result"]["id"]
        note = client.patch(f"/v1/notes/{nid}", json={
            "modelId": cloze_id, "fields": {"Text": "{{c1::猫}}"}}).json()["result"]
        assert note["model_id"] == cloze_id

    def test_change_model_without_fields_is_400(self, client):
        # The resize blanks every field, so a bare model change would erase
        # the note. Refuse rather than silently destroy content.
        nid = add(client).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}", json={"modelName": "Cloze"})
        assert resp.status_code == 400
        assert "erase" in resp.json()["detail"]
        note = client.get("/v1/notes", params={"where": f"id=={nid}"}).json()["items"][0]
        assert note["fields"][0]["value"] == "犬"   # untouched

    def test_unknown_model_is_400(self, client):
        nid = add(client).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}",
                            json={"modelName": "Nope", "fields": {"Front": "x"}})
        assert resp.status_code == 400

    def test_fields_not_on_the_new_model_are_400(self, client):
        nid = add(client).json()["result"]["id"]
        resp = client.patch(f"/v1/notes/{nid}",
                            json={"modelName": "Cloze", "fields": {"Front": "x"}})
        assert resp.status_code == 400


class TestDelete:
    def test_delete_removes_note_and_cards(self, client, col):
        nid = add(client).json()["result"]["id"]
        assert client.delete(f"/v1/notes/{nid}").json()["success"] is True
        assert client.get("/v1/notes").json()["items"] == []
        assert col.card_ids_of_note(nid) == []

    def test_delete_missing_is_404(self, client):
        assert client.delete("/v1/notes/999999").status_code == 404


class TestCheck:
    def check(self, client, notes):
        return client.post("/v1/notes:check", json={"notes": notes}).json()["results"]

    def test_normal_can_add(self, client):
        (res,) = self.check(client, [{"modelName": "Basic", "deckName": "Default",
                                      "fields": {"Front": "新しい"}}])
        assert res == {"index": 0, "can_add": True, "state": "normal",
                       "reason": None, "duplicate_note_ids": []}

    def test_duplicate_reports_existing_id(self, client):
        nid = add(client).json()["result"]["id"]
        (res,) = self.check(client, [{"modelName": "Basic", "deckName": "Default",
                                      "fields": {"Front": "犬"}}])
        assert res["can_add"] is False
        assert res["state"] == "duplicate"
        assert res["duplicate_note_ids"] == [nid]

    def test_duplicate_allowed_can_add(self, client):
        add(client)
        (res,) = self.check(client, [{"modelName": "Basic", "deckName": "Default",
                                      "fields": {"Front": "犬"}, "allowDuplicate": True}])
        assert res["can_add"] is True
        assert res["state"] == "duplicate"

    def test_empty_first_field(self, client):
        (res,) = self.check(client, [{"modelName": "Basic", "deckName": "Default",
                                      "fields": {"Front": ""}}])
        assert (res["can_add"], res["state"]) == (False, "empty")

    def test_unknown_model_is_reported_not_raised(self, client):
        (res,) = self.check(client, [{"modelName": "Nope", "deckName": "Default",
                                      "fields": {"Front": "x"}}])
        assert res["can_add"] is False
        assert "Nope" in res["reason"]

    def test_order_and_indexes_preserved(self, client):
        add(client)
        results = self.check(client, [
            {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "新"}},
            {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬"}},
        ])
        assert [r["index"] for r in results] == [0, 1]
        assert [r["can_add"] for r in results] == [True, False]

    def test_check_adds_nothing(self, client, col):
        before = col.note_count()
        self.check(client, [{"modelName": "Basic", "deckName": "Default",
                             "fields": {"Front": "新しい"}}])
        assert col.note_count() == before

"""
Full-app tests for /v1/cards over the fake collection.
"""
import pytest


def add_note(client, front="犬", back="dog", deck="Default", model="Basic"):
    body = {"modelName": model, "deckName": deck, "fields": {"Front": front, "Back": back}}
    if model == "Cloze":
        body["fields"] = {"Text": front, "Back Extra": back}
    return client.post("/v1/notes", json=body).json()["result"]


@pytest.fixture()
def seeded(client):
    """Two notes in Default, one in JP - four cards total? No: Basic has one template."""
    add_note(client, "犬", "dog")
    add_note(client, "猫", "cat")
    client.post("/v1/decks", json={"name": "JP"})
    add_note(client, "鳥", "bird", deck="JP")
    return client


def ids(client, **params):
    return [c["id"] for c in client.get("/v1/cards", params=params).json()["items"]]


class TestReads:
    def test_bare_list_uses_scan_tier(self, seeded):
        body = seeded.get("/v1/cards").json()
        assert len(body["items"]) == 3
        assert body["items"][0]["deck_name"] == "Default"

    def test_search_by_deck(self, seeded):
        body = seeded.get("/v1/cards", params={"search": "deck:JP"}).json()
        assert [c["deck_name"] for c in body["items"]] == ["JP"]

    def test_malformed_search_is_400(self, seeded):
        assert seeded.get("/v1/cards", params={"search": "zzz:nope"}).status_code == 400

    def test_id_index_avoids_search(self, seeded, fake_col):
        cid = ids(seeded)[0]
        before = fake_col.find_notes_calls
        assert ids(seeded, where=f"id=={cid}") == [cid]
        assert fake_col.find_notes_calls == before  # index tier, no search

    def test_note_id_index(self, seeded):
        note = seeded.get("/v1/notes").json()["items"][0]
        body = seeded.get("/v1/cards", params={"where": f"note_id=={note['id']}"}).json()
        assert [c["id"] for c in body["items"]] == note["cards"]

    def test_derived_fields_are_free(self, seeded):
        card = seeded.get("/v1/cards", params={
            "select": "id,suspended,buried,flag", "shape": "object"}).json()["items"][0]
        assert card["suspended"] is False
        assert card["buried"] is False
        assert card["flag"] == 0

    def test_question_renders_the_template(self, seeded):
        body = seeded.get("/v1/cards", params={
            "select": "question", "shape": "scalar", "search": "deck:JP"}).json()
        assert body["items"] == ["鳥"]        # seed qfmt is "{{Front}}"

    def test_note_fields_available_on_the_card(self, seeded):
        card = seeded.get("/v1/cards", params={
            "select": "id,fields[].(name,value)", "shape": "object",
            "search": "deck:JP"}).json()["items"][0]
        assert card["fields"] == [{"name": "Front", "value": "鳥"},
                                  {"name": "Back", "value": "bird"}]

    def test_where_on_nested_note_fields(self, seeded):
        body = seeded.get("/v1/cards", params={"where": "fields[].value==犬"}).json()
        assert len(body["items"]) == 1

    def test_expensive_fields_skipped_when_not_selected(self, seeded, fake_col):
        calls = []
        original = fake_col.get_note
        fake_col.get_note = lambda nid: calls.append(nid) or original(nid)

        seeded.get("/v1/cards", params={"select": "id,due,queue"})
        assert calls == []                      # no note loaded for a cheap select

        seeded.get("/v1/cards", params={"select": "id,model_name"})
        assert len(calls) == 3                  # one per card, only when asked

    def test_bare_listing_includes_rendered_fields(self, seeded):
        card = seeded.get("/v1/cards").json()["items"][0]
        # No select means the whole record - consistent with every resource.
        assert card["question"] and card["model_name"] == "Basic"
        assert card["next_reviews"] == ["<1m", "<10m", "1d", "4d"]

    def test_due_is_passed_through_raw(self, seeded):
        # New cards carry a queue position in `due`, not a timestamp.
        dues = seeded.get("/v1/cards", params={
            "select": "due", "shape": "scalar"}).json()["items"]
        assert dues == sorted(dues) and all(0 < d < 1000 for d in dues)

    def test_get_post_parity(self, seeded):
        get_body = seeded.get("/v1/cards", params={"search": "deck:JP", "select": "id"}).json()
        post_body = seeded.post("/v1/cards/query",
                                json={"search": "deck:JP", "select": "id"}).json()
        assert get_body["items"] == post_body["items"]

    def test_no_create_or_delete_routes(self, seeded):
        # Cards come from notes and templates; a POST/DELETE would be a lie.
        # POST hits the listing path (405); DELETE has no path at all (404).
        assert seeded.post("/v1/cards", json={}).status_code == 405
        assert seeded.delete(f"/v1/cards/{ids(seeded)[0]}").status_code == 404


class TestSuspendBury:
    def test_suspend_and_unsuspend(self, seeded):
        cid = ids(seeded)[0]
        assert seeded.post("/v1/cards:suspend", json={"card_ids": [cid]}
                           ).json()["affected"] == 1
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert card["suspended"] is True and card["queue"] == -1

        seeded.post("/v1/cards:unsuspend", json={"card_ids": [cid]})
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert card["suspended"] is False and card["queue"] == 0

    def test_bury_and_unbury(self, seeded):
        cid = ids(seeded)[0]
        seeded.post("/v1/cards:bury", json={"card_ids": [cid]})
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert card["buried"] is True and card["queue"] == -3  # manually buried

        seeded.post("/v1/cards:unbury", json={"card_ids": [cid]})
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["buried"] is False

    def test_batch_affects_every_card(self, seeded):
        all_ids = ids(seeded)
        assert seeded.post("/v1/cards:suspend", json={"card_ids": all_ids}
                           ).json()["affected"] == 3

    def test_camel_case_body_accepted(self, seeded):
        # Same alias tolerance as the rest of the write surface.
        assert seeded.post("/v1/cards:suspend", json={"cardIds": ids(seeded)[:1]}
                           ).json()["affected"] == 1


class TestScheduling:
    def test_set_due_date(self, seeded):
        cid = ids(seeded)[0]
        assert seeded.post("/v1/cards:set-due-date",
                           json={"card_ids": [cid], "days": "5"}).json()["affected"] == 1
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert (card["type"], card["queue"], card["due"]) == (2, 2, 5)

    def test_set_due_date_rejects_garbage(self, seeded):
        resp = seeded.post("/v1/cards:set-due-date",
                           json={"card_ids": ids(seeded)[:1], "days": "soon"})
        assert resp.status_code == 400

    def test_forget_returns_card_to_new(self, seeded):
        cid = ids(seeded)[0]
        seeded.post("/v1/cards:set-due-date", json={"card_ids": [cid], "days": "5"})
        seeded.post("/v1/cards:forget", json={"card_ids": [cid]})
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert (card["type"], card["queue"], card["interval"]) == (0, 0, 0)

    def test_reposition(self, seeded):
        all_ids = sorted(ids(seeded))
        seeded.post("/v1/cards:reposition", json={
            "card_ids": all_ids, "starting_from": 10, "step_size": 5})
        dues = {c["id"]: c["due"] for c in seeded.get("/v1/cards").json()["items"]}
        assert [dues[c] for c in all_ids] == [10, 15, 20]

    def test_set_flag(self, seeded):
        cid = ids(seeded)[0]
        seeded.post("/v1/cards:set-flag", json={"card_ids": [cid], "flag": 3})
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["flag"] == 3

    def test_set_flag_rejects_out_of_range(self, seeded):
        resp = seeded.post("/v1/cards:set-flag",
                           json={"card_ids": ids(seeded)[:1], "flag": 9})
        assert resp.status_code == 422  # pydantic bound, before the adapter

    def test_set_ease(self, seeded):
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:set-ease",
                           json={"cards": [{"id": cid, "factor": 2500}]}).json()
        assert body["affected"] == 1
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["factor"] == 2500

    def test_set_ease_counts_only_real_cards(self, seeded):
        body = seeded.post("/v1/cards:set-ease", json={
            "cards": [{"id": ids(seeded)[0], "factor": 2500},
                      {"id": 999999, "factor": 2500}]}).json()
        assert body["affected"] == 1  # missing card doesn't fail the batch


class TestChangeDeck:
    def test_by_name(self, seeded):
        cid = ids(seeded, search="deck:Default")[0]
        assert seeded.post("/v1/cards:change-deck",
                           json={"card_ids": [cid], "deck_name": "JP"}
                           ).json()["affected"] == 1
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["deck_name"] == "JP"

    def test_by_id(self, seeded):
        did = [d["id"] for d in seeded.get("/v1/decks").json()["items"]
               if d["name"] == "JP"][0]
        cid = ids(seeded, search="deck:Default")[0]
        seeded.post("/v1/cards:change-deck", json={"card_ids": [cid], "deck_id": did})
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["deck_id"] == did

    def test_unknown_deck_name_is_400_and_creates_nothing(self, seeded):
        resp = seeded.post("/v1/cards:change-deck",
                           json={"card_ids": ids(seeded)[:1], "deck_name": "Nope"})
        assert resp.status_code == 400
        names = [d["name"] for d in seeded.get("/v1/decks").json()["items"]]
        assert "Nope" not in names

    def test_unknown_deck_id_is_404(self, seeded):
        resp = seeded.post("/v1/cards:change-deck",
                           json={"card_ids": ids(seeded)[:1], "deck_id": 999999})
        assert resp.status_code == 404

    def test_neither_target_is_400(self, seeded):
        assert seeded.post("/v1/cards:change-deck",
                           json={"card_ids": ids(seeded)[:1]}).status_code == 400

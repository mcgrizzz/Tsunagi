"""
Full-app tests for /v1/cards against a real collection.
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
        # Anki accepts zzz:nope (it just matches nothing); an unbalanced quote
        # is what the parser genuinely refuses.
        assert seeded.get("/v1/cards", params={"search": '"unbalanced'}).status_code == 400

    def test_unknown_search_key_is_not_an_error(self, seeded):
        body = seeded.get("/v1/cards", params={"search": "zzz:nope"})
        assert body.status_code == 200 and body.json()["items"] == []

    def test_id_index_avoids_search(self, seeded, col):
        cid = ids(seeded)[0]
        calls = []
        original = col.find_cards
        col.find_cards = lambda q, **kw: calls.append(q) or original(q, **kw)
        assert ids(seeded, where=f"id=={cid}") == [cid]
        assert calls == []                      # index tier, no search

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
        # Anki's rendered question carries the notetype's <style> block; the
        # field content is what this asserts.
        (question,) = body["items"]
        assert "鳥" in question and "<style>" in question

    def test_note_fields_available_on_the_card(self, seeded):
        card = seeded.get("/v1/cards", params={
            "select": "id,fields[].(name,value)", "shape": "object",
            "search": "deck:JP"}).json()["items"][0]
        assert card["fields"] == [{"name": "Front", "value": "鳥"},
                                  {"name": "Back", "value": "bird"}]

    def test_where_on_nested_note_fields(self, seeded):
        body = seeded.get("/v1/cards", params={"where": "fields[].value==犬"}).json()
        assert len(body["items"]) == 1

    def test_expensive_fields_skipped_when_not_selected(self, seeded, col):
        calls = []
        original = col.get_note
        col.get_note = lambda nid: calls.append(nid) or original(nid)

        seeded.get("/v1/cards", params={"select": "id,due,queue"})
        assert calls == []                      # no note loaded for a cheap select

        seeded.get("/v1/cards", params={"select": "id,model_name"})
        assert len(calls) == 3                  # one per card, only when asked

    def test_bare_listing_includes_rendered_fields(self, seeded):
        card = seeded.get("/v1/cards").json()["items"][0]
        # No select means the whole record - consistent with every resource.
        assert card["question"] and card["model_name"] == "Basic"
        # Anki formats these for display and wraps the numbers in Unicode
        # directional isolates, so assert the shape rather than the exact text.
        assert len(card["next_reviews"]) == 4
        assert all(isinstance(s, str) and s for s in card["next_reviews"])

    def test_due_is_passed_through_raw(self, seeded):
        # New cards carry a queue position in `due`, not a timestamp.
        dues = seeded.get("/v1/cards", params={
            "select": "due", "shape": "scalar"}).json()["items"]
        assert dues == sorted(dues) and all(0 < d < 1000 for d in dues)

    def test_fsrs_state_is_null_before_review(self, seeded):
        card = seeded.get("/v1/cards", params={
            "select": "id,memory_state,desired_retention,decay,last_review_time",
            "shape": "object"}).json()["items"][0]
        assert card["memory_state"] is None
        assert card["decay"] is None

    def test_fsrs_state_is_reported(self, seeded, col):
        # FSRS shipped in 23.10, our floor, and is the default since 24.11 -
        # memory state is part of a card, not an optional extra.
        from anki.cards import FSRSMemoryState
        cid = ids(seeded)[0]
        card = col.get_card(cid)
        card.memory_state = FSRSMemoryState(stability=42.5, difficulty=5.25)
        card.desired_retention = 0.9
        col.update_card(card)

        row = seeded.get("/v1/cards", params={
            "where": f"id=={cid}", "shape": "object"}).json()["items"][0]
        assert row["memory_state"] == pytest.approx(
            {"stability": 42.5, "difficulty": 5.25})
        # Anki stores desired_retention as a float32.
        assert row["desired_retention"] == pytest.approx(0.9)

    def test_fsrs_fields_degrade_on_older_anki(self, seeded, col):
        # decay and last_review_time postdate memory_state - anki 23.10, our
        # floor, has neither - so the reader must report null, not raise.
        cid = ids(seeded)[0]
        card = col.get_card(cid)
        row = seeded.get("/v1/cards", params={
            "where": f"id=={cid}", "shape": "object"}).json()["items"][0]
        for name in ("decay", "last_review_time"):
            if not hasattr(card, name):
                assert row[name] is None, name

    def test_custom_data_passes_through_unparsed(self, seeded, col):
        cid = ids(seeded)[0]
        card = col.get_card(cid)
        card.custom_data = '{"v":"3","seed":42}'
        col.update_card(card)
        row = seeded.get("/v1/cards", params={
            "where": f"id=={cid}", "select": "custom_data",
            "shape": "scalar"}).json()["items"][0]
        assert row == '{"v":"3","seed":42}'   # a string, not a decoded object

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


class TestAffectedCounts:
    """
    `affected` counts cards the call actually CHANGED, on every verb.

    Anki hands back a count for some scheduler ops and a bare OpChanges for
    others; reporting "however many ids you sent" for the latter meant
    unsuspending an unsuspended card claimed work it never did.
    """

    def test_suspend_ignores_already_suspended(self, seeded):
        all_ids = ids(seeded)
        seeded.post("/v1/cards:suspend", json={"card_ids": all_ids[:1]})
        assert seeded.post("/v1/cards:suspend", json={"card_ids": all_ids}
                           ).json()["affected"] == 2   # not 3

    def test_unsuspend_counts_only_suspended_cards(self, seeded):
        all_ids = ids(seeded)
        seeded.post("/v1/cards:suspend", json={"card_ids": all_ids[:1]})
        assert seeded.post("/v1/cards:unsuspend", json={"card_ids": all_ids}
                           ).json()["affected"] == 1

    def test_unsuspend_on_nothing_is_zero(self, seeded):
        assert seeded.post("/v1/cards:unsuspend", json={"card_ids": ids(seeded)}
                           ).json()["affected"] == 0

    def test_unbury_counts_only_buried_cards(self, seeded):
        all_ids = ids(seeded)
        seeded.post("/v1/cards:bury", json={"card_ids": all_ids[:2]})
        assert seeded.post("/v1/cards:unbury", json={"card_ids": all_ids}
                           ).json()["affected"] == 2

    def test_missing_ids_are_not_counted(self, seeded):
        body = seeded.post("/v1/cards:forget",
                           json={"card_ids": ids(seeded)[:1] + [999999]}).json()
        assert body["affected"] == 1

    def test_change_deck_ignores_cards_already_there(self, seeded):
        target = ids(seeded, search="deck:Default")
        seeded.post("/v1/cards:change-deck",
                    json={"card_ids": target, "deck_name": "JP"})
        assert seeded.post("/v1/cards:change-deck",
                           json={"card_ids": target, "deck_name": "JP"}
                           ).json()["affected"] == 0

    def test_set_flag_ignores_unchanged(self, seeded):
        cid = ids(seeded)[:1]
        seeded.post("/v1/cards:set-flag", json={"card_ids": cid, "flag": 3})
        assert seeded.post("/v1/cards:set-flag", json={"card_ids": cid, "flag": 3}
                           ).json()["affected"] == 0


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


class TestSetMemoryState:
    """POST /v1/cards:set-memory-state - opt-in via gates.cards_set_memory_state."""

    def _enable(self, reset_settings):
        reset_settings.update(gates={"cards_set_memory_state": True})

    def _write(self, client, entry):
        return client.post("/v1/cards:set-memory-state", json={"cards": [entry]})

    def _row(self, client, cid):
        return client.get("/v1/cards", params={
            "where": f"id=={cid}", "shape": "object"}).json()["items"][0]

    def test_disabled_by_default(self, seeded):
        cid = ids(seeded)[0]
        resp = self._write(seeded, {
            "id": cid, "memory_state": {"stability": 9.0, "difficulty": 3.0}})
        assert resp.status_code == 400
        assert "gates.cards_set_memory_state" in resp.json()["detail"]
        assert self._row(seeded, cid)["memory_state"] is None

    def test_write_round_trip(self, seeded, reset_settings):
        self._enable(reset_settings)
        cid = ids(seeded)[0]
        body = self._write(seeded, {
            "id": cid,
            "memory_state": {"stability": 99.5, "difficulty": 3.3},
            "desired_retention": 0.8,
        }).json()
        assert body["affected"] == 1
        row = self._row(seeded, cid)
        assert row["memory_state"] == pytest.approx(
            {"stability": 99.5, "difficulty": 3.3})
        assert row["desired_retention"] == pytest.approx(0.8)

    def test_null_clears_and_omitted_leaves_alone(self, seeded, reset_settings):
        self._enable(reset_settings)
        cid = ids(seeded)[0]
        self._write(seeded, {
            "id": cid,
            "memory_state": {"stability": 5.0, "difficulty": 5.0},
            "desired_retention": 0.85,
        })
        # Clearing memory_state must not touch the omitted desired_retention.
        assert self._write(seeded, {
            "id": cid, "memory_state": None}).json()["affected"] == 1
        row = self._row(seeded, cid)
        assert row["memory_state"] is None
        assert row["desired_retention"] == pytest.approx(0.85)

    def test_missing_card_doesnt_fail_the_batch(self, seeded, reset_settings):
        self._enable(reset_settings)
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:set-memory-state", json={"cards": [
            {"id": cid, "desired_retention": 0.7},
            {"id": 999999999, "desired_retention": 0.7},
        ]}).json()
        assert body["affected"] == 1

    def test_entry_with_nothing_to_write_counts_zero(self, seeded, reset_settings):
        self._enable(reset_settings)
        cid = ids(seeded)[0]
        assert self._write(seeded, {"id": cid}).json()["affected"] == 0

    def test_decay_by_version(self, seeded, reset_settings, col):
        # Per-card decay postdates the 23.10 floor: on a build without it the
        # whole batch is refused up front (501); where it exists it round-trips.
        self._enable(reset_settings)
        cid = ids(seeded)[0]
        resp = self._write(seeded, {"id": cid, "decay": 0.2})
        if hasattr(col.get_card(cid), "decay"):
            assert resp.status_code == 200
            assert self._row(seeded, cid)["decay"] == pytest.approx(0.2)
        else:
            assert resp.status_code == 501
            assert "Anki version" in resp.json()["detail"]
            assert self._row(seeded, cid)["memory_state"] is None


class TestRetrievability:
    """The want-gated FSRS recall probability, via col.card_stats_data."""

    def _rows(self, client):
        return client.get("/v1/cards", params={
            "select": "id,retrievability", "shape": "object"}).json()["items"]

    def test_no_backend_call_unless_selected(self, seeded, col):
        calls = []
        original = col.card_stats_data
        col.card_stats_data = lambda cid: calls.append(cid) or original(cid)

        seeded.get("/v1/cards", params={"select": "id,due,queue"})
        assert calls == []                      # cheap select stays cheap

        self._rows(seeded)
        assert len(calls) == 3                  # one per card, only when asked

    def test_null_before_any_review(self, seeded):
        assert all(r["retrievability"] is None for r in self._rows(seeded))

    def test_reported_after_a_real_fsrs_review(self, seeded, col, answer_cards):
        col.set_config("fsrs", True)
        assert answer_cards(1) == 1
        values = [r["retrievability"] for r in self._rows(seeded)
                  if r["retrievability"] is not None]
        # Only the answered card has been scored; recall is ~certain today.
        assert len(values) == 1
        assert values[0] == pytest.approx(1.0, abs=0.05)


class TestAnswer:
    def test_answer_advances_the_card(self, seeded):
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:answer",
                           json={"answers": [{"card_id": cid, "ease": 3}]}).json()
        assert body["affected"] == 1
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert card["reps"] == 1 and card["type"] != 0     # no longer new
        reviews = seeded.get("/v1/reviews",
                             params={"where": f"card_id=={cid}"}).json()["items"]
        assert [r["ease"] for r in reviews] == [3]         # a real revlog row

    def test_missing_card_is_skipped(self, seeded):
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:answer", json={"answers": [
            {"card_id": cid, "ease": 3}, {"card_id": 999999, "ease": 3}]}).json()
        assert body["affected"] == 1

    def test_ease_out_of_range_is_422(self, seeded):
        resp = seeded.post("/v1/cards:answer",
                           json={"answers": [{"card_id": ids(seeded)[0], "ease": 5}]})
        assert resp.status_code == 422  # pydantic bound, before the adapter

    def test_answering_a_suspended_card_unsuspends_it(self, seeded):
        cid = ids(seeded)[0]
        seeded.post("/v1/cards:suspend", json={"card_ids": [cid]})
        body = seeded.post("/v1/cards:answer",
                           json={"answers": [{"card_id": cid, "ease": 3}]}).json()
        assert body["affected"] == 1
        card = seeded.get("/v1/cards", params={"where": f"id=={cid}"}).json()["items"][0]
        assert card["suspended"] is False


class TestSetValues:
    def test_plain_column_write(self, seeded):
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:set-values",
                           json={"card_id": cid, "values": {"factor": 2600}}).json()
        assert body["affected"] == 1
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["factor"] == 2600

    def test_risky_column_needs_force(self, seeded):
        cid = ids(seeded)[0]
        resp = seeded.post("/v1/cards:set-values",
                           json={"card_id": cid, "values": {"reps": 5}})
        assert resp.status_code == 400
        assert "force" in resp.json()["detail"]

    def test_force_writes_the_risky_column(self, seeded):
        cid = ids(seeded)[0]
        body = seeded.post("/v1/cards:set-values", json={
            "card_id": cid, "values": {"reps": 5}, "force": True}).json()
        assert body["affected"] == 1
        assert seeded.get("/v1/cards", params={"where": f"id=={cid}"}
                          ).json()["items"][0]["reps"] == 5

    def test_missing_card_is_404(self, seeded):
        resp = seeded.post("/v1/cards:set-values",
                           json={"card_id": 999999, "values": {"factor": 2600}})
        assert resp.status_code == 404

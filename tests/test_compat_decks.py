"""
Wire-shape golden tests for the AnkiConnect deck and deck-config actions,
quoted from canonical (git.sr.ht/~foosoft/anki-connect).
"""
import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)
from tsunagi.http.compat.errors import DECKS_NEED_CARDS_TOO


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add_note(client, front="犬", deck="Default"):
    return rpc(client, "addNote", {"note": {
        "deckName": deck, "modelName": "Basic",
        "fields": {"Front": front, "Back": "x"}}})["result"]


@pytest.fixture()
def seeded(client):
    rpc(client, "createDeck", {"deck": "JP"})
    add_note(client, "犬", "Default")
    add_note(client, "猫", "JP")
    return client


def cids(client, query=""):
    return rpc(client, "findCards", {"query": query})["result"]


class TestGetDecks:
    def test_groups_cards_by_deck_name(self, seeded):
        result = rpc(seeded, "getDecks", {"cards": cids(seeded)})["result"]
        assert sorted(result) == ["Default", "JP"]
        assert len(result["Default"]) == 1 and len(result["JP"]) == 1

    def test_unknown_card_uses_default_deck(self, seeded):
        # Canonical resolves a missing card through decks.get(None).
        result = rpc(seeded, "getDecks", {"cards": [999999]})["result"]
        assert result == {"Default": [999999]}


class TestChangeDeck:
    def test_moves_cards(self, seeded):
        target = cids(seeded, "deck:Default")
        assert rpc(seeded, "changeDeck", {"cards": target, "deck": "JP"}) == {
            "result": None, "error": None}
        assert cids(seeded, "deck:Default") == []

    def test_creates_the_target_deck(self, seeded):
        # Canonical uses decks.id(), which creates. The native
        # POST /v1/cards:change-deck refuses instead.
        rpc(seeded, "changeDeck", {"cards": cids(seeded)[:1], "deck": "Brand::New"})
        assert "Brand::New" in rpc(seeded, "deckNames")["result"]


class TestDeleteDecks:
    def test_refuses_without_cards_too(self, seeded):
        resp = rpc(seeded, "deleteDecks", {"decks": ["JP"]})
        assert resp == {"result": None, "error": DECKS_NEED_CARDS_TOO}
        assert "JP" in rpc(seeded, "deckNames")["result"]

    def test_deletes_with_cards_too(self, seeded):
        resp = rpc(seeded, "deleteDecks", {"decks": ["JP"], "cardsToo": True})
        assert resp == {"result": None, "error": None}
        assert "JP" not in rpc(seeded, "deckNames")["result"]

    def test_unknown_names_are_skipped(self, seeded):
        resp = rpc(seeded, "deleteDecks", {"decks": ["Nope"], "cardsToo": True})
        assert resp["error"] is None
        assert "Nope" not in rpc(seeded, "deckNames")["result"]


class TestDeckConfig:
    def test_get_returns_the_config_dict(self, seeded):
        conf = rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]
        assert conf["id"] == 1 and conf["name"] == "Default"
        assert conf["new"]["perDay"] == 20

    def test_get_unknown_deck_is_false(self, seeded):
        assert rpc(seeded, "getDeckConfig", {"deck": "Nope"})["result"] is False

    def test_save_round_trips(self, seeded):
        conf = rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]
        conf["new"]["perDay"] = 40
        assert rpc(seeded, "saveDeckConfig", {"config": conf})["result"] is True
        assert rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]["new"]["perDay"] == 40

    def test_save_unknown_id_is_false(self, seeded):
        assert rpc(seeded, "saveDeckConfig",
                   {"config": {"id": 999999, "name": "x"}})["result"] is False

    def test_clone_returns_new_id(self, seeded):
        new_id = rpc(seeded, "cloneDeckConfigId", {"name": "Cram"})["result"]
        assert isinstance(new_id, int) and new_id != 1

    def test_clone_from_unknown_is_false(self, seeded):
        assert rpc(seeded, "cloneDeckConfigId",
                   {"name": "Cram", "cloneFrom": 999999})["result"] is False

    def test_set_config_id(self, seeded):
        new_id = rpc(seeded, "cloneDeckConfigId", {"name": "Cram"})["result"]
        assert rpc(seeded, "setDeckConfigId",
                   {"decks": ["JP"], "configId": new_id})["result"] is True
        assert rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]["id"] == new_id

    def test_set_config_id_unknown_deck_is_false(self, seeded):
        assert rpc(seeded, "setDeckConfigId",
                   {"decks": ["Nope"], "configId": 1})["result"] is False

    def test_set_config_validates_all_names_before_saving(self, seeded):
        new_id = rpc(seeded, "cloneDeckConfigId", {"name": "Cram"})["result"]
        assert rpc(seeded, "setDeckConfigId", {
            "decks": ["JP", "Nope"], "configId": new_id,
        }) == {"result": False, "error": None}
        assert rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]["id"] == 1

    @pytest.mark.parametrize("failed_save", [1, 2])
    def test_set_config_keeps_saved_prefix_on_failure(self, seeded, col, monkeypatch, failed_save):
        from tsunagi.adapters.anki.compat import set_deck_config_legacy

        new_id = rpc(seeded, "cloneDeckConfigId", {"name": "Cram"})["result"]
        save = col.decks.save
        calls = []

        def fail_save(deck):
            calls.append(deck["name"])
            if len(calls) == failed_save:
                raise RuntimeError("save failed")
            save(deck)

        # Future Anki may remove this proxy entirely.
        monkeypatch.delattr(col.decks, "decks")
        monkeypatch.setattr(col.decks, "save", fail_save)
        out = set_deck_config_legacy.__wrapped__(col, ["JP", "Default"], str(new_id))
        if failed_save == 1:
            assert out is False
        else:
            assert out.value is False and out.changes.deck
        assert calls == ["JP", "Default"][:failed_save]
        assert col.decks.by_name("JP")["conf"] == (new_id if failed_save == 2 else 1)
        assert col.decks.by_name("Default")["conf"] == 1

    def test_remove_config_id(self, seeded):
        new_id = rpc(seeded, "cloneDeckConfigId", {"name": "Cram"})["result"]
        rpc(seeded, "setDeckConfigId", {"decks": ["JP"], "configId": new_id})
        assert rpc(seeded, "removeDeckConfigId", {"configId": new_id})["result"] is True
        # Anki reassigns the orphaned deck to the default config.
        assert rpc(seeded, "getDeckConfig", {"deck": "JP"})["result"]["id"] == 1

    def test_remove_unknown_config_is_false(self, seeded):
        assert rpc(seeded, "removeDeckConfigId", {"configId": 999999})["result"] is False


class TestDeckStats:
    def test_counts_per_deck(self, seeded):
        result = rpc(seeded, "getDeckStats", {"decks": ["JP"]})["result"]
        (stats,) = result.values()
        assert set(stats) == {"deck_id", "name", "new_count", "learn_count",
                              "review_count", "total_in_deck"}
        assert stats["name"] == "JP"
        assert stats["new_count"] == 1 and stats["total_in_deck"] == 1

    def test_unknown_deck_is_created_only_by_shim(self, seeded):
        from tsunagi.adapters.anki.decks import get_deck_stats

        assert get_deck_stats(["Nope"]) == {}
        assert "Nope" not in rpc(seeded, "deckNames")["result"]
        reply = rpc(seeded, "getDeckStats", {"decks": ["Nope"]})
        assert reply["error"] is None
        did = rpc(seeded, "deckNamesAndIds")["result"]["Nope"]
        assert reply["result"] == {str(did): {
            "deck_id": did, "name": "Nope", "new_count": 0,
            "learn_count": 0, "review_count": 0, "total_in_deck": 0,
        }}


class TestMediaDirPath:
    def test_returns_a_path(self, client):
        result = rpc(client, "getMediaDirPath")["result"]
        assert isinstance(result, str) and result

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

    def test_unknown_card_is_dropped(self, seeded):
        # Divergence: canonical files it under "Default", because
        # decks.get(None) falls back to the default deck.
        result = rpc(seeded, "getDecks", {"cards": [999999]})["result"]
        assert result == {}


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

    def test_unknown_deck_is_skipped_and_not_created(self, seeded):
        # Divergence: canonical resolves names with decks.id(), so a typo
        # silently creates a deck. A stats read must not mutate.
        assert rpc(seeded, "getDeckStats", {"decks": ["Nope"]})["result"] == {}
        assert "Nope" not in rpc(seeded, "deckNames")["result"]


class TestMediaDirPath:
    def test_returns_a_path(self, client):
        result = rpc(client, "getMediaDirPath")["result"]
        assert isinstance(result, str) and result

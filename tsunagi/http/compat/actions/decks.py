"""
AnkiConnect compatibility handlers for deck actions.

Shared adapters handle ordinary deck operations. Dedicated compatibility
operations preserve legacy lookup, configuration and due-tree behavior.
"""
from typing import Any, Dict, List

from pydantic import BaseModel

from ....adapters.anki.cards import change_deck
from ....adapters.anki.compat import raw_id_list
from ....adapters.anki.decks import (
    create_deck_if_missing,
    delete_deck,
    get_deck_names_and_ids,
    get_deck_stats,
    get_decks_by_ids,
    get_decks_by_names,
)
from ..errors import DECK_NOT_FOUND, DECKS_NEED_CARDS_TOO
from ..registry import registry


class CreateDeckParams(BaseModel):
    deck: str


class DeckIdParams(BaseModel):
    deckId: int


class CardsParams(BaseModel):
    cards: Any = ...


class ChangeDeckParams(BaseModel):
    cards: List[int]
    deck: str


class DeleteDecksParams(BaseModel):
    decks: List[str]
    cardsToo: bool = False


class DeckParams(BaseModel):
    deck: Any = ...


class DecksParams(BaseModel):
    decks: List[str]


class DeckStatsParams(BaseModel):
    decks: Any


class SaveDeckConfigParams(BaseModel):
    config: Any = ...


class SetDeckConfigIdParams(BaseModel):
    decks: Any = ...
    configId: Any = ...


class CloneDeckConfigIdParams(BaseModel):
    name: Any = ...
    cloneFrom: Any = "1"


class RemoveDeckConfigIdParams(BaseModel):
    configId: Any = ...


@registry.register("deckNames")
def ac_deckNames(params: Dict[str, Any]) -> List[str]:
    return [d["name"] for d in get_deck_names_and_ids()]


@registry.register("deckNamesAndIds")
def ac_deckNamesAndIds(params: Dict[str, Any]) -> Dict[str, int]:
    return {d["name"]: d["id"] for d in get_deck_names_and_ids()}


@registry.register("createDeck", params=CreateDeckParams)
def ac_createDeck(p: CreateDeckParams) -> int:
    # Existing name returns the existing id without error; "::" creates parents.
    return create_deck_if_missing(p.deck)


@registry.register("deckNameFromId", params=DeckIdParams)
def ac_deckNameFromId(p: DeckIdParams) -> str:
    # Narrow wants: without it the deck fetcher builds due counts, which
    # costs a full scheduler pass over every card - to read one name.
    decks = get_decks_by_ids([p.deckId], {"id", "name"})
    if not decks:
        raise ValueError(DECK_NOT_FOUND.format(p.deckId))
    return decks[0].name


@registry.register("getDecks", params=CardsParams)
def ac_getDecks(p: CardsParams) -> Dict[str, List[int]]:
    from ....adapters.anki.compat import decks_for_cards

    return decks_for_cards(raw_id_list(p.cards))


@registry.register("changeDeck", params=ChangeDeckParams)
def ac_changeDeck(p: ChangeDeckParams) -> None:
    # Canonical creates the target deck if it doesn't exist (decks.id), unlike
    # the native POST /v1/cards:change-deck, which refuses.
    deck_id = create_deck_if_missing(p.deck)
    change_deck(p.cards, deck_id=deck_id)


@registry.register("deleteDecks", params=DeleteDecksParams)
def ac_deleteDecks(p: DeleteDecksParams) -> None:
    if not p.cardsToo:
        # Anki has not been able to delete a deck while keeping its cards
        # since 2.1.28, and passing cardsToo=False to the deprecated API is
        # silently ignored - so canonical refuses rather than destroying data.
        raise ValueError(DECKS_NEED_CARDS_TOO)
    for deck in get_decks_by_names(p.decks):
        delete_deck(deck.id)


@registry.register("getDeckConfig", params=DeckParams)
def ac_getDeckConfig(p: DeckParams):
    from ....adapters.anki.compat import get_deck_config_legacy

    return get_deck_config_legacy(p.deck)


@registry.register("saveDeckConfig", params=SaveDeckConfigParams)
def ac_saveDeckConfig(p: SaveDeckConfigParams) -> bool:
    from ....adapters.anki.compat import save_deck_config_legacy

    return save_deck_config_legacy(p.config)


@registry.register("setDeckConfigId", params=SetDeckConfigIdParams)
def ac_setDeckConfigId(p: SetDeckConfigIdParams) -> bool:
    from ....adapters.anki.compat import set_deck_config_legacy

    return set_deck_config_legacy(p.decks, p.configId)


@registry.register("cloneDeckConfigId", params=CloneDeckConfigIdParams)
def ac_cloneDeckConfigId(p: CloneDeckConfigIdParams):
    from ....adapters.anki.compat import clone_deck_config_legacy

    return clone_deck_config_legacy(p.name, p.cloneFrom)


@registry.register("removeDeckConfigId", params=RemoveDeckConfigIdParams)
def ac_removeDeckConfigId(p: RemoveDeckConfigIdParams) -> bool:
    from ....adapters.anki.compat import remove_deck_config_legacy

    result, error = remove_deck_config_legacy(p.configId)
    if error is not None:
        raise ValueError(error)
    return result


@registry.register("getDeckStats", params=DeckStatsParams)
def ac_getDeckStats(p: DeckStatsParams) -> Dict[int, Dict[str, Any]]:
    from ....adapters.anki.compat import deck_tree_names, resolve_deck_names

    decks = resolve_deck_names(p.decks)
    names = deck_tree_names()
    return {did: dict(stats, name=names[did])
            for did, stats in get_deck_stats(decks).items() if did in names}

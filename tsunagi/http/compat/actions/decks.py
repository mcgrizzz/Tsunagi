"""
AnkiConnect compatibility handlers for deck actions.

Thin translations over the adapters /v1/decks and /v1/deck-configs use.
Two deliberate divergences, both because a read must not mutate:
getDeckStats and getDecks resolve deck names to existing decks only, where
canonical uses decks.id() and silently CREATES a deck for a typo.
"""
from typing import Any, Dict, List

from pydantic import BaseModel

from ....adapters.anki.cards import change_deck, get_cards_by_ids
from ....adapters.anki.deck_configs import (
    create_deck_config,
    delete_deck_config,
    get_deck_config_for_deck,
    get_deck_configs_by_ids,
    replace_deck_config,
)
from ....adapters.anki.decks import (
    create_deck_if_missing,
    delete_deck,
    get_deck_names_and_ids,
    get_deck_stats,
    get_decks_by_ids,
    get_decks_by_names,
    patch_deck,
)
from ..errors import DECK_NOT_FOUND, DECKS_NEED_CARDS_TOO
from ..registry import registry


class CreateDeckParams(BaseModel):
    deck: str


class DeckIdParams(BaseModel):
    deckId: int


class CardsParams(BaseModel):
    cards: List[int]


class ChangeDeckParams(BaseModel):
    cards: List[int]
    deck: str


class DeleteDecksParams(BaseModel):
    decks: List[str]
    cardsToo: bool = False


class DeckParams(BaseModel):
    deck: str


class DecksParams(BaseModel):
    decks: List[str]


class SaveDeckConfigParams(BaseModel):
    config: Dict[str, Any]


class SetDeckConfigIdParams(BaseModel):
    decks: List[str]
    configId: int


class CloneDeckConfigIdParams(BaseModel):
    name: str
    cloneFrom: int = 1


class RemoveDeckConfigIdParams(BaseModel):
    configId: int


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
    decks = get_decks_by_ids([p.deckId])
    if not decks:
        raise ValueError(DECK_NOT_FOUND.format(p.deckId))
    return decks[0].name


@registry.register("getDecks", params=CardsParams)
def ac_getDecks(p: CardsParams) -> Dict[str, List[int]]:
    """
    {deckName: [cardIds]}. Unknown card ids are dropped; canonical files them
    under "Default", because decks.get(None) falls back to the default deck.
    """
    out: Dict[str, List[int]] = {}
    for card in get_cards_by_ids(p.cards, {"id", "deck_name"}):
        out.setdefault(card.deck_name, []).append(card.id)
    return out


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
    decks = get_decks_by_names([p.deck])
    if not decks:
        return False
    return get_deck_config_for_deck(decks[0].id)


@registry.register("saveDeckConfig", params=SaveDeckConfigParams)
def ac_saveDeckConfig(p: SaveDeckConfigParams) -> bool:
    return replace_deck_config(p.config)


@registry.register("setDeckConfigId", params=SetDeckConfigIdParams)
def ac_setDeckConfigId(p: SetDeckConfigIdParams) -> bool:
    decks = get_decks_by_names(p.decks)
    if len(decks) != len(p.decks):
        return False  # all-or-nothing: an unknown deck name fails the batch
    for deck in decks:
        patch_deck(deck.id, {"conf": p.configId})
    return True


@registry.register("cloneDeckConfigId", params=CloneDeckConfigIdParams)
def ac_cloneDeckConfigId(p: CloneDeckConfigIdParams):
    if not get_deck_configs_by_ids([p.cloneFrom]):
        return False
    return create_deck_config({"name": p.name, "clone_from_id": p.cloneFrom})["id"]


@registry.register("removeDeckConfigId", params=RemoveDeckConfigIdParams)
def ac_removeDeckConfigId(p: RemoveDeckConfigIdParams) -> bool:
    if not get_deck_configs_by_ids([p.configId]):
        return False
    delete_deck_config(p.configId)
    return True


@registry.register("getDeckStats", params=DecksParams)
def ac_getDeckStats(p: DecksParams) -> Dict[int, Dict[str, Any]]:
    return get_deck_stats(p.decks)

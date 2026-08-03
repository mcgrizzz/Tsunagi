"""
AnkiConnect compatibility handlers for deck actions.
"""
from typing import Any, Dict, List

from pydantic import BaseModel

from ....adapters.anki.decks import create_deck_if_missing, get_deck_names_and_ids
from ..registry import registry


class CreateDeckParams(BaseModel):
    deck: str


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

from typing import Any, Dict, List, Mapping, Sequence

from anki.collection import Collection

from ...shared.errors import ResourceNotFoundError, ValidationError
from ...shared.helpers import (
    copy_if_present,
    normalize_field_names,
    validate_required_keys,
)
from ...shared.schemas.decks import DeckCreate, DeckInfo, DeckPatch
from ..ops import as_collection_op, as_query_op

# NOTE: DeckManager.get() defaults to default=True, which silently returns the
# DEFAULT deck for missing ids. Every lookup here must pass default=False.


@as_query_op
def list_decks(col: Collection) -> List[DeckInfo]:
    return [DeckInfo.parse_obj(d) for d in col.decks.all()]

@as_query_op
def get_decks_by_ids(col: Collection, ids: Sequence[int], wants=None) -> List[DeckInfo]:
    # `wants` accepted for the fetcher contract; decks have no expensive fields.
    out: List[DeckInfo] = []
    for did in ids:
        d = col.decks.get(did, default=False)
        if d:
            out.append(DeckInfo.parse_obj(d))
    return out

@as_query_op
def get_decks_by_names(col: Collection, names: Sequence[str], wants=None) -> List[DeckInfo]:
    out: List[DeckInfo] = []
    for name in names:
        d = col.decks.by_name(name)
        if d:
            out.append(DeckInfo.parse_obj(d))
    return out

@as_query_op
def get_deck_names_and_ids(col: Collection) -> List[Mapping[str, Any]]:
    res: List[Mapping[str, Any]] = []
    for nt in col.decks.all_names_and_ids(skip_empty_default=False, include_filtered=True):
        res.append({"id": int(nt.id), "name": nt.name})
    return res


@as_collection_op
def create_deck(col: Collection, data: Dict[str, Any]) -> DeckInfo:
    """
    POST /v1/decks - create a deck ("A::B" creates parents).
    """
    data = normalize_field_names(data, DeckCreate)
    validate_required_keys(data, ["name"])
    name = data["name"]

    if col.decks.by_name(name) is not None:
        raise ValueError(f"Deck name '{name}' already exists")

    out = col.decks.add_normal_deck_with_name(name)
    deck = col.decks.get(int(out.id), default=False)
    if "desc" in data and data["desc"] is not None:
        deck["desc"] = data["desc"]
        col.decks.save(deck)
    return DeckInfo.parse_obj(deck)


@as_collection_op
def create_deck_if_missing(col: Collection, name: str) -> int:
    """
    Compat createDeck semantics: existing name returns the existing id
    (no error), otherwise create (with "::" parents) and return the new id.
    """
    existing = col.decks.by_name(name)
    if existing is not None:
        return int(existing["id"])
    return int(col.decks.add_normal_deck_with_name(name).id)


@as_collection_op
def patch_deck(col: Collection, deck_id: int, updates: Dict[str, Any]) -> DeckInfo:
    """
    PATCH /v1/decks/{id} - rename (children follow) and/or update properties.
    """
    deck = col.decks.get(deck_id, default=False)
    if not deck:
        raise ResourceNotFoundError("Deck", deck_id)

    updates = normalize_field_names(updates, DeckPatch)

    if "name" in updates:
        col.decks.rename(deck, updates["name"])

    copy_if_present(updates, deck, ["desc", "collapsed", "browserCollapsed", "conf"])
    col.decks.save(deck)

    return DeckInfo.parse_obj(col.decks.get(deck_id, default=False))


@as_collection_op
def delete_deck(col: Collection, deck_id: int) -> bool:
    """
    DELETE /v1/decks/{id} - delete a deck (and its subdecks, per Anki).
    """
    deck = col.decks.get(deck_id, default=False)
    if not deck:
        raise ResourceNotFoundError("Deck", deck_id)
    if deck_id == 1:
        raise ValidationError("Cannot delete the default deck")
    col.decks.remove([deck_id])
    return True

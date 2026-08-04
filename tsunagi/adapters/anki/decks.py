from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from anki.collection import Collection

from ...shared.errors import (
    ResourceNotFoundError,
    UnsupportedAnkiVersionError,
    ValidationError,
)
from ...shared.helpers import (
    copy_if_present,
    normalize_field_names,
    validate_required_keys,
)
from ...shared.schemas.decks import DeckCreate, DeckInfo, DeckPatch
from ..ops import ValueWithChanges, as_collection_op, as_query_op

# NOTE: DeckManager.get() defaults to default=True, which silently returns the
# DEFAULT deck for missing ids. Every lookup here must pass default=False.

# Due counts aren't stored on the deck; they come from the scheduler's tree.
STAT_FIELDS = frozenset({"new_count", "learn_count", "review_count", "total_in_deck"})
ZERO_COUNTS = {k: 0 for k in sorted(STAT_FIELDS)}


def _deck_stats(col: Collection) -> Dict[int, Dict[str, int]]:
    """
    Flatten the scheduler's due tree into {deck_id: counts}.

    One backend call for the whole page - deck_due_tree() already walks the
    entire collection, so asking it per deck would be the exact "redundant
    internal work" this API exists to avoid.
    """
    out: Dict[int, Dict[str, int]] = {}

    def walk(node: Any) -> None:
        out[int(node.deck_id)] = {
            "new_count": int(node.new_count),
            "learn_count": int(node.learn_count),
            "review_count": int(node.review_count),
            "total_in_deck": int(node.total_in_deck),
        }
        for child in node.children:
            walk(child)

    walk(col.sched.deck_due_tree())
    return out


def _retention_supported() -> bool:
    # Per-deck desired retention postdates 23.10; the proto descriptor is the
    # cheap, import-safe check.
    try:
        from anki import decks_pb2
        return "desired_retention" in decks_pb2.Deck.Normal.DESCRIPTOR.fields_by_name
    except Exception:
        return False


def _read_desired_retention(col: Collection, deck_id: int) -> Optional[float]:
    """
    From the deck protobuf, not the schema11 dict: the dict carries the value
    as int(fraction*100), so 0.85 reads back as 85 and 0.837 as 83.
    """
    if not _retention_supported():
        return None
    try:
        deck = col._backend.get_deck(int(deck_id))
        if deck.WhichOneof("kind") == "normal" and deck.normal.HasField("desired_retention"):
            return float(deck.normal.desired_retention)
    except Exception:
        pass  # missing deck, filtered deck, or a proto surprise -> null
    return None


def _write_desired_retention(col: Collection, deck_id: int, value: Optional[Any]) -> Any:
    if not _retention_supported():
        raise UnsupportedAnkiVersionError("per-deck desired retention")
    deck = col._backend.get_deck(int(deck_id))
    if deck.WhichOneof("kind") != "normal":
        raise ValidationError("desired_retention applies to normal decks, not filtered ones")
    if value is None:
        deck.normal.ClearField("desired_retention")
    else:
        deck.normal.desired_retention = float(value)
    return col._backend.update_deck(deck)


def _deck_info(col: Collection, d: Mapping[str, Any],
               stats: Optional[Dict[int, Dict[str, int]]],
               wants: Optional[Set[str]] = None) -> DeckInfo:
    info = DeckInfo.parse_obj(d)
    if stats is not None:
        # A deck missing from the tree has nothing due, not unknown counts.
        # Anki drops the Default deck from deck_due_tree() while it's empty
        # and other decks exist, so without this it reported nulls where
        # zeros are the truth.
        counts = stats.get(int(info.id)) or ZERO_COUNTS
        for k, v in counts.items():
            setattr(info, k, v)
    if wants is None or "desired_retention" in wants:
        info.desired_retention = _read_desired_retention(col, int(info.id))
    return info


def _stats_if_wanted(col: Collection, wants: Optional[Set[str]]) -> Optional[Dict[int, Dict[str, int]]]:
    if wants is None or (STAT_FIELDS & wants):
        return _deck_stats(col)
    return None


@as_query_op
def list_decks(col: Collection, wants=None) -> List[DeckInfo]:
    stats = _stats_if_wanted(col, wants)
    return [_deck_info(col, d, stats, wants) for d in col.decks.all()]

@as_query_op
def get_decks_by_ids(col: Collection, ids: Sequence[int], wants=None) -> List[DeckInfo]:
    stats = _stats_if_wanted(col, wants)
    out: List[DeckInfo] = []
    for did in ids:
        d = col.decks.get(did, default=False)
        if d:
            out.append(_deck_info(col, d, stats, wants))
    return out

@as_query_op
def get_decks_by_names(col: Collection, names: Sequence[str], wants=None) -> List[DeckInfo]:
    stats = _stats_if_wanted(col, wants)
    out: List[DeckInfo] = []
    for name in names:
        d = col.decks.by_name(name)
        if d:
            out.append(_deck_info(col, d, stats, wants))
    return out

@as_query_op
def get_deck_stats(col: Collection, names: Sequence[str]) -> Dict[int, Dict[str, Any]]:
    """
    Due counts for named decks - AnkiConnect's getDeckStats.

    Unknown names are skipped. Canonical resolves them with decks.id(), which
    CREATES the deck; a stats read must not mutate the collection.
    """
    stats = _deck_stats(col)
    out: Dict[int, Dict[str, Any]] = {}
    for name in names:
        deck = col.decks.by_name(name)
        if deck is None:
            continue
        did = int(deck["id"])
        out[did] = {"deck_id": did, "name": deck["name"],
                    **(stats.get(did) or ZERO_COUNTS)}
    return out


@as_query_op
def get_deck_names_and_ids(col: Collection, wants=None) -> List[Mapping[str, Any]]:
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
    changes = out
    deck = col.decks.get(int(out.id), default=False)
    if "desc" in data and data["desc"] is not None:
        deck["desc"] = data["desc"]
        # update_dict, not the legacy save(): same write, but it returns the
        # OpChanges the op needs to report.
        changes = col.decks.update_dict(deck)
    return ValueWithChanges(DeckInfo.parse_obj(deck), changes)


@as_collection_op
def create_deck_if_missing(col: Collection, name: str) -> int:
    """
    Compat createDeck semantics: existing name returns the existing id
    (no error), otherwise create (with "::" parents) and return the new id.
    """
    existing = col.decks.by_name(name)
    if existing is not None:
        return int(existing["id"])
    out = col.decks.add_normal_deck_with_name(name)
    return ValueWithChanges(int(out.id), out)


@as_collection_op
def patch_deck(col: Collection, deck_id: int, updates: Dict[str, Any]) -> DeckInfo:
    """
    PATCH /v1/decks/{id} - rename (children follow) and/or update properties.
    """
    deck = col.decks.get(deck_id, default=False)
    if not deck:
        raise ResourceNotFoundError("Deck", deck_id)

    # Read the retention intent off the raw body: normalize_field_names drops
    # explicit nulls (exclude_none), but here null means "clear the override".
    retention_sent = any(k in updates for k in ("desiredRetention", "desired_retention"))
    retention_value = updates.get("desiredRetention", updates.get("desired_retention"))

    updates = normalize_field_names(updates, DeckPatch)

    changes = None
    if "name" in updates:
        changes = col.decks.rename(deck, updates["name"])
        # rename() renames in the backend and does NOT touch the dict we hold,
        # which still carries the old name - saving it below would write the
        # rename straight back out again. Re-read before touching anything else.
        deck = col.decks.get(deck_id, default=False)

    copy_if_present(updates, deck, ["desc", "collapsed", "browserCollapsed", "conf"])
    # update_dict, not the legacy save(): same write, but it returns OpChanges.
    changes = col.decks.update_dict(deck)

    # After save() on purpose: saving the schema11 dict rewrites the proto's
    # desired_retention from the dict's truncated integer percent, so writing
    # first would immediately mangle the value (0.837 -> 0.83).
    if retention_sent:
        changes = _write_desired_retention(col, deck_id, retention_value)

    info = _deck_info(col, col.decks.get(deck_id, default=False), None)
    return ValueWithChanges(info, changes) if changes is not None else info


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
    changes = col.decks.remove([deck_id])
    return ValueWithChanges(True, changes)

"""
Deck configs ("options groups").

Rows are Anki's config dicts passed through untyped, on purpose. The scheduler
config gains keys every Anki release (the FSRS parameters are the obvious
recent example), and a typed schema would silently drop whatever it didn't
model - which would also break saveDeckConfig's read-modify-write round trip.
The query DSL filters plain Mappings, so select/where still work over the
nested new/rev/lapse objects.
"""
import copy
from typing import Any, Dict, List, Optional, Sequence

from anki.collection import Collection

from ...shared.errors import ResourceNotFoundError, ValidationError
from ..ops import as_collection_op, as_query_op

# Anki's built-in options group. Every deck falls back to it, so it can't go.
DEFAULT_CONFIG_ID = 1


def _config(col: Collection, config_id: int) -> Optional[Dict[str, Any]]:
    """
    A config by id, or None if there is no such config.

    DeckManager.get_config() cannot be trusted to report absence: it catches
    NotFoundError and returns None, but the backend's get_deck_config_legacy()
    doesn't raise - it falls back to the DEFAULT config. So an unknown id came
    back as config 1, and every existence check here silently passed. PATCH on
    a bogus id merged into the default preset; DELETE got past the guard and
    blew up inside remove_config. Same trap as DeckManager.get(default=True),
    which decks.py already documents.
    """
    conf = col.decks.get_config(int(config_id))
    if conf is None or int(conf.get("id", 0)) != int(config_id):
        return None
    return conf


def _merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive merge, so PATCH {"new": {"perDay": 40}} keeps the other new/* keys."""
    out = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@as_query_op
def list_deck_configs(col: Collection, wants=None) -> List[Dict[str, Any]]:
    return list(col.decks.all_config())


@as_query_op
def get_deck_configs_by_ids(col: Collection, ids: Sequence[int],
                            wants=None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cid in ids:
        conf = _config(col, int(cid))
        if conf:
            out.append(conf)
    return out


@as_query_op
def get_deck_config_for_deck(col: Collection, deck_id: int) -> Dict[str, Any]:
    """The config a deck actually uses, following its fallback to the default."""
    if col.decks.get(int(deck_id), default=False) is None:
        raise ResourceNotFoundError("deck", int(deck_id))
    return col.decks.config_dict_for_deck_id(int(deck_id))


@as_collection_op
def create_deck_config(col: Collection, data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("'name' is required")

    clone_from = data.get("clone_from_id", data.get("cloneFromId"))
    source: Optional[Dict[str, Any]] = None
    if clone_from is not None:
        source = _config(col, int(clone_from))
        if source is None:
            raise ResourceNotFoundError("deck config", int(clone_from))

    new_id = col.decks.add_config_returning_id(name, source)
    return col.decks.get_config(int(new_id))


@as_collection_op
def patch_deck_config(col: Collection, config_id: int,
                      updates: Dict[str, Any]) -> Dict[str, Any]:
    conf = _config(col, int(config_id))
    if conf is None:
        raise ResourceNotFoundError("deck config", int(config_id))
    merged = _merge(conf, updates)
    # The id is the resource's identity, not a settable property.
    merged["id"] = int(config_id)
    col.decks.update_config(merged)
    return col.decks.get_config(int(config_id))


@as_collection_op
def replace_deck_config(col: Collection, conf: Dict[str, Any]) -> bool:
    """
    Whole-document write, for AnkiConnect's saveDeckConfig. Unknown id is
    reported rather than silently creating a config.
    """
    try:
        config_id = int(conf["id"])
    except (KeyError, TypeError, ValueError):
        return False
    if _config(col, config_id) is None:
        return False
    payload = dict(conf)
    payload["id"] = config_id
    col.decks.update_config(payload)
    return True


@as_collection_op
def delete_deck_config(col: Collection, config_id: int) -> bool:
    if int(config_id) == DEFAULT_CONFIG_ID:
        raise ValidationError("Cannot delete the default deck config")
    if _config(col, int(config_id)) is None:
        raise ResourceNotFoundError("deck config", int(config_id))
    # Anki reassigns every deck using it back to the default.
    col.decks.remove_config(int(config_id))
    return True

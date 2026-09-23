"""
Card reads and scheduling mutations.

Cards are never created or deleted here: they are generated from notes by a
notetype's templates, so the resource exposes reads plus the scheduler's verbs
and nothing else. Every mutation is a single CollectionOp, which means one
undo entry per call and - unlike raw SQL - writes that work while the browser
has the card selected.
"""
from typing import Any, Dict, List, Optional, Sequence, Set

from anki.collection import Collection

from ...shared.errors import (
    ResourceNotFoundError,
    UnsupportedAnkiVersionError,
    ValidationError,
)
from ...shared.schemas.cards import (
    CardIds,
    CardInfo,
    ChangeDeckRequest,
    ForgetRequest,
    RepositionRequest,
    SetDueDateRequest,
    SetEaseRequest,
    SetFlagRequest,
)
from ..ops import ValueWithChanges, as_collection_op, as_query_op

QUEUE_SUSPENDED = -1
BURIED_QUEUES = (-2, -3)  # sibling-buried, manually buried

# Fields that need the card's note loaded. Rendering question/answer goes
# through the backend template renderer, which is a separate call again.
NOTE_WANTS = frozenset({"model_name", "css", "fields"})
RENDER_WANTS = frozenset({"question", "answer"})

# Only stable columns and expressions with the same meaning as _card_info.
# Newer FSRS properties live in Anki's card data and use the normal reader.
CARD_COLUMN_SQL = {
    "id": "id", "note_id": "nid", "deck_id": "did",
    "original_deck_id": "odid", "ord": "ord", "mod": "mod", "usn": "usn",
    "type": "type", "queue": "queue", "due": "due", "original_due": "odue",
    "interval": "ivl", "factor": "factor", "reps": "reps", "lapses": "lapses",
    "left": '"left"', "flags": "flags", "flag": "flags & 7",
    "suspended": "queue = -1", "buried": "queue in (-2, -3)",
}


def _deck_names(col: Collection) -> Dict[int, str]:
    # One call for the whole page; col.decks.get() per card would be a backend
    # round trip each.
    return {int(d.id): d.name for d in col.decks.all_names_and_ids(
        skip_empty_default=False, include_filtered=True)}


def _next_reviews(col: Collection, card_id: int) -> Optional[List[str]]:
    # Anki's interval formatter is private. If a future Anki moves it,
    # the field goes missing rather than the whole request failing.
    try:
        states = col._backend.get_scheduling_states(card_id)
        return [str(s) for s in col._backend.describe_next_states(states)]
    except Exception:
        return None


def _retrievability(col: Collection, card_id: int) -> Optional[float]:
    # card_stats_data exists on 23.10 through current, but the field is only
    # populated once FSRS has scored the card - use the protobuf presence bit,
    # since 0.0 is a legitimate value for a long-lapsed card.
    try:
        data = col.card_stats_data(card_id)
        if data.HasField("fsrs_retrievability"):
            return float(data.fsrs_retrievability)
        return None
    except Exception:
        return None


def _memory_state(card: Any) -> Optional[Dict[str, float]]:
    """
    FSRS memory state as plain numbers. Anki hands back a protobuf message,
    and `decay`/`last_review_time` landed after `memory_state`, so every FSRS
    attribute is read defensively: on an older build the field reports null
    rather than raising.
    """
    state = getattr(card, "memory_state", None)
    if state is None:
        return None
    return {"stability": float(state.stability), "difficulty": float(state.difficulty)}


def _card_info(col: Collection, card: Any, deck_names: Dict[int, str],
               wants: Optional[Set[str]] = None) -> CardInfo:
    return CardInfo(**_card_row(col, card, deck_names, wants))


def _optional(convert: Any, value: Any) -> Any:
    return None if value is None else convert(value)


def _card_row(col: Collection, card: Any, deck_names: Dict[int, str],
              wants: Optional[Set[str]] = None) -> Dict[str, Any]:
    """
    A card as CardInfo's field names and types, without per-row validation:
    the values come from Anki's own card, note and notetype. The conversions
    below are the ones CardInfo applied. tests/test_card_rows.py checks the
    rows against the schema on each CI runtime.
    """
    want_note = wants is None or bool(NOTE_WANTS & wants)
    want_render = wants is None or bool(RENDER_WANTS & wants)

    model_name = css = fields = None
    if want_note:
        note = card.note()
        notetype = note.note_type()
        model_name = notetype.get("name", "")
        css = notetype.get("css", "")
        fields = [{"name": n, "value": v, "ord": i}
                  for i, (n, v) in enumerate(zip(note.keys(), note.fields))]

    question = card.question() if want_render else None
    answer = card.answer() if want_render else None

    next_reviews = None
    if wants is None or "next_reviews" in wants:
        next_reviews = _next_reviews(col, int(card.id))

    retrievability = None
    if wants is None or "retrievability" in wants:
        retrievability = _retrievability(col, int(card.id))

    flags = int(getattr(card, "flags", 0) or 0)
    return {
        "id": int(card.id),
        "note_id": int(card.nid),
        "deck_id": int(card.did),
        "original_deck_id": int(getattr(card, "odid", 0) or 0),
        "ord": int(card.ord),
        "mod": int(getattr(card, "mod", 0) or 0),
        "usn": int(getattr(card, "usn", 0) or 0),
        "type": int(card.type),
        "queue": int(card.queue),
        "due": int(card.due),
        "original_due": int(getattr(card, "odue", 0) or 0),
        "interval": int(card.ivl),
        "factor": int(card.factor),
        "reps": int(card.reps),
        "lapses": int(card.lapses),
        "left": int(card.left),
        "flags": flags,
        "original_position": _optional(int, getattr(card, "original_position", None)),
        "custom_data": str(getattr(card, "custom_data", "") or ""),
        "memory_state": _memory_state(card),
        "desired_retention": _optional(float, getattr(card, "desired_retention", None)),
        "decay": _optional(float, getattr(card, "decay", None)),
        "last_review_time": _optional(int, getattr(card, "last_review_time", None)),
        "suspended": int(card.queue) == QUEUE_SUSPENDED,
        "buried": int(card.queue) in BURIED_QUEUES,
        "flag": flags & 0b111,
        "deck_name": deck_names.get(int(card.did), ""),
        "model_name": model_name,
        "css": css,
        "fields": fields,
        "question": question,
        "answer": answer,
        "next_reviews": next_reviews,
        "retrievability": retrievability,
    }


# ====================
# Reads
# ====================

@as_query_op
def page_card_ids(col: Collection, after_id: Optional[int], limit: int) -> List[int]:
    """
    The next `limit` card ids after `after_id` (None = from the start),
    ascending. `cards.id` is the primary key (and has never changed across
    Anki's schema migrations), so this is a pure index walk - the keyset page
    for a bare GET /v1/cards, which otherwise materializes every card id in
    the collection per page request.
    """
    if after_id is None:
        return [int(i) for i in col.db.list(
            "select id from cards order by id limit ?", int(limit))]
    return [int(i) for i in col.db.list(
        "select id from cards where id > ? order by id limit ?",
        int(after_id), int(limit))]


@as_query_op
def find_card_ids(col: Collection, query: str) -> List[int]:
    """
    Anki search -> card ids. An empty query means the whole collection
    (Anki's parser maps it to WholeCollection).
    """
    try:
        return [int(i) for i in col.find_cards(query)]
    except Exception as e:
        # A malformed search is a client error; without this every typo'd
        # search string becomes a 500.
        if type(e).__name__ in ("SearchError", "InvalidInput"):
            raise ValueError(f"Invalid Anki search: {e}") from e
        raise


@as_query_op
def get_cards_by_ids(col: Collection, ids: Sequence[int],
                     wants: Optional[Set[str]] = None) -> List[CardInfo]:
    return _get_cards_by_ids(col, ids, wants)


def _get_cards_by_ids(col: Collection, ids: Sequence[int],
                      wants: Optional[Set[str]] = None, build: Any = _card_info) -> List[Any]:
    deck_names = _deck_names(col)
    out: List[Any] = []
    for cid in ids:
        try:
            card = col.get_card(int(cid))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue  # missing ids are skipped, like get_notes_by_ids
            raise
        out.append(build(col, card, deck_names, wants))
    return out


@as_query_op
def get_card_rows_by_ids(col: Collection, ids: Sequence[int],
                         wants: Optional[Set[str]] = None) -> List[Any]:
    """Native scalar projections without per-card backend/model round trips.

    Keep filtering in the shared DSL, and keep this read inside QueryOp.
    Full rows and fields requiring Anki's objects retain the normal reader.
    The compatibility adapter continues to return CardInfo objects.
    """
    if wants is None or not wants <= CARD_COLUMN_SQL.keys():
        return _get_cards_by_ids(col, ids, wants, _card_row)
    ordered_ids = [int(cid) for cid in ids]
    fields = ["id", *sorted(wants - {"id"})]
    columns = ", ".join(CARD_COLUMN_SQL[field] for field in fields)
    by_id: Dict[int, Dict[str, Any]] = {}
    for offset in range(0, len(ordered_ids), 250):
        chunk = ordered_ids[offset:offset + 250]
        placeholders = ",".join("?" for _ in chunk)
        for values in col.db.all(
            f"select {columns} from cards where id in ({placeholders})", *chunk,
        ):
            row = dict(zip(fields, values))
            for field in ("suspended", "buried"):
                if field in row:
                    row[field] = bool(row[field])
            by_id[row["id"]] = row
    # SQL IN does not preserve caller order or duplicate IDs. Missing IDs
    # are skipped, exactly as in the object reader.
    return [by_id[cid] for cid in ordered_ids if cid in by_id]


@as_query_op
def get_cards_of_notes(col: Collection, note_ids: Sequence[int],
                       wants: Optional[Set[str]] = None) -> List[CardInfo]:
    deck_names = _deck_names(col)
    out: List[CardInfo] = []
    for nid in note_ids:
        for cid in col.card_ids_of_note(int(nid)):
            out.append(_card_info(col, col.get_card(int(cid)), deck_names, wants))
    return out


@as_query_op
def notes_of_cards(col: Collection, card_ids: Sequence[int]) -> List[int]:
    """
    Note ids for these cards, deduped - AnkiConnect's cardsToNotes. Walks the
    ids in ascending order so the result matches the row order canonical's
    'select distinct nid from cards where id in (...)' produces.
    """
    seen: List[int] = []
    for cid in sorted({int(c) for c in card_ids}):
        try:
            nid = int(col.get_card(cid).nid)
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue
            raise
        if nid not in seen:
            seen.append(nid)
    return seen


@as_query_op
def cards_mod_times(col: Collection, card_ids: Sequence[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cid in card_ids:
        try:
            card = col.get_card(int(cid))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append({})  # keep input/output positions aligned
                continue
            raise
        out.append({"cardId": int(card.id), "mod": int(card.mod)})
    return out


@as_query_op
def card_ease_factors(col: Collection, card_ids: Sequence[int]) -> List[Optional[int]]:
    out: List[Optional[int]] = []
    for cid in card_ids:
        try:
            out.append(int(col.get_card(int(cid)).factor))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(None)
                continue
            raise
    return out


@as_query_op
def cards_suspended(col: Collection, card_ids: Sequence[int]) -> List[Optional[bool]]:
    out: List[Optional[bool]] = []
    for cid in card_ids:
        try:
            out.append(int(col.get_card(int(cid)).queue) == QUEUE_SUSPENDED)
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(None)
                continue
            raise
    return out


# ====================
# Scheduling mutations
# ====================

def _count(changes: Any) -> int:
    """
    Cards the op reports changing. Anki returns OpChangesWithCount for some
    scheduler ops and a bare OpChanges for others; callers of the latter must
    supply their own count via _matching. Falling back to "however many ids
    you sent" would claim work that never happened.
    """
    return int(getattr(changes, "count", 0))


def _matching(col: Collection, card_ids: Sequence[int], query: str = "") -> int:
    """
    How many of `card_ids` match `query` (empty query = merely exist).

    One search scoped to the ids: `cid:a,b,c` compiles to an indexed
    `c.id in (...)` in Anki's search engine. The old form ran the query over
    the WHOLE collection and intersected client-side - asking about 5 cards
    cost a 150k-card scan.
    """
    ids = sorted({int(c) for c in card_ids})
    if not ids:
        return 0
    scoped = "cid:" + ",".join(str(c) for c in ids)
    if query:
        scoped += " " + query
    return len(col.find_cards(scoped))


def _ids_details(card_ids: Sequence[int], *_a: Any, **_k: Any) -> Dict[str, Any]:
    """event_details for the verbs whose first argument is the card ids."""
    return {"card_ids": [int(c) for c in card_ids]}


def _entry_ids_details(entries: Sequence[Dict[str, Any]], *_a: Any, **_k: Any) -> Dict[str, Any]:
    return {"card_ids": [int(e["id"]) for e in entries]}


# Each verb is a raw `(col, ...) -> (affected, changes)` plus a decorated
# wrapper: the wrapper is the single-verb op, the raw is what batch_cards
# runs under its one merged undo entry. One implementation, two entry points.

def _suspend(col: Collection, card_ids: Sequence[int]) -> Any:
    changes = col.sched.suspend_cards(list(card_ids))
    return _count(changes), changes


@as_collection_op(event_details=_ids_details)
def suspend_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return ValueWithChanges(*_suspend(col, card_ids),
                            event_changes=lambda: {"cards": {"updated": list(card_ids)}})


def _unsuspend(col: Collection, card_ids: Sequence[int]) -> Any:
    # Anki's unsuspend returns a bare OpChanges, so count the cards that were
    # actually suspended before we touched them.
    affected = _matching(col, card_ids, "is:suspended")
    return affected, col.sched.unsuspend_cards(list(card_ids))


@as_collection_op(event_details=_ids_details)
def unsuspend_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return ValueWithChanges(*_unsuspend(col, card_ids),
                            event_changes=lambda: {"cards": {"updated": list(card_ids)}})


def _bury(col: Collection, card_ids: Sequence[int]) -> Any:
    changes = col.sched.bury_cards(list(card_ids), manual=True)
    return _count(changes), changes


@as_collection_op(event_details=_ids_details)
def bury_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return ValueWithChanges(*_bury(col, card_ids),
                            event_changes=lambda: {"cards": {"updated": list(card_ids)}})


def _unbury(col: Collection, card_ids: Sequence[int]) -> Any:
    affected = _matching(col, card_ids, "is:buried")
    return affected, col.sched.unbury_cards(list(card_ids))


@as_collection_op(event_details=_ids_details)
def unbury_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return ValueWithChanges(*_unbury(col, card_ids),
                            event_changes=lambda: {"cards": {"updated": list(card_ids)}})


def _forget(col: Collection, card_ids: Sequence[int], *,
            restore_position: bool = False, reset_counts: bool = False) -> Any:
    affected = _matching(col, card_ids)
    changes = col.sched.schedule_cards_as_new(
        list(card_ids), restore_position=restore_position, reset_counts=reset_counts)
    return affected, changes


@as_collection_op(event_details=_ids_details)
def forget_cards(col: Collection, card_ids: Sequence[int], *,
                 restore_position: bool = False, reset_counts: bool = False) -> int:
    return ValueWithChanges(*_forget(
        col, card_ids, restore_position=restore_position, reset_counts=reset_counts))


def _set_due_date(col: Collection, card_ids: Sequence[int], days: str,
                  config_key: Optional[str] = None) -> Any:
    affected = _matching(col, card_ids)
    try:
        changes = col.sched.set_due_date(list(card_ids), days, config_key)
    except Exception as e:
        if type(e).__name__ in ("InvalidInput", "ValueError"):
            raise ValidationError(f"invalid due date '{days}': {e}") from e
        raise
    return affected, changes


@as_collection_op(event_details=_ids_details)
def set_due_date(col: Collection, card_ids: Sequence[int], days: str,
                 config_key: Optional[str] = None) -> int:
    return ValueWithChanges(*_set_due_date(col, card_ids, days, config_key))


def _resolve_change_deck(col: Collection, deck_id: Optional[int],
                         deck_name: Optional[str]) -> int:
    if deck_id is None and deck_name is None:
        raise ValidationError("one of deck_id or deck_name is required")
    if deck_id is None:
        deck = col.decks.by_name(str(deck_name))
        if deck is None:
            # Deliberately NOT creating the deck, matching POST /v1/notes.
            raise ValidationError(f"deck was not found: {deck_name}")
        return int(deck["id"])
    if col.decks.get(int(deck_id), default=False) is None:
        raise ResourceNotFoundError("deck", int(deck_id))
    return int(deck_id)


def _change_deck(col: Collection, card_ids: Sequence[int],
                 deck_id: Optional[int] = None, deck_name: Optional[str] = None) -> Any:
    did = _resolve_change_deck(col, deck_id, deck_name)
    changes = col.set_deck(list(card_ids), did)
    return _count(changes), changes


@as_collection_op(event_details=_ids_details)
def change_deck(col: Collection, card_ids: Sequence[int],
                deck_id: Optional[int] = None, deck_name: Optional[str] = None) -> int:
    return ValueWithChanges(*_change_deck(col, card_ids, deck_id, deck_name))


def _reposition(col: Collection, card_ids: Sequence[int], *,
                starting_from: int = 0, step_size: int = 1,
                randomize: bool = False, shift_existing: bool = False) -> Any:
    changes = col.sched.reposition_new_cards(
        list(card_ids), starting_from, step_size, randomize, shift_existing,
    )
    return _count(changes), changes


@as_collection_op(event_details=_ids_details)
def reposition_cards(col: Collection, card_ids: Sequence[int], *,
                     starting_from: int = 0, step_size: int = 1,
                     randomize: bool = False, shift_existing: bool = False) -> int:
    return ValueWithChanges(*_reposition(
        col, card_ids, starting_from=starting_from, step_size=step_size,
        randomize=randomize, shift_existing=shift_existing))


def _set_flag(col: Collection, card_ids: Sequence[int], flag: int) -> Any:
    if not 0 <= int(flag) <= 7:
        raise ValidationError("flag must be between 0 and 7")
    changes = col.set_user_flag_for_cards(int(flag), list(card_ids))
    return _count(changes), changes


@as_collection_op(event_details=_ids_details)
def set_flag(col: Collection, card_ids: Sequence[int], flag: int) -> int:
    return ValueWithChanges(*_set_flag(col, card_ids, flag))


def _set_ease(col: Collection, entries: Sequence[Dict[str, int]]) -> Any:
    out: List[bool] = []
    changes: Any = None
    for entry in entries:
        try:
            card = col.get_card(int(entry["id"]))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(False)
                continue
            raise
        card.factor = int(entry["factor"])
        changes = col.update_card(card)
        out.append(True)
    return out, changes


@as_collection_op(event_details=_entry_ids_details)
def set_ease_factors(col: Collection, entries: Sequence[Dict[str, int]]) -> List[bool]:
    """
    Per-entry success, so a missing card doesn't fail the whole batch.
    Returns a list aligned with `entries`.
    """
    out, changes = _set_ease(col, entries)
    return ValueWithChanges(out, changes) if changes is not None else out


@as_collection_op(event_details=_entry_ids_details)
def set_memory_states(col: Collection, entries: Sequence[Dict[str, Any]]) -> List[bool]:
    """
    Per-card FSRS state write, shaped like set_ease_factors: per-entry success,
    a missing card doesn't fail the batch. Entry dicts carry only the fields
    the caller sent (exclude_unset): a present key with None clears the value,
    an absent key leaves it alone. An entry with nothing to write reports
    False. Writes go through col.update_card, so this is a normal undoable
    CollectionOp - not a raw-DB write.
    """
    from anki import cards_pb2
    from anki.cards import FSRSMemoryState

    writable = ("memory_state", "desired_retention", "decay")
    # Refuse decay wholesale before any write: on a build whose card proto has
    # no decay column the assignment would be silently dropped on save.
    if (any("decay" in e for e in entries)
            and "decay" not in cards_pb2.Card.DESCRIPTOR.fields_by_name):
        raise UnsupportedAnkiVersionError("per-card decay")

    out: List[bool] = []
    changes: Any = None
    for entry in entries:
        if not any(k in entry for k in writable):
            out.append(False)
            continue
        try:
            card = col.get_card(int(entry["id"]))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(False)
                continue
            raise
        if "memory_state" in entry:
            state = entry["memory_state"]
            card.memory_state = None if state is None else FSRSMemoryState(
                stability=float(state["stability"]),
                difficulty=float(state["difficulty"]),
            )
        if "desired_retention" in entry:
            value = entry["desired_retention"]
            card.desired_retention = None if value is None else float(value)
        if "decay" in entry:
            value = entry["decay"]
            card.decay = None if value is None else float(value)
        changes = col.update_card(card)
        out.append(True)
    return ValueWithChanges(out, changes) if changes is not None else out


@as_collection_op
def relearn_cards(col: Collection, card_ids: Sequence[int]) -> int:
    """
    AnkiConnect's relearnCards. Anki exposes no scheduler API for this, so it
    is the one action with no native counterpart - the raw UPDATE is kept
    verbatim, just wrapped in a CollectionOp so it stays undoable.
    """
    ids = ",".join(str(int(c)) for c in card_ids)
    if not ids:
        return 0
    affected = _matching(col, card_ids)
    col.db.execute(f"update cards set type=3, queue=1 where id in ({ids})")
    return affected


@as_collection_op(event_details=lambda answers: {
    "card_ids": [int(a["card_id"]) for a in answers]})
def answer_cards(col: Collection, answers: Sequence[Dict[str, Any]]) -> Any:
    """
    Answer cards through the scheduler, AnkiConnect's answerCards. Entries are
    {"card_id", "ease"} with ease 1-4; a missing card reports False and an
    invalid ease raises mid-batch with earlier answers kept, both matching
    canonical. Works on a card in any state - the v3 scheduler derives the
    state from the card itself, and answering a suspended card unsuspends it.
    """
    out: List[bool] = []
    changes: Any = None
    for entry in answers:
        try:
            card = col.get_card(int(entry["card_id"]))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(False)
                continue
            raise
        # answerCard reads time_taken(), which explodes on the None a fresh
        # Card starts with - canonical starts the timer too.
        card.start_timer()
        changes = col.sched.answerCard(card, int(entry["ease"]))
        out.append(True)
    return ValueWithChanges(out, changes) if changes is not None else out


@as_collection_op(event_details=lambda card_id, values: {
    "card_ids": [int(card_id)]})
def set_card_values(col: Collection, card_id: int, values: Dict[str, Any]) -> Any:
    """
    Raw card-column write, AnkiConnect's setSpecificValueOfCard: setattr each
    key on the card object and save. No validation beyond what the card proto
    itself enforces - which columns need an explicit opt-in is wire-layer
    policy (RISKY_CARD_COLUMNS), not enforced here.
    """
    card = col.get_card(int(card_id))  # NotFoundError propagates
    for key, value in values.items():
        setattr(card, key, value)
    changes = col.update_card(card, skip_undo_entry=True)
    return ValueWithChanges(True, changes)


# Columns canonical's setSpecificValueOfCard refuses without warning_check:
# scheduling state and row linkage, where a bad write corrupts the card.
RISKY_CARD_COLUMNS = frozenset({
    "did", "id", "ivl", "lapses", "left", "mod", "nid",
    "odid", "odue", "ord", "queue", "reps", "type", "usn",
})


# ====================
# Batch: several verbs, one undo entry
# ====================

# Verb name (the :verb route names) -> (request model, raw runner). The
# runner returns (affected, changes) - the same raw the single route uses.
BATCH_VERBS: Dict[str, Any] = {
    "suspend": (CardIds, lambda col, b: _suspend(col, b.card_ids)),
    "unsuspend": (CardIds, lambda col, b: _unsuspend(col, b.card_ids)),
    "bury": (CardIds, lambda col, b: _bury(col, b.card_ids)),
    "unbury": (CardIds, lambda col, b: _unbury(col, b.card_ids)),
    "forget": (ForgetRequest, lambda col, b: _forget(
        col, b.card_ids, restore_position=b.restore_position,
        reset_counts=b.reset_counts)),
    "set-due-date": (SetDueDateRequest, lambda col, b: _set_due_date(
        col, b.card_ids, b.days, b.config_key)),
    "change-deck": (ChangeDeckRequest, lambda col, b: _change_deck(
        col, b.card_ids, b.deck_id, b.deck_name)),
    "reposition": (RepositionRequest, lambda col, b: _reposition(
        col, b.card_ids, starting_from=b.starting_from, step_size=b.step_size,
        randomize=b.randomize, shift_existing=b.shift_existing)),
    "set-flag": (SetFlagRequest, lambda col, b: _set_flag(col, b.card_ids, b.flag)),
    "set-ease": (SetEaseRequest, lambda col, b: _ease_affected(col, b)),
}


def _ease_affected(col: Collection, body: Any) -> Any:
    results, changes = _set_ease(col, [e.dict() for e in body.cards])
    return sum(1 for ok in results if ok), changes


def _batch_card_ids(operations: Sequence[Any], *_a: Any, **_k: Any) -> Dict[str, Any]:
    """Union of every card id in the batch, in first-seen order."""
    out: List[int] = []
    seen: set = set()
    for _name, body in operations:
        ids = (list(getattr(body, "card_ids", None) or [])
               or [e.id for e in getattr(body, "cards", None) or []])
        for cid in ids:
            cid = int(cid)
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return {"card_ids": out}


@as_collection_op(event_details=_batch_card_ids)
def batch_cards(col: Collection, operations: Sequence[Any]) -> Any:
    """
    Run several scheduling verbs as ONE undoable operation. `operations` is
    [(verb_name, parsed request model), ...], already shape-validated by the
    route.

    Mechanics: anchor a custom undo entry, run each verb's raw exactly as the
    single route would, and merge_undo_entries(target) after EVERY step - the
    merge keeps the undo deque at one entry (so Anki's 30-step cap can never
    swallow the anchor) and its return value is the union of all steps'
    OpChanges, which is what the op reports (one repaint, one event).

    NOT atomic: everything checkable is validated before the anchor, but a
    backend error mid-run leaves the earlier steps applied - and Anki wipes
    the undo queues on any failed op, so they can't be undone. Never call
    update_card/update_note(skip_undo_entry=True) or Card.flush() in here:
    both clear the undo queues and kill the merge target.
    """
    if not operations:
        raise ValidationError("at least one operation is required")
    for name, body in operations:
        if name not in BATCH_VERBS:
            raise ValidationError(
                f"unknown op '{name}'; expected one of {sorted(BATCH_VERBS)}")
        if name == "change-deck":
            # Resolve now so a bad deck fails the batch before any write.
            _resolve_change_deck(col, body.deck_id, body.deck_name)

    target = col.add_custom_undo_entry("Card Batch")
    results: List[Dict[str, Any]] = []
    changes: Any = None
    for name, body in operations:
        _model, run = BATCH_VERBS[name]
        affected, _step_changes = run(col, body)
        changes = col.merge_undo_entries(target)
        results.append({"op": name, "affected": int(affected)})

    value = {"affected": sum(r["affected"] for r in results), "results": results}
    return ValueWithChanges(value, changes)

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

from ...shared.errors import ResourceNotFoundError, ValidationError
from ...shared.schemas.cards import CardInfo
from ..ops import as_collection_op, as_query_op

QUEUE_SUSPENDED = -1
BURIED_QUEUES = (-2, -3)  # sibling-buried, manually buried

# Fields that need the card's note loaded. Rendering question/answer goes
# through the backend template renderer, which is a separate call again.
NOTE_WANTS = frozenset({"model_name", "css", "fields"})
RENDER_WANTS = frozenset({"question", "answer"})


def _deck_names(col: Collection) -> Dict[int, str]:
    # One call for the whole page; col.decks.get() per card would be a backend
    # round trip each.
    return {int(d.id): d.name for d in col.decks.all_names_and_ids(
        skip_empty_default=False, include_filtered=True)}


def _next_reviews(col: Collection, card_id: int) -> Optional[List[str]]:
    # The only private-API read in the resource. If a future Anki moves it,
    # the field goes missing rather than the whole request failing.
    try:
        states = col._backend.get_scheduling_states(card_id)
        return [str(s) for s in col._backend.describe_next_states(states)]
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

    return CardInfo(
        id=int(card.id),
        nid=int(card.nid),
        did=int(card.did),
        odid=int(getattr(card, "odid", 0) or 0),
        ord=int(card.ord),
        mod=int(getattr(card, "mod", 0) or 0),
        usn=int(getattr(card, "usn", 0) or 0),
        type=int(card.type),
        queue=int(card.queue),
        due=int(card.due),
        odue=int(getattr(card, "odue", 0) or 0),
        ivl=int(card.ivl),
        factor=int(card.factor),
        reps=int(card.reps),
        lapses=int(card.lapses),
        left=int(card.left),
        flags=int(getattr(card, "flags", 0) or 0),
        original_position=getattr(card, "original_position", None),
        custom_data=getattr(card, "custom_data", "") or "",
        memory_state=_memory_state(card),
        desired_retention=getattr(card, "desired_retention", None),
        decay=getattr(card, "decay", None),
        last_review_time=getattr(card, "last_review_time", None),
        suspended=int(card.queue) == QUEUE_SUSPENDED,
        buried=int(card.queue) in BURIED_QUEUES,
        flag=int(getattr(card, "flags", 0) or 0) & 0b111,
        deck_name=deck_names.get(int(card.did), ""),
        model_name=model_name,
        css=css,
        fields=fields,
        question=question,
        answer=answer,
        next_reviews=next_reviews,
    )


# ====================
# Reads
# ====================

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
    deck_names = _deck_names(col)
    out: List[CardInfo] = []
    for cid in ids:
        try:
            card = col.get_card(int(cid))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue  # missing ids are skipped, like get_notes_by_ids
            raise
        out.append(_card_info(col, card, deck_names, wants))
    return out


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

    One search for the whole batch, so `affected` means the same thing on
    every verb: cards the call actually changed.
    """
    wanted = {int(c) for c in card_ids}
    if not wanted:
        return 0
    return len(wanted & {int(i) for i in col.find_cards(query)})


@as_collection_op
def suspend_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return _count(col.sched.suspend_cards(list(card_ids)))


@as_collection_op
def unsuspend_cards(col: Collection, card_ids: Sequence[int]) -> int:
    # Anki's unsuspend returns a bare OpChanges, so count the cards that were
    # actually suspended before we touched them.
    affected = _matching(col, card_ids, "is:suspended")
    col.sched.unsuspend_cards(list(card_ids))
    return affected


@as_collection_op
def bury_cards(col: Collection, card_ids: Sequence[int]) -> int:
    return _count(col.sched.bury_cards(list(card_ids), manual=True))


@as_collection_op
def unbury_cards(col: Collection, card_ids: Sequence[int]) -> int:
    affected = _matching(col, card_ids, "is:buried")
    col.sched.unbury_cards(list(card_ids))
    return affected


@as_collection_op
def forget_cards(col: Collection, card_ids: Sequence[int], *,
                 restore_position: bool = False, reset_counts: bool = False) -> int:
    affected = _matching(col, card_ids)
    col.sched.schedule_cards_as_new(
        list(card_ids), restore_position=restore_position, reset_counts=reset_counts)
    return affected


@as_collection_op
def set_due_date(col: Collection, card_ids: Sequence[int], days: str,
                 config_key: Optional[str] = None) -> int:
    affected = _matching(col, card_ids)
    try:
        col.sched.set_due_date(list(card_ids), days, config_key)
    except Exception as e:
        if type(e).__name__ in ("InvalidInput", "ValueError"):
            raise ValidationError(f"invalid due date '{days}': {e}") from e
        raise
    return affected


@as_collection_op
def change_deck(col: Collection, card_ids: Sequence[int],
                deck_id: Optional[int] = None, deck_name: Optional[str] = None) -> int:
    if deck_id is None and deck_name is None:
        raise ValidationError("one of deck_id or deck_name is required")
    if deck_id is None:
        deck = col.decks.by_name(str(deck_name))
        if deck is None:
            # Deliberately NOT creating the deck, matching POST /v1/notes.
            raise ValidationError(f"deck was not found: {deck_name}")
        deck_id = int(deck["id"])
    elif col.decks.get(int(deck_id), default=False) is None:
        raise ResourceNotFoundError("deck", int(deck_id))
    return _count(col.set_deck(list(card_ids), int(deck_id)))


@as_collection_op
def reposition_cards(col: Collection, card_ids: Sequence[int], *,
                     starting_from: int = 0, step_size: int = 1,
                     randomize: bool = False, shift_existing: bool = False) -> int:
    return _count(col.sched.reposition_new_cards(
        list(card_ids), starting_from, step_size, randomize, shift_existing,
    ))


@as_collection_op
def set_flag(col: Collection, card_ids: Sequence[int], flag: int) -> int:
    if not 0 <= int(flag) <= 7:
        raise ValidationError("flag must be between 0 and 7")
    return _count(col.set_user_flag_for_cards(int(flag), list(card_ids)))


@as_collection_op
def set_ease_factors(col: Collection, entries: Sequence[Dict[str, int]]) -> List[bool]:
    """
    Per-entry success, so a missing card doesn't fail the whole batch.
    Returns a list aligned with `entries`.
    """
    out: List[bool] = []
    for entry in entries:
        try:
            card = col.get_card(int(entry["id"]))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                out.append(False)
                continue
            raise
        card.factor = int(entry["factor"])
        col.update_card(card)
        out.append(True)
    return out


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

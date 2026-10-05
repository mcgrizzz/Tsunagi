"""AnkiConnect card actions.

Shared native adapters handle ordinary reads. Compatibility collection operations
preserve raw arguments, legacy scheduling behavior and upstream error order.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.cards import (
    RISKY_CARD_COLUMNS,
    cards_mod_times,
    cards_suspended,
    get_cards_by_ids,
    raw_left_and_flags,
    set_card_values,
)
from ....adapters.anki.compat import raw_id_list
from ....adapters.anki.reviews import card_intervals, cards_are_due
from ..registry import registry


class CardsParams(BaseModel):
    cards: Any = ...


class CardsInfoParams(BaseModel):
    # The compatibility boundary must not coerce strings, floats or booleans.
    cards: Any = ...


class DueParams(BaseModel):
    cards: Any


class CardParams(BaseModel):
    card: Any = ...


class SuspendParams(BaseModel):
    cards: Any = ...
    suspend: Any = True


class SetEaseFactorsParams(BaseModel):
    cards: Any = ...
    easeFactors: Any = ...


class GetIntervalsParams(BaseModel):
    cards: Any
    complete: Any = False


class SetDueDateParams(BaseModel):
    cards: Any = ...
    days: Any = ...


def _object_ids(values):
    from ....adapters.anki.compat import validate_object_ids

    ids = raw_id_list(values)
    if any(type(value) is not int for value in ids):
        return validate_object_ids(ids)
    return ids


@registry.register("getEaseFactors", params=CardsParams, permission="read:cards")
def ac_getEaseFactors(p: CardsParams) -> List[Optional[int]]:
    from ....adapters.anki.compat import read_ease_factors_raw

    return read_ease_factors_raw(p.cards)


@registry.register("setEaseFactors", params=SetEaseFactorsParams, permission="write:cards")
def ac_setEaseFactors(p: SetEaseFactorsParams) -> List[bool]:
    from ....adapters.anki.compat import set_raw_ease_factors

    result, error = set_raw_ease_factors(p.cards, p.easeFactors)
    if error is not None:
        raise ValueError(error)
    return result


@registry.register("suspend", params=SuspendParams, permission="write:cards")
def ac_suspend(p: SuspendParams) -> bool:
    from ....adapters.anki.compat import suspend_cards_raw

    return suspend_cards_raw(p.cards, p.suspend)


@registry.register("unsuspend", params=CardsInfoParams, permission="write:cards")
def ac_unsuspend(p: CardsInfoParams) -> None:
    # Upstream discards suspend's return value.
    ac_suspend(SuspendParams(cards=p.cards, suspend=False))


@registry.register("suspended", params=CardParams, permission="read:cards")
def ac_suspended(p: CardParams) -> bool:
    from ....adapters.anki.compat import read_suspended_raw

    return read_suspended_raw([p.card])[0]


@registry.register("areSuspended", params=CardsInfoParams, permission="read:cards")
def ac_areSuspended(p: CardsInfoParams) -> List[Optional[bool]]:
    from ....adapters.anki.compat import read_suspended_raw

    ids = raw_id_list(p.cards)
    if all(type(cid) is int and cid != 0 for cid in ids):
        return cards_suspended(ids)
    return read_suspended_raw(ids, missing_ok=True)


@registry.register("areDue", params=DueParams, permission="read:cards")
def ac_areDue(p: DueParams) -> List[bool]:
    try:
        ids = raw_id_list(p.cards)
        if any(type(cid) is not int or not 0 <= cid < 2**63 for cid in ids):
            from ....adapters.anki.compat import raw_card_schedule

            return raw_card_schedule(ids, due=True)
        if any(history == [] for history in card_intervals(ids, True)):
            raise ValueError("list index out of range")
        return cards_are_due(ids)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


@registry.register("getIntervals", params=GetIntervalsParams, permission="read:cards")
def ac_getIntervals(p: GetIntervalsParams) -> List[Any]:
    try:
        ids = raw_id_list(p.cards)
        if any(type(cid) is not int or not 0 <= cid < 2**63 for cid in ids):
            from ....adapters.anki.compat import raw_card_schedule

            return raw_card_schedule(ids, complete=p.complete)
        histories = card_intervals(ids, True)
        if p.complete:
            return histories
        return [history[-1] if isinstance(history, list) else history for history in histories]
    except (TypeError, IndexError) as exc:
        raise ValueError(str(exc)) from exc


@registry.register("cardsToNotes", params=CardsParams, permission="read:cards")
def ac_cardsToNotes(p: CardsParams) -> List[int]:
    from ....adapters.anki.compat import notes_of_cards_raw

    return notes_of_cards_raw(p.cards)


@registry.register("cardsModTime", params=CardsInfoParams, permission="read:cards")
def ac_cardsModTime(p: CardsInfoParams) -> List[Dict[str, Any]]:
    return cards_mod_times(_object_ids(p.cards))


# Everything cardsInfo's wire shape reads - notably NOT retrievability,
# whose build is a per-card FSRS stats call the response would just discard.
_CARDS_INFO_WANTS = {
    "id", "fields", "template_index", "question", "answer", "note_type_name", "deck_name",
    "css", "ease_factor", "interval", "note_id", "type", "queue", "due", "reps",
    "lapses", "modified", "next_reviews",
}


@registry.register("cardsInfo", params=CardsInfoParams, permission="read:cards")
def ac_cardsInfo(p: CardsInfoParams) -> List[Dict[str, Any]]:
    if p.cards is None:
        raise ValueError("'NoneType' object is not iterable")
    ids = _object_ids(p.cards)
    # Anki treats get_card(0) as constructing an unsaved card. Upstream catches
    # its missing-note error and returns an empty object at that input position.
    by_id = {c.id: c for c in get_cards_by_ids([cid for cid in ids if cid], _CARDS_INFO_WANTS)}
    raw = raw_left_and_flags(list(by_id)) if by_id else {}
    out: List[Dict[str, Any]] = []
    for cid in ids:
        card = by_id.get(int(cid))
        if card is None:
            out.append({})  # keep input/output positions aligned
            continue
        fields = {f.name: {"value": f.value, "order": f.index}
                  for f in (card.fields or [])}
        out.append({
            "cardId": card.id,
            "fields": fields,
            "fieldOrder": card.template_index,
            "question": card.question,
            "answer": card.answer,
            "modelName": card.note_type_name,
            "ord": card.template_index,
            "deckName": card.deck_name,
            "css": card.css,
            # 10x the ease percentage: 310% is reported as 3100.
            "factor": card.ease_factor,
            "interval": card.interval,
            "note": card.note_id,
            "type": card.type,
            "queue": card.queue,
            "due": card.due,
            "reps": card.reps,
            "lapses": card.lapses,
            "left": raw[card.id]["left"],
            "mod": card.modified,
            "nextReviews": card.next_reviews or [],
            "flags": raw[card.id]["flags"],
        })
    return out


@registry.register("forgetCards", params=CardsInfoParams, permission="write:cards")
def ac_forgetCards(p: CardsInfoParams) -> None:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "forget")


@registry.register("relearnCards", params=CardsInfoParams, permission="write:cards")
def ac_relearnCards(p: CardsInfoParams) -> None:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "relearn")


@registry.register("setDueDate", params=SetDueDateParams, permission="write:cards")
def ac_setDueDate(p: SetDueDateParams) -> bool:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "due", p.days)
    return True


class AnswerCardsParams(BaseModel):
    answers: Any = ...


@registry.register("answerCards", params=AnswerCardsParams, permission="write:cards")
def ac_answerCards(p: AnswerCardsParams) -> List[bool]:
    from ....adapters.anki.compat import answer_cards_raw

    result, error = answer_cards_raw(p.answers)
    if error is not None:
        raise ValueError(error)
    return result


@registry.register("setSpecificValueOfCard", permission="write:cards")
def ac_setSpecificValueOfCard(params: Dict[str, Any]) -> Any:
    """
    Canonical's return ladder, quirks and all: every input problem is a bare
    False, success is [True], and a failure while writing is [[False, "err"]].
    Raw params on purpose - the False branches need type checks, not
    validation errors.
    """
    card = params.get("card")
    keys = params.get("keys")
    new_values = params.get("newValues")
    if isinstance(card, list):
        return False
    if not isinstance(keys, list) or not isinstance(new_values, list):
        return False
    if len(new_values) != len(keys):
        return False
    # Canonical tests `warning_check is False` - literally. A null or 0 slips
    # past the guard there, so it does here too.
    if params.get("warning_check", False) is False:
        if any(key in RISKY_CARD_COLUMNS for key in keys):
            return False
    try:
        set_card_values(card, dict(zip(keys, new_values)))
        return [True]
    except Exception as e:
        return [[False, str(e)]]

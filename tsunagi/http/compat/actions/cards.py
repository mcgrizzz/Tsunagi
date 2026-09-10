"""AnkiConnect card actions.

Shared native adapters handle ordinary reads. Compatibility collection operations
preserve raw arguments, legacy scheduling behavior and upstream error order.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.cards import (
    RISKY_CARD_COLUMNS,
    card_ease_factors,
    cards_mod_times,
    cards_suspended,
    get_cards_by_ids,
    notes_of_cards,
    set_card_values,
)
from ....adapters.anki.compat import raw_id_list
from ....adapters.anki.reviews import card_intervals, cards_are_due
from ..registry import registry


class CardsParams(BaseModel):
    cards: List[int]


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
    complete: bool = False


class SetDueDateParams(BaseModel):
    cards: Any = ...
    days: Any = ...


def _object_ids(values):
    from ....adapters.anki.compat import validate_object_ids

    ids = raw_id_list(values)
    if any(type(value) is not int for value in ids):
        return validate_object_ids(ids)
    return ids


@registry.register("getEaseFactors", params=CardsParams)
def ac_getEaseFactors(p: CardsParams) -> List[Optional[int]]:
    return card_ease_factors(p.cards)


@registry.register("setEaseFactors", params=SetEaseFactorsParams)
def ac_setEaseFactors(p: SetEaseFactorsParams) -> List[bool]:
    from ....adapters.anki.compat import set_raw_ease_factors

    result, error = set_raw_ease_factors(p.cards, p.easeFactors)
    if error is not None:
        raise ValueError(error)
    return result


@registry.register("suspend", params=SuspendParams)
def ac_suspend(p: SuspendParams) -> bool:
    from ....adapters.anki.compat import suspend_cards_raw

    return suspend_cards_raw(p.cards, p.suspend)


@registry.register("unsuspend", params=CardsInfoParams)
def ac_unsuspend(p: CardsInfoParams) -> None:
    # Upstream discards suspend's return value.
    ac_suspend(SuspendParams(cards=p.cards, suspend=False))


@registry.register("suspended", params=CardParams)
def ac_suspended(p: CardParams) -> bool:
    from ....adapters.anki.compat import read_suspended_raw

    return read_suspended_raw([p.card])[0]


@registry.register("areSuspended", params=CardsInfoParams)
def ac_areSuspended(p: CardsInfoParams) -> List[Optional[bool]]:
    from ....adapters.anki.compat import read_suspended_raw

    ids = raw_id_list(p.cards)
    if all(type(cid) is int and cid != 0 for cid in ids):
        return cards_suspended(ids)
    return read_suspended_raw(ids, missing_ok=True)


@registry.register("areDue", params=DueParams)
def ac_areDue(p: DueParams) -> List[bool]:
    try:
        ids = raw_id_list(p.cards)
        if any(type(cid) is not int for cid in ids):
            from ....adapters.anki.compat import raw_card_schedule

            return raw_card_schedule(ids, due=True)
        if any(history == [] for history in card_intervals(ids, True)):
            raise ValueError("list index out of range")
        return cards_are_due(ids)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


@registry.register("getIntervals", params=GetIntervalsParams)
def ac_getIntervals(p: GetIntervalsParams) -> List[Any]:
    try:
        ids = raw_id_list(p.cards)
        if any(type(cid) is not int for cid in ids):
            from ....adapters.anki.compat import raw_card_schedule

            return raw_card_schedule(ids, complete=p.complete)
        histories = card_intervals(ids, True)
        if p.complete:
            return histories
        return [history[-1] if isinstance(history, list) else history for history in histories]
    except (TypeError, IndexError) as exc:
        raise ValueError(str(exc)) from exc


@registry.register("cardsToNotes", params=CardsParams)
def ac_cardsToNotes(p: CardsParams) -> List[int]:
    return notes_of_cards(p.cards)


@registry.register("cardsModTime", params=CardsInfoParams)
def ac_cardsModTime(p: CardsInfoParams) -> List[Dict[str, Any]]:
    return cards_mod_times(_object_ids(p.cards))


# Everything cardsInfo's wire shape reads - notably NOT retrievability,
# whose build is a per-card FSRS stats call the response would just discard.
_CARDS_INFO_WANTS = {
    "id", "fields", "ord", "question", "answer", "model_name", "deck_name",
    "css", "factor", "interval", "note_id", "type", "queue", "due", "reps",
    "lapses", "left", "mod", "next_reviews", "flags",
}


@registry.register("cardsInfo", params=CardsInfoParams)
def ac_cardsInfo(p: CardsInfoParams) -> List[Dict[str, Any]]:
    if p.cards is None:
        raise ValueError("'NoneType' object is not iterable")
    ids = _object_ids(p.cards)
    # Anki treats get_card(0) as constructing an unsaved card. Upstream catches
    # its missing-note error and returns an empty object at that input position.
    by_id = {c.id: c for c in get_cards_by_ids([cid for cid in ids if cid], _CARDS_INFO_WANTS)}
    out: List[Dict[str, Any]] = []
    for cid in ids:
        card = by_id.get(int(cid))
        if card is None:
            out.append({})  # keep input/output positions aligned
            continue
        fields = {f.name: {"value": f.value, "order": f.ord}
                  for f in (card.fields or [])}
        out.append({
            "cardId": card.id,
            "fields": fields,
            "fieldOrder": card.ord,
            "question": card.question,
            "answer": card.answer,
            "modelName": card.model_name,
            "ord": card.ord,
            "deckName": card.deck_name,
            "css": card.css,
            # 10x the ease percentage: 310% is reported as 3100.
            "factor": card.factor,
            "interval": card.interval,
            "note": card.note_id,
            "type": card.type,
            "queue": card.queue,
            "due": card.due,
            "reps": card.reps,
            "lapses": card.lapses,
            "left": card.left,
            "mod": card.mod,
            "nextReviews": card.next_reviews or [],
            "flags": card.flags,
        })
    return out


@registry.register("forgetCards", params=CardsInfoParams)
def ac_forgetCards(p: CardsInfoParams) -> None:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "forget")


@registry.register("relearnCards", params=CardsInfoParams)
def ac_relearnCards(p: CardsInfoParams) -> None:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "relearn")


@registry.register("setDueDate", params=SetDueDateParams)
def ac_setDueDate(p: SetDueDateParams) -> bool:
    from ....adapters.anki.compat import reschedule_cards_raw

    reschedule_cards_raw(p.cards, "due", p.days)
    return True


class AnswerCardsParams(BaseModel):
    answers: Any = ...


@registry.register("answerCards", params=AnswerCardsParams)
def ac_answerCards(p: AnswerCardsParams) -> List[bool]:
    from ....adapters.anki.compat import answer_cards_raw

    result, error = answer_cards_raw(p.answers)
    if error is not None:
        raise ValueError(error)
    return result


@registry.register("setSpecificValueOfCard")
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

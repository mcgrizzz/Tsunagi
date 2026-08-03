"""
AnkiConnect compatibility handlers for card actions.

Thin translations over the same adapters /v1/cards uses. Every wire quirk
below is quoted from canonical (git.sr.ht/~foosoft/anki-connect, plugin/
__init__.py) - several of these return values look like mistakes and are
relied on anyway, so they are reproduced rather than tidied up.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.cards import (
    card_ease_factors,
    cards_mod_times,
    cards_suspended,
    forget_cards,
    get_cards_by_ids,
    notes_of_cards,
    relearn_cards,
    set_due_date,
    set_ease_factors,
    suspend_cards,
    unsuspend_cards,
)
from ....adapters.anki.reviews import card_intervals, cards_are_due
from ..errors import CARD_NOT_FOUND
from ..registry import registry


class CardsParams(BaseModel):
    cards: List[int]


class CardParams(BaseModel):
    card: int


class SuspendParams(BaseModel):
    cards: List[int]
    suspend: bool = True


class SetEaseFactorsParams(BaseModel):
    cards: List[int]
    easeFactors: List[int]


class GetIntervalsParams(BaseModel):
    cards: List[int]
    complete: bool = False


class SetDueDateParams(BaseModel):
    cards: List[int]
    days: str


def _require_all_present(card_ids: List[int]) -> List[bool]:
    """
    Canonical's suspend()/suspended() reach cards through getCard, which
    raises for an unknown id instead of reporting it. Mirror that.
    """
    states = cards_suspended(card_ids)
    for cid, state in zip(card_ids, states):
        if state is None:
            raise ValueError(CARD_NOT_FOUND.format(cid))
    return [bool(s) for s in states]


@registry.register("getEaseFactors", params=CardsParams)
def ac_getEaseFactors(p: CardsParams) -> List[Optional[int]]:
    return card_ease_factors(p.cards)


@registry.register("setEaseFactors", params=SetEaseFactorsParams)
def ac_setEaseFactors(p: SetEaseFactorsParams) -> List[bool]:
    # Parallel arrays on the wire; a missing card is False, not an error.
    entries = [{"id": cid, "factor": factor}
               for cid, factor in zip(p.cards, p.easeFactors)]
    return set_ease_factors(entries)


@registry.register("suspend", params=SuspendParams)
def ac_suspend(p: SuspendParams) -> bool:
    """
    False when every card is already in the requested state, True otherwise.

    Canonical computes that by removing entries from the list it is iterating,
    which skips elements; the *return value* is reproduced, the skipping is
    not - it only ever caused redundant work.
    """
    states = _require_all_present(p.cards)
    todo = [cid for cid, suspended in zip(p.cards, states) if suspended != p.suspend]
    if not todo:
        return False
    suspend_cards(todo) if p.suspend else unsuspend_cards(todo)
    return True


@registry.register("unsuspend", params=CardsParams)
def ac_unsuspend(p: CardsParams) -> None:
    # Returns None: canonical calls suspend() without returning its result,
    # and clients see `"result": null`.
    ac_suspend(SuspendParams(cards=p.cards, suspend=False))


@registry.register("suspended", params=CardParams)
def ac_suspended(p: CardParams) -> bool:
    return _require_all_present([p.card])[0]


@registry.register("areSuspended", params=CardsParams)
def ac_areSuspended(p: CardsParams) -> List[Optional[bool]]:
    # Unlike `suspended`, a missing card is None here rather than an error.
    return cards_suspended(p.cards)


@registry.register("areDue", params=CardsParams)
def ac_areDue(p: CardsParams) -> List[bool]:
    return cards_are_due(p.cards)


@registry.register("getIntervals", params=GetIntervalsParams)
def ac_getIntervals(p: GetIntervalsParams) -> List[Any]:
    return card_intervals(p.cards, p.complete)


@registry.register("cardsToNotes", params=CardsParams)
def ac_cardsToNotes(p: CardsParams) -> List[int]:
    return notes_of_cards(p.cards)


@registry.register("cardsModTime", params=CardsParams)
def ac_cardsModTime(p: CardsParams) -> List[Dict[str, Any]]:
    return cards_mod_times(p.cards)


@registry.register("cardsInfo", params=CardsParams)
def ac_cardsInfo(p: CardsParams) -> List[Dict[str, Any]]:
    by_id = {c.id: c for c in get_cards_by_ids(p.cards)}
    out: List[Dict[str, Any]] = []
    for cid in p.cards:
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


@registry.register("forgetCards", params=CardsParams)
def ac_forgetCards(p: CardsParams) -> None:
    # restore_position=True is canonical's choice, not Anki's default.
    forget_cards(p.cards, restore_position=True, reset_counts=False)


@registry.register("relearnCards", params=CardsParams)
def ac_relearnCards(p: CardsParams) -> None:
    relearn_cards(p.cards)


@registry.register("setDueDate", params=SetDueDateParams)
def ac_setDueDate(p: SetDueDateParams) -> bool:
    set_due_date(p.cards, p.days)
    return True

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
    RISKY_CARD_COLUMNS,
    answer_cards,
    card_ease_factors,
    cards_mod_times,
    cards_suspended,
    forget_cards,
    get_cards_by_ids,
    notes_of_cards,
    relearn_cards,
    set_card_values,
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


class CardsInfoParams(BaseModel):
    cards: Optional[List[int]] = ...


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
    entries = []
    for index, cid in enumerate(p.cards):
        if index >= len(p.easeFactors):
            # Upstream skips missing cards before indexing easeFactors, and
            # keeps earlier writes when a present card runs past the array.
            if card_ease_factors([cid])[0] is not None:
                set_ease_factors(entries)
                raise ValueError("list index out of range")
            factor = 0  # ignored by the native writer for a missing card
        else:
            factor = p.easeFactors[index]
        entries.append({"id": cid, "factor": factor})
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
    # Anki treats get_card(0) as constructing an unsaved card. Upstream catches
    # its missing-note error and returns an empty object at that input position.
    by_id = {c.id: c for c in get_cards_by_ids([cid for cid in p.cards if cid], _CARDS_INFO_WANTS)}
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
    try:
        set_due_date(p.cards, p.days)
    except Exception as exc:
        # The native API adds context; the shim exposes Anki's original error.
        cause = exc.__cause__
        if cause is not None and type(cause).__name__ in ("InvalidInput", "ValueError"):
            raise ValueError(str(cause)) from exc
        raise
    return True


class AnswerCardsParams(BaseModel):
    # Entries stay raw dicts: a missing cardId/ease key must surface as
    # canonical's KeyError string, not a pydantic validation message.
    answers: List[Dict[str, Any]]


@registry.register("answerCards", params=AnswerCardsParams)
def ac_answerCards(p: AnswerCardsParams) -> List[bool]:
    """
    Per-card success bools; a missing card is False, an invalid ease raises.

    Apply the prefix before reporting a malformed entry. An invalid ease in
    that prefix takes precedence over a later missing key, matching canonical.
    """
    entries = []
    malformed = None
    for a in p.answers:
        try:
            entries.append({"card_id": a["cardId"], "ease": a["ease"]})
        except KeyError as e:
            # Canonical's KeyError surfaces as its str ("'cardId'"); ours must
            # be a ValueError to carry the message past the dispatcher's
            # leak-nothing default.
            malformed = ValueError(str(e))
            break
    try:
        result = answer_cards(entries) if entries or malformed is None else []
    except Exception as e:
        if str(e) == "invalid ease":   # anki's own message, a client error
            raise ValueError("invalid ease") from e
        raise
    if malformed is not None:
        raise malformed
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

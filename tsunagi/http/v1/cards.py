import time
from typing import Any, Callable, List

from fastapi import Body
from pydantic import ValidationError as PydanticValidationError

from ...adapters.anki.cards import (
    BATCH_VERBS,
    RISKY_CARD_COLUMNS,
    answer_cards,
    batch_cards,
    bury_cards,
    change_deck,
    find_card_ids,
    forget_cards,
    get_cards_by_ids,
    get_cards_of_notes,
    reposition_cards,
    set_card_values,
    set_due_date,
    set_ease_factors,
    set_flag,
    set_memory_states,
    suspend_cards,
    unbury_cards,
    unsuspend_cards,
)
from ...adapters.settings import settings
from ...shared.errors import (
    ResourceNotFoundError,
    ValidationError,
    handle_mutation_errors,
)
from ...shared.planning import IndexSpec, SearchSpec, SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes, make_id_getter
from ...shared.schemas.cards import (
    AnswerRequest,
    BatchRequest,
    BatchResult,
    CardIds,
    ChangeDeckRequest,
    ForgetRequest,
    RepositionRequest,
    SchedulingResult,
    SetCardValuesRequest,
    SetDueDateRequest,
    SetEaseRequest,
    SetFlagRequest,
    SetMemoryStateRequest,
)
from ...shared.schemas.wrappers import Paginated


def _int_id(v: Any) -> Any:
    return int(v) if isinstance(v, (int, str)) and str(v).isdigit() else None


caps = SourceCaps(
    # No fetch_all and no columns_fetchers, for the same reason as notes:
    # materializing every card must be unreachable, and no backend route
    # returns a cheaper subset of a card row.
    indices=[
        IndexSpec(path=("id",), fetch_values=get_cards_by_ids, coerce=_int_id),
        IndexSpec(path=("note_id",), fetch_values=get_cards_of_notes, coerce=_int_id),
    ],
    search=SearchSpec(find_ids=find_card_ids, hydrate=get_cards_by_ids),
    # No MutationCaps: cards aren't created or deleted directly - they're
    # generated from notes by a notetype's templates. Everything a caller can
    # legitimately change about a card is a scheduling verb below.
)

# Query: GET /v1/cards (?search=...), POST /v1/cards/query
router = create_resource_routes(
    path="/v1/cards",
    caps=caps,
    response_model=Paginated[ModelRow],
    id_getter=make_id_getter("id"),
    resource_name="card",
    resource_plural="cards",
    tag="Cards",
    description="Cards are generated from notes by a model's templates. Use `search` for Anki query syntax; scheduling changes go through the verb routes.",
)


def _verb(path: str, summary: str, description: str) -> Callable:
    """
    Register a batch scheduling route.

    A REST deviation on purpose: these are operations on a set of cards, not
    edits to one card's representation, and doing them one PATCH at a time
    would mean one undo entry (and one op) per card. Same `resource:verb`
    convention as POST /v1/notes:check.
    """
    def decorate(fn: Callable) -> Callable:
        operation_id = "cards" + "".join(p.capitalize() for p in path.split("-"))
        return router.post(
            f"/v1/cards:{path}",
            response_model=SchedulingResult,
            summary=summary,
            description=description,
            tags=["Cards"],
            operation_id=operation_id,
        )(handle_mutation_errors(path)(fn))
    return decorate


def _result(affected: Any, start: float) -> SchedulingResult:
    return SchedulingResult(
        affected=int(affected),
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )


@_verb("suspend", "Suspend cards", "Removes cards from review until unsuspended.")
def suspend(body: CardIds = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(suspend_cards(body.card_ids), start)


@_verb("unsuspend", "Unsuspend cards", "Returns suspended cards to their queue.")
def unsuspend(body: CardIds = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(unsuspend_cards(body.card_ids), start)


@_verb("bury", "Bury cards", "Hides cards until the next day.")
def bury(body: CardIds = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(bury_cards(body.card_ids), start)


@_verb("unbury", "Unbury cards", "Returns buried cards to their queue.")
def unbury(body: CardIds = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(unbury_cards(body.card_ids), start)


@_verb("forget", "Reset cards to new",
       "Puts cards back in the new queue, optionally restoring their original position.")
def forget(body: ForgetRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    affected = forget_cards(
        body.card_ids,
        restore_position=body.restore_position,
        reset_counts=body.reset_counts,
    )
    return _result(affected, start)


@_verb("set-due-date", "Set the due date",
       "`days` is '5' (due in five days) or '5-7' (a random day in that range).")
def set_due(body: SetDueDateRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(set_due_date(body.card_ids, body.days, body.config_key), start)


@_verb("change-deck", "Move cards to another deck",
       "Takes deck_id or deck_name. The deck must already exist - this never creates one.")
def move(body: ChangeDeckRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(change_deck(body.card_ids, body.deck_id, body.deck_name), start)


@_verb("reposition", "Reposition new cards",
       "Reassigns the position (`due`) of cards in the new queue.")
def reposition(body: RepositionRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    affected = reposition_cards(
        body.card_ids,
        starting_from=body.starting_from,
        step_size=body.step_size,
        randomize=body.randomize,
        shift_existing=body.shift_existing,
    )
    return _result(affected, start)


@_verb("set-flag", "Set the coloured flag", "0 clears the flag; 1-7 are Anki's colours.")
def flag(body: SetFlagRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    return _result(set_flag(body.card_ids, body.flag), start)


@_verb("set-ease", "Set ease factors",
       "Per-card ease, stored as an integer 10x the percentage (250% is 2500).")
def ease(body: SetEaseRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    results: List[bool] = set_ease_factors([e.dict() for e in body.cards])
    return _result(sum(1 for ok in results if ok), start)


@_verb("set-memory-state", "Set FSRS memory state",
       "Overwrites per-card FSRS state (stability/difficulty, desired retention, "
       "decay) - how FSRS helper tools reschedule. An omitted field is left "
       "unchanged; an explicit null clears it. Off by default: requires the "
       "`gates.cards_set_memory_state` config gate.")
def set_memory_state(body: SetMemoryStateRequest = Body(...)) -> SchedulingResult:
    if not settings.gate_enabled("cards_set_memory_state"):
        raise ValidationError(
            "cards:set-memory-state is disabled; enable gates.cards_set_memory_state in the config"
        )
    start = time.perf_counter()
    results: List[bool] = set_memory_states(
        [e.dict(exclude_unset=True) for e in body.cards])
    return _result(sum(1 for ok in results if ok), start)


@_verb("answer", "Answer cards",
       "Answers each card through the scheduler as if the button (`ease` 1-4: "
       "again/hard/good/easy) had been pressed in the reviewer. Works on a "
       "card in any state - answering a suspended card unsuspends it. A "
       "missing card is skipped; `affected` counts the cards answered.")
def answer(body: AnswerRequest = Body(...)) -> SchedulingResult:
    start = time.perf_counter()
    results: List[bool] = answer_cards(
        [{"card_id": e.card_id, "ease": e.ease} for e in body.answers])
    return _result(sum(1 for ok in results if ok), start)


@_verb("set-values", "Set raw card columns",
       "Writes card columns as-is, with no validation beyond the column's "
       "type - the escape hatch AnkiConnect calls setSpecificValueOfCard. "
       "Scheduling and linkage columns (did, id, ivl, lapses, left, mod, nid, "
       "odid, odue, ord, queue, reps, type, usn) corrupt the card when "
       "written badly, so they require `force: true`.")
def set_values(body: SetCardValuesRequest = Body(...)) -> SchedulingResult:
    risky = sorted(set(body.values) & RISKY_CARD_COLUMNS)
    if risky and not body.force:
        raise ValidationError(
            f"columns {', '.join(risky)} need force=true to overwrite")
    start = time.perf_counter()
    try:
        set_card_values(body.card_id, body.values)
    except Exception as e:
        if type(e).__name__ == "NotFoundError":
            raise ResourceNotFoundError("card", body.card_id) from e
        raise
    return _result(1, start)


@router.post(
    "/v1/cards:batch",
    response_model=BatchResult,
    summary="Run several scheduling verbs as one undoable operation",
    description=(
        "Runs the listed scheduling verbs in order as a single undo entry "
        "(\"Card Batch\") - one Ctrl+Z in Anki reverts the whole batch, and "
        "the event stream sees one `op` carrying every card id involved. "
        "Each entry is `{\"op\": \"<verb>\", ...that verb's body}`, where "
        "`<verb>` is one of: " + ", ".join(sorted(BATCH_VERBS)) + ". "
        "Everything checkable is validated before any write; a backend error "
        "mid-run (rare) leaves the earlier steps applied with the undo "
        "history cleared - the batch is one undo entry, not a transaction. "
        "`answer`, `set-values` and `set-memory-state` are deliberately not "
        "batchable."
    ),
    tags=["Cards"],
    operation_id="cardsBatch",
)
@handle_mutation_errors("batch")
def batch(body: BatchRequest = Body(...)) -> BatchResult:
    start = time.perf_counter()
    if not body.operations:
        raise ValidationError("at least one operation is required")
    parsed = []
    for i, item in enumerate(body.operations):
        name = item.get("op")
        if name not in BATCH_VERBS:
            raise ValidationError(
                f"operation {i}: unknown op {name!r}; "
                f"expected one of {sorted(BATCH_VERBS)}")
        model = BATCH_VERBS[name][0]
        try:
            parsed.append((name, model.parse_obj(item)))
        except PydanticValidationError as e:
            raise ValidationError(f"operation {i} ({name}): {e}") from e
    result = batch_cards(parsed)
    return BatchResult(
        affected=result["affected"],
        results=result["results"],
        stats={"duration_ms": round((time.perf_counter() - start) * 1000, 3)},
    )

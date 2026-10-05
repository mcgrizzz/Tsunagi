from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, validator

from .notes import NoteField, unique_ids
from .wrappers import NULLABLE, RequestBody, coded, derived

# ----------------- Response Schemas -----------------


class FsrsMemoryState(RequestBody):
    """FSRS's per-card memory model. Null until the card has been reviewed."""
    stability: float = Field(description="FSRS memory stability, in days.")
    difficulty: float = Field(description="How hard the card is, from 1 (easiest) to 10 (hardest).")


# A card's queue, by name: also in the cards.answered event.
QUEUES = {0: "new", 1: "learning", 2: "review", 3: "day_learning", 4: "preview",
          -1: "suspended", -2: "sibling_buried", -3: "manually_buried"}


class CardInfo(BaseModel):
    """
    A card row with human-readable names (Anki wire names as aliases).

    Everything here is a plain column read - no backend call - including the
    FSRS state. FSRS is Anki's default scheduler, so it is part of a card,
    not an extra.
    """
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    id: int = Field(description="Card id: its creation time in epoch milliseconds.")
    note_id: int = Field(alias="nid", description="Id of the note the card belongs to.")
    deck_id: int = Field(alias="did", description=(
        "Id of the deck the card is in now; a filtered deck's id while it sits in one."))
    original_deck_id: int = Field(0, alias="odid", description=(
        "Home deck id while the card is in a filtered deck; 0 otherwise."))
    ord: int = Field(0, description=(
        "Which template made the card, from 0; on a cloze note type, the cloze number minus 1."))
    mod: int = Field(0, description="Last modified, Unix seconds.")
    usn: int = Field(0, description="Update sequence number for syncing; -1 means changed since the last sync.")

    type: int = Field(0, description="The card's scheduling stage.",
                      **coded({0: "new", 1: "learning", 2: "review", 3: "relearning"}))
    queue: int = Field(0, description=(
        "The queue the card is in, which also says what `due` means: new (a position), learning "
        "and preview (epoch seconds), review and day_learning (a day number; day_learning is "
        "learning whose next step is on a later day); suspended, sibling_buried (buried "
        "automatically with a sibling) and manually_buried keep `due` from before."),
        **coded(QUEUES))
    # Raw on purpose. `due` means a different thing per queue - a position for
    # new cards, a day number for review cards, epoch seconds while learning -
    # so normalizing it would destroy information the client needs.
    due: int = Field(0, description=(
        "Anki's stored value, not days from today. New: position in the new queue. Learning: "
        "epoch seconds. Review: days since the collection was created. For cards due on a day, "
        "search `prop:due=1` (days from today: 0 today, -1 yesterday); `is:due` for cards due now."))
    original_due: int = Field(0, alias="odue", description=(
        "The card's due value in its home deck while it is in a filtered deck; 0 otherwise."))
    interval: int = Field(0, alias="ivl", description="Current interval in days; 0 for new and learning cards.")
    factor: int = Field(0, description=(
        "SM-2 ease in permille (2500 = 250%); 0 until the card graduates. FSRS doesn't use it."))
    reps: int = Field(0, description="How many times the card has been answered.")
    lapses: int = Field(0, description="How many times the card was forgotten (Again on a review card).")
    left: int = Field(0, description=(
        "Learning steps the card still has to pass before it graduates, the current one included; "
        "only meaningful while the card is learning or relearning."))

    original_position: Optional[int] = Field(None, description=(
        "Where the card was in the new queue before it was first studied; null if Anki didn't "
        "record it."), **NULLABLE)
    # Anki's own scratch space, a JSON string. Passed through unparsed -
    # scheduling add-ons keep their state here and it is not ours to reshape.
    custom_data: str = Field("", description=(
        'A JSON object string that custom scheduling code stores on the card; "" when none.'))

    # FSRS. Null on a card FSRS has not seen (never reviewed, or SM-2 only).
    memory_state: Optional[FsrsMemoryState] = Field(None, description=(
        "FSRS memory state; null until FSRS has scheduled the card."), **NULLABLE)
    desired_retention: Optional[float] = Field(None, description=(
        "Desired retention (0-1) in effect when the card was last scheduled; null if none recorded."),
        **NULLABLE)
    decay: Optional[float] = Field(None, description=(
        "FSRS decay parameter used for the card; null until FSRS has scheduled it."), **NULLABLE)
    last_review_time: Optional[int] = Field(None, description=(
        "When the card was last answered, Unix seconds; null if never, or before Anki recorded it."),
        **NULLABLE)

    # Derived from the columns above - free, so always present.
    suspended: bool = Field(False, description="True when the card is suspended (queue -1).")
    buried: bool = Field(False, description=(
        "True when the card is buried, by a sibling or by the user (queue -2 or -3)."))
    flag: int = Field(0, description="The card's flag colour.", **coded({
        0: "none", 1: "red", 2: "orange", 3: "green", 4: "blue", 5: "pink", 6: "turquoise", 7: "purple"}))
    deck_name: str = Field("", description='Full name of the deck in deck_id, with "::" between levels.',
                           **derived("decks"))

    # Need the note or the template renderer, so only built when asked for.
    model_name: Optional[str] = Field(None, description="Name of the card's note type.", **derived("models"))
    css: Optional[str] = Field(None, description="The note type's styling.", **derived("models"))
    fields: Optional[List[NoteField]] = Field(None, description="The note's fields, in note type order.",
                                              **derived("notes", "models"))
    question: Optional[str] = Field(None, description="The card's front, rendered as HTML.",
                                    **derived("notes", "models", "decks"))
    answer: Optional[str] = Field(None, description="The card's back, rendered as HTML.",
                                  **derived("notes", "models", "decks"))
    next_reviews: Optional[List[str]] = Field(None, description=(
        'Next interval for each answer button, Again to Easy, as Anki shows them (e.g. "10m", "4d"); '
        "null if Anki couldn't work them out."), **NULLABLE)
    # FSRS recall probability right now, via col.card_stats_data - a backend
    # call per card, so want-gated like the renderer fields.
    retrievability: Optional[float] = Field(None, description=(
        "FSRS estimate (0-1) that the card would be recalled now; null if FSRS hasn't scored it."),
        **NULLABLE)


# ----------------- Scheduling verb requests -----------------


class CardIds(RequestBody):
    """Base body for the batch scheduling verbs."""
    class Config:
        allow_population_by_field_name = True

    card_ids: List[int] = Field(
        alias="cardIds",
        description="A card id sent twice counts once; a missing card is skipped.")

    _unique = validator("card_ids", allow_reuse=True)(unique_ids)


class ForgetRequest(CardIds):
    # Anki's own defaults. AnkiConnect's forgetCards passes restore_position
    # True instead; that difference lives in the compat layer, not here.
    restore_position: bool = Field(alias="restorePosition", default=False)
    reset_counts: bool = Field(alias="resetCounts", default=False)


class SetDueDateRequest(CardIds):
    # "5" (due in 5 days) or "5-7" (a random day in that range). Anki parses it.
    days: str
    config_key: Optional[str] = Field(alias="configKey", default=None)


class ChangeDeckRequest(CardIds):
    deck_id: Optional[int] = Field(alias="deckId", default=None)
    deck_name: Optional[str] = Field(alias="deckName", default=None)


class RepositionRequest(CardIds):
    starting_from: int = Field(alias="startingFrom", default=0)
    step_size: int = Field(alias="stepSize", default=1)
    randomize: bool = False
    shift_existing: bool = Field(alias="shiftExisting", default=False)


class SetFlagRequest(CardIds):
    # 0 clears the flag; 1-7 are Anki's colours.
    flag: int = Field(ge=0, le=7)


class EaseEntry(RequestBody):
    id: int
    # Anki stores ease x10 as an integer: 250% is 2500.
    factor: int


class SetEaseRequest(RequestBody):
    cards: List[EaseEntry]


class MemoryStateEntry(RequestBody):
    """
    Per-card FSRS state write. An omitted field is left unchanged; an explicit
    null clears it. The route preserves that distinction by handing the
    adapter dicts built with exclude_unset.
    """
    id: int
    memory_state: Optional[FsrsMemoryState] = None
    desired_retention: Optional[float] = None
    decay: Optional[float] = None


class SetMemoryStateRequest(RequestBody):
    cards: List[MemoryStateEntry]


class AnswerEntry(RequestBody):
    class Config:
        allow_population_by_field_name = True

    card_id: int = Field(alias="cardId")
    # The answer button: 1 again, 2 hard, 3 good, 4 easy.
    ease: int = Field(ge=1, le=4)


class AnswerRequest(RequestBody):
    answers: List[AnswerEntry]


class SetCardValuesRequest(RequestBody):
    class Config:
        allow_population_by_field_name = True

    card_id: int = Field(alias="cardId")
    # Raw card columns, written as-is: the route lists them; values are integers.
    values: dict
    # Scheduling/linkage columns are refused unless this is true.
    force: bool = False


class BatchRequest(RequestBody):
    # Entries stay raw dicts here: each is validated against ITS verb's
    # request model by the route, keyed on "op".
    operations: List[dict]


class BatchOpResult(BaseModel):
    op: str
    affected: int


class BatchResult(BaseModel):
    affected: int
    results: List[BatchOpResult]
    stats: dict

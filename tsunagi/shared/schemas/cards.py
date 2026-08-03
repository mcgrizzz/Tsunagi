from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .notes import NoteField

# ----------------- Response Schemas -----------------


class FsrsMemoryState(BaseModel):
    """FSRS's per-card memory model. Null until the card has been reviewed."""
    stability: float
    difficulty: float


class CardInfo(BaseModel):
    """
    A card row with human-readable names (Anki wire names as aliases).

    Everything here is a plain column read - no backend call - including the
    FSRS state. FSRS shipped in 23.10 (our floor) and has been the default
    scheduler since 24.11, so it is part of a card, not an extra.
    """
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    id: int
    note_id: int = Field(alias="nid")
    deck_id: int = Field(alias="did")
    # Non-zero only while the card sits in a filtered deck (its home deck).
    original_deck_id: int = Field(alias="odid", default=0)
    ord: int = 0
    mod: int = 0
    usn: int = 0

    type: int = 0
    queue: int = 0
    # Raw on purpose. `due` means a different thing per queue - a position for
    # new cards, a day number for review cards, epoch seconds while learning -
    # so normalizing it would destroy information the client needs.
    due: int = 0
    original_due: int = Field(alias="odue", default=0)
    interval: int = Field(alias="ivl", default=0)
    factor: int = 0
    reps: int = 0
    lapses: int = 0
    left: int = 0
    flags: int = 0

    # Set while the card is in a filtered deck or has been repositioned.
    original_position: Optional[int] = None
    # Anki's own scratch space, a JSON string. Passed through unparsed -
    # scheduling add-ons keep their state here and it is not ours to reshape.
    custom_data: str = ""

    # FSRS. Null on a card FSRS has not seen (never reviewed, or SM-2 only).
    memory_state: Optional[FsrsMemoryState] = None
    desired_retention: Optional[float] = None
    decay: Optional[float] = None
    last_review_time: Optional[int] = None

    # Derived from the columns above - free, so always present.
    suspended: bool = False
    buried: bool = False
    flag: int = 0
    deck_name: str = ""

    # Need the note or the template renderer, so only built when asked for.
    model_name: Optional[str] = None
    css: Optional[str] = None
    fields: Optional[List[NoteField]] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    next_reviews: Optional[List[str]] = None


# ----------------- Scheduling verb requests -----------------


class CardIds(BaseModel):
    """Base body for the batch scheduling verbs."""
    class Config:
        allow_population_by_field_name = True

    card_ids: List[int] = Field(alias="cardIds")


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


class EaseEntry(BaseModel):
    id: int
    # Anki stores ease x10 as an integer: 250% is 2500.
    factor: int


class SetEaseRequest(BaseModel):
    cards: List[EaseEntry]


# ----------------- Verb response -----------------


class SchedulingResult(BaseModel):
    affected: int
    stats: dict

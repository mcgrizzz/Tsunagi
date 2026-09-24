from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

# ----------------- Response Schemas -----------------


class DeckInfo(BaseModel):
    """Schema11 deck dict with human-readable names (Anki wire names as aliases)."""
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    id: int
    name: str
    mod: int = 0
    usn: int = 0

    description: str = Field(alias="desc", default="")
    dynamic: int = Field(alias="dyn", default=0)
    # Filtered (dynamic) decks have no "conf" key
    config_id: Optional[int] = Field(alias="conf", default=None)

    collapsed: bool = False
    browser_collapsed: bool = Field(alias="browserCollapsed", default=False)

    # [day, amount] pairs
    learn_today: List[int] = Field(alias="lrnToday", default_factory=lambda: [0, 0])
    review_today: List[int] = Field(alias="revToday", default_factory=lambda: [0, 0])
    new_today: List[int] = Field(alias="newToday", default_factory=lambda: [0, 0])
    time_today: List[int] = Field(alias="timeToday", default_factory=lambda: [0, 0])

    extend_new: int = Field(alias="extendNew", default=0)
    extend_rev: int = Field(alias="extendRev", default=0)

    # Newer schema11 keys (per-deck limits); absent on older decks
    review_limit: Optional[int] = Field(alias="reviewLimit", default=None)
    new_limit: Optional[int] = Field(alias="newLimit", default=None)

    # Per-deck FSRS desired retention override. Read from the deck protobuf,
    # not the schema11 dict - the dict carries it as a truncated integer
    # percent - so it costs a backend call per deck and is only fetched when
    # selected. Null when unset or on filtered decks.
    desired_retention: Optional[float] = None

    # Due counts. Not stored on the deck - they come from the scheduler's due
    # tree, so they're only computed when select/where asks for one of them.
    #
    # Anki's own asymmetry, passed through rather than papered over: the three
    # due counts INCLUDE subdecks (a parent shows what its children owe, which
    # is what the deck list displays), while total_in_deck counts only the
    # cards sitting directly in that deck. So a parent with all its cards in
    # children reports new_count=2, total_in_deck=0.
    new_count: Optional[int] = None
    learn_count: Optional[int] = None
    review_count: Optional[int] = None
    total_in_deck: Optional[int] = None


# ----------------- Request Schemas -----------------


class DeckCreate(BaseModel):
    """Schema for creating a deck ("::" nesting allowed)"""
    class Config:
        allow_population_by_field_name = True

    name: str
    description: Optional[str] = Field(alias="desc", default=None)


class DeckPatch(BaseModel):
    """Schema for patching a deck - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    description: Optional[str] = Field(alias="desc", default=None)
    collapsed: Optional[bool] = None
    browser_collapsed: Optional[bool] = Field(alias="browserCollapsed", default=None)
    config_id: Optional[int] = Field(alias="conf", default=None)
    # Per-deck FSRS retention override; explicit null clears it.
    desired_retention: Optional[float] = Field(alias="desiredRetention", default=None)

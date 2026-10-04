from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .wrappers import NULLABLE, RequestBody, coded

# ----------------- Response Schemas -----------------


class DeckInfo(BaseModel):
    """Schema11 deck dict with human-readable names (Anki wire names as aliases)."""
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    id: int = Field(description="Deck id.")
    name: str = Field(description='Full deck name, with "::" between levels.')
    mod: int = Field(0, description="Last modified, Unix seconds.")
    usn: int = Field(0, description="Update sequence number for syncing; -1 means changed since the last sync.")

    description: str = Field("", alias="desc", description="The deck's description, shown on its overview screen.")
    dynamic: int = Field(0, alias="dyn", description="Whether this is a filtered deck.",
                         **coded({0: "normal", 1: "filtered"}))
    # Filtered (dynamic) decks have no "conf" key
    config_id: Optional[int] = Field(None, alias="conf", description=(
        "Id of the deck's options preset (see /v1/deck-configs); null for filtered decks."), **NULLABLE)

    collapsed: bool = Field(False, description="Whether the deck's subdecks are collapsed in the deck list.")
    browser_collapsed: bool = Field(False, alias="browserCollapsed", description=(
        "Whether the deck's subdecks are collapsed in the browser sidebar."))

    learn_today: List[int] = Field(alias="lrnToday", default_factory=lambda: [0, 0], description=(
        "[day, count]: learning cards studied on that day; day counts from the collection's creation."))
    review_today: List[int] = Field(alias="revToday", default_factory=lambda: [0, 0], description=(
        "[day, count]: review cards studied on that day; count drops when today's limit is extended."))
    new_today: List[int] = Field(alias="newToday", default_factory=lambda: [0, 0], description=(
        "[day, count]: new cards studied on that day; count drops when today's limit is extended."))
    time_today: List[int] = Field(alias="timeToday", default_factory=lambda: [0, 0], description=(
        "[day, milliseconds]: time spent studying the deck on that day."))

    extend_new: int = Field(0, alias="extendNew", description=(
        "Last amount entered in Custom Study's \"increase today's new card limit\"; 0 for filtered decks."))
    extend_rev: int = Field(0, alias="extendRev", description=(
        "Last amount entered in Custom Study's \"increase today's review limit\"; 0 for filtered decks."))

    # Newer schema11 keys: the deck's own limits, null when it has none
    review_limit: Optional[int] = Field(None, alias="reviewLimit", description=(
        "This deck's own daily review limit, overriding its preset; null when it has none."), **NULLABLE)
    new_limit: Optional[int] = Field(None, alias="newLimit", description=(
        "This deck's own daily new card limit, overriding its preset; null when it has none."), **NULLABLE)

    # Per-deck FSRS desired retention override. Read from the deck protobuf,
    # not the schema11 dict - the dict carries it as a truncated integer
    # percent - so it costs a backend call per deck and is only fetched when
    # selected. Null when unset or on filtered decks.
    desired_retention: Optional[float] = Field(None, description=(
        "This deck's FSRS desired retention (0-1), overriding its preset; null when unset or filtered."),
        **NULLABLE)

    # Due counts. Not stored on the deck - they come from the scheduler's due
    # tree, so they're only computed when select/where asks for one of them.
    #
    # Anki's own asymmetry, passed through rather than papered over: the three
    # due counts INCLUDE subdecks (a parent shows what its children owe, which
    # is what the deck list displays), while total_in_deck counts only the
    # cards sitting directly in that deck. So a parent with all its cards in
    # children reports new_count=2, total_in_deck=0.
    new_count: Optional[int] = Field(None, description=(
        "New cards to study today, subdecks included, as the deck list shows them."))
    learn_count: Optional[int] = Field(None, description=(
        "Learning cards due today, subdecks included, as the deck list shows them."))
    review_count: Optional[int] = Field(None, description=(
        "Review cards due today, subdecks included, as the deck list shows them."))
    total_in_deck: Optional[int] = Field(None, description="Cards in this deck itself, not counting subdecks.")


# ----------------- Request Schemas -----------------


class DeckConfigRow(BaseModel):
    """
    A deck preset as Anki stores it: `id`, `name` and Anki's own settings,
    with Anki's names (`new`, `rev`, `lapse`, `desiredRetention`...), which
    vary with the Anki version. Sent back whole, so a read-modify-write keeps
    settings this API doesn't know.
    """
    class Config:
        extra = "allow"

    id: int = Field(description="Preset id; 1 is the Default preset.")
    name: str = Field(description="Preset name. Other keys are Anki's own settings, as Anki names them.")


class DeckCreate(RequestBody):
    """Schema for creating a deck ("::" nesting allowed)"""
    class Config:
        allow_population_by_field_name = True

    name: str
    description: Optional[str] = Field(alias="desc", default=None)


class DeckPatch(RequestBody):
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

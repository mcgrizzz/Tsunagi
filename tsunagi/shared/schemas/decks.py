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

"""Statistics (6.6), from the data behind Anki's Statistics screen."""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class MatureToday(BaseModel):
    reviews: int = Field(description="Reviews of mature cards (interval of 21 days or more).")
    correct: int = Field(description="Of those, answered Hard, Good or Easy.")


class TodayStatistics(BaseModel):
    """Anki's day so far, as the Today section of its Statistics screen counts it."""
    reviews: int = Field(description="Cards answered.")
    duration_ms: int = Field(description="Time spent answering, in milliseconds.")
    correct: int = Field(description="Answered Hard, Good or Easy.")
    learn: int = Field(description="Answers to cards in learning.")
    review: int = Field(description="Answers to cards in review.")
    relearn: int = Field(description="Answers to cards in relearning.")
    filtered: int = Field(description="Answers in filtered decks, ahead of schedule.")
    mature: MatureToday
    stats: Dict[str, Any] = Field(default_factory=dict)


class ReviewDay(BaseModel):
    date: str = Field(description=(
        "The Anki day, as the date it started (days start at the \"Next day starts at\" hour)."))
    reviews: int
    duration_ms: int = Field(description="Time spent answering, in milliseconds.")
    learn: int = Field(description="Answers to cards in learning.")
    young: int = Field(description="Answers to review cards with an interval under 21 days.")
    mature: int = Field(description="Answers to review cards with an interval of 21 days or more.")
    relearn: int = Field(description="Answers to cards in relearning.")
    filtered: int = Field(description="Answers in filtered decks, ahead of schedule.")


class ReviewDays(BaseModel):
    items: List[ReviewDay] = Field(description="Days with reviews, newest first.")
    days_studied: int = Field(description="How many days in the range had reviews.")
    streak: int = Field(description=(
        "Days in a row with reviews, up to today; while today has none yet, up to yesterday. "
        "Counted within the range."))
    stats: Dict[str, Any] = Field(default_factory=dict)

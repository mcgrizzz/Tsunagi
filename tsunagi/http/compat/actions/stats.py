"""
AnkiConnect compatibility handlers for review statistics.

Every one is a translation over adapters/anki/reviews.py - the same module
GET /v1/reviews reads through. Two shapes to be careful with, because clients
depend on both: cardReviews returns ARRAYS in a fixed column order, while
getReviewsOfCards returns a map of card id to objects.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.reviews import (
    card_review_map,
    collection_stats_html,
    insert_reviews,
    latest_review_id,
    reviews_by_day,
    reviews_of_deck,
    reviews_today,
)
from ..registry import registry


class DeckParams(BaseModel):
    deck: str


class CardReviewsParams(BaseModel):
    deck: str
    startID: int = 0


class GetReviewsOfCardsParams(BaseModel):
    cards: List[int]


class CollectionStatsParams(BaseModel):
    wholeCollection: bool = True


@registry.register("getNumCardsReviewedToday")
def ac_getNumCardsReviewedToday(params: Optional[Dict[str, Any]] = None) -> int:
    return reviews_today()


@registry.register("getNumCardsReviewedByDay")
def ac_getNumCardsReviewedByDay(params: Optional[Dict[str, Any]] = None) -> List[List[Any]]:
    return reviews_by_day()


@registry.register("getCollectionStatsHTML", params=CollectionStatsParams)
def ac_getCollectionStatsHTML(p: CollectionStatsParams) -> str:
    return collection_stats_html(p.wholeCollection)


@registry.register("cardReviews", params=CardReviewsParams)
def ac_cardReviews(p: CardReviewsParams) -> List[List[Any]]:
    return reviews_of_deck(p.deck, p.startID)


@registry.register("getLatestReviewID", params=DeckParams)
def ac_getLatestReviewID(p: DeckParams) -> int:
    return latest_review_id(p.deck)


@registry.register("getReviewsOfCards", params=GetReviewsOfCardsParams)
def ac_getReviewsOfCards(p: GetReviewsOfCardsParams) -> Dict[int, List[Dict[str, Any]]]:
    return card_review_map(p.cards)


class InsertReviewsParams(BaseModel):
    # 9-tuples in canonical's order: [reviewTime, cardID, usn, buttonPressed,
    # newInterval, previousInterval, newFactor, reviewDuration, reviewType].
    reviews: List[List[int]]


@registry.register("insertReviews", params=InsertReviewsParams)
def ac_insertReviews(p: InsertReviewsParams) -> None:
    """
    Returns null, like canonical. Under the hood the rows go in parameterized
    and transactional instead of string-interpolated, so a malformed row's
    error message is ours rather than sqlite's - but a malformed row is an
    error either way, and good rows produce identical revlog entries.
    """
    insert_reviews(p.reviews)

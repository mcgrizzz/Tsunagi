from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, validator

from .wrappers import RequestBody, coded

# ----------------- Response Schemas -----------------

# revlog.type. Anki records why a row was written, which is the difference
# between a real answer and a bookkeeping entry.
REVIEW_LEARN = 0
REVIEW_REVIEW = 1
REVIEW_RELEARN = 2
REVIEW_FILTERED = 3
REVIEW_MANUAL = 4
REVIEW_RESCHEDULED = 5


class ReviewInfo(RequestBody):
    """
    One revlog row, with human-readable names (Anki wire names as aliases).
    Not every row is an answer: manual reschedules (type 4) and FSRS
    reschedules (type 5) are rows too, with rating 0.

    The revlog is append-only history: every row is a fact about a review that
    happened, so it is normally the scheduler's to write. The one exception is
    POST /v1/reviews (AnkiConnect's insertReviews), which inserts rows for
    history imports - and reuses this model, so rows round-trip read<->write.
    """
    class Config:
        allow_population_by_field_name = True

    # Epoch milliseconds of the review, and the row's identity. Also the
    # keyset pagination key, which is why pages come back in review order.
    id: int = Field(description="When the review happened, epoch milliseconds; also the row's id.")
    card_id: int = Field(alias="cid", description="Id of the card reviewed.")
    usn: int = Field(0, description="Update sequence number for syncing; -1 means not yet synced.")
    rating: int = Field(0, alias="ease", description=(
        "Answer button pressed: again, hard, good or easy (on old v1 learning rows, 2 was Good and "
        "3 Easy). none (0) when the row records a reschedule rather than an answer: a set due "
        "date, a reset, or an FSRS reschedule (type manual or rescheduled)."),
        **coded({0: "none", 1: "again", 2: "hard", 3: "good", 4: "easy"}))
    # Both are in days when positive and in NEGATIVE SECONDS when the card is
    # in learning - Anki's encoding, passed through rather than normalized away.
    interval: int = Field(0, alias="ivl", description=(
        "Interval after the review: days if positive, seconds if negative (learning)."))
    last_interval: int = Field(0, alias="lastIvl", description=(
        "Interval before the review, in the same units as interval."))
    ease_factor: int = Field(0, alias="factor", description=(
        "SM-2: ease after the review, permille (2500 = 250%). FSRS: difficulty mapped to 100-1100. "
        "0 if neither."))
    duration_ms: int = Field(0, alias="time", description="Time spent answering, milliseconds; 0 on reschedule rows.")
    type: int = Field(REVIEW_LEARN, description=(
        "What kind of entry the row is: learning, review, relearning, filtered (an early review or "
        "cram in a filtered deck; cram rows have ease_factor 0), manual (a set due date or a reset; "
        "reset rows have ease_factor 0), or rescheduled (by FSRS when deck options changed)."),
        **coded({REVIEW_LEARN: "learning", REVIEW_REVIEW: "review", REVIEW_RELEARN: "relearning",
                 REVIEW_FILTERED: "filtered", REVIEW_MANUAL: "manual", REVIEW_RESCHEDULED: "rescheduled"}))

    @validator("*", allow_reuse=True)  # reload_addon defines it again
    def _fits_a_column(cls, value: int) -> int:
        # An SQLite integer column holds 64 bits. A larger number would be
        # stored as a float, or refused for the id.
        if not -(2 ** 63) <= value < 2 ** 63:
            raise ValueError("must fit in 64 bits")
        return value


# ----------------- Request Schemas -----------------


class InsertReviewsRequest(RequestBody):
    # Same shape GET /v1/reviews returns (aliases accepted), so a row read
    # from one collection can be posted into another unchanged. Only `id` and
    # `card_id` are required; everything else has the column's natural default.
    reviews: List[ReviewInfo]


class InsertReviewsResult(BaseModel):
    inserted: int
    stats: dict

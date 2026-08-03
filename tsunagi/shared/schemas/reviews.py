from __future__ import annotations

from pydantic import BaseModel, Field

# ----------------- Response Schemas -----------------

# revlog.type. Anki records why a row was written, which is the difference
# between a real answer and a bookkeeping entry.
REVIEW_LEARN = 0
REVIEW_REVIEW = 1
REVIEW_RELEARN = 2
REVIEW_FILTERED = 3
REVIEW_MANUAL = 4
REVIEW_RESCHEDULED = 5


class ReviewInfo(BaseModel):
    """
    One revlog row, with human-readable names (Anki wire names as aliases).

    The revlog is append-only history: every row is a fact about a review that
    happened, so this resource is read-only. Writing rows directly is how
    AnkiConnect's insertReviews works, and it bypasses the scheduler - which is
    why that action is out of scope.
    """
    class Config:
        extra = "ignore"
        allow_population_by_field_name = True

    # Epoch milliseconds of the review, and the row's identity. Also the
    # keyset pagination key, which is why pages come back in review order.
    id: int
    card_id: int = Field(alias="cid")
    usn: int = 0
    # Which answer button was pressed (1-4). Zero for a manual reschedule,
    # where nothing was actually answered.
    ease: int = 0
    # Interval AFTER this review, and the one before it. Both are in days when
    # positive and in NEGATIVE SECONDS when the card is in learning - Anki's
    # encoding, passed through rather than normalized away.
    interval: int = Field(alias="ivl", default=0)
    last_interval: int = Field(alias="lastIvl", default=0)
    # SM-2 ease factor, permille (2500 = 250%). Zero on FSRS-scheduled reviews.
    factor: int = 0
    # How long the answer took, in milliseconds.
    time_ms: int = Field(alias="time", default=0)
    type: int = REVIEW_LEARN

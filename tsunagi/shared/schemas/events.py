"""
The messages of GET /v1/events (6.105). Server-Sent Events have no place in
an OpenAPI schema, so these are added to the description's components and
named per event type in the stream's `x-events` (tsunagi/app.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .cards import QUEUES, FsrsMemoryState
from .wrappers import NULLABLE, coded


class _Message(BaseModel):
    class Config:
        extra = "forbid"   # tests check the stream sends exactly this


class _Live(_Message):
    """A numbered message of the session (not ready, gap, access.changed or close)."""
    type: str = Field(description="The message's name, also its SSE `event:`.")
    seq: int = Field(description="Its number in the session; the SSE `id:` is `<session_id>:<seq>`.")
    session_id: str = Field(description="The server session; a new one after a restart or profile switch.")
    ts: int = Field(description="When it was sent, Unix milliseconds.")


class _Change(_Live):
    by: Optional[Literal["ui", "api"]] = Field(None, description=(
        "api: made through either API; ui: made in Anki; null when unknown"), **NULLABLE)
    app: Optional[str] = Field(None, description="For by api: the app that made it; null otherwise", **NULLABLE)
    anki: Optional[Dict[str, Any]] = Field(None, description="Anki's own description of the change, for debugging; "
                                                             "don't rely on it", **NULLABLE)


class RowsChanged(_Change):
    """`<resource>.created`, `.updated`, `.deleted`; `reviews.created`."""
    ids: List[int] = Field(description="The ids of the rows that changed.")


class RowsStale(_Change):
    """`<resource>.stale`: rows changed, but which isn't known; reload what you show."""
    reason: Literal["collection", "details_unavailable"] = Field(description=(
        "collection: anything may have changed (a sync, a full reset); details_unavailable: "
        "Anki didn't say which rows (an undo, more than 1,000 ids)"))


class DeckCounts(_Message):
    deck_id: int = Field(description="The deck's id.")
    new_count: int
    learn_count: int
    review_count: int
    total_in_deck: int


class DecksCounts(_Live):
    """`decks.counts`: decks whose due counts changed, as /v1/decks rows count them."""
    decks: List[DeckCounts]


class CardAnswered(_Change):
    """`cards.answered`: a card was answered, in Anki or through either API; its new state."""
    card_id: int
    rating: int = Field(description="The answer button.", **coded({1: "again", 2: "hard", 3: "good", 4: "easy"}))
    interval: int = Field(description="The card's new interval, days.")
    due: int = Field(description="The card's new due value (see /v1/cards).")
    queue: int = Field(description="The card's new queue.", **coded(QUEUES))
    memory_state: Optional[FsrsMemoryState] = Field(description="FSRS memory state; null for cards FSRS hasn't scheduled",
                                                    **NULLABLE)


class SyncEvent(_Live):
    """`sync`: a sync started or finished."""
    phase: Literal["started", "finished"]


class Ready(_Message):
    """`ready`: connected; load the data you show now."""
    type: Literal["ready"]
    session_id: str
    after_seq: int = Field(description="Messages after this number come on this connection.")
    ts: int
    resources: List[str] = Field(description="The resources this stream carries: those asked for that the app may read.")
    heartbeat_ms: int = Field(description="How often a heartbeat comment is sent; a few missed means a dead connection.")


class Gap(_Message):
    """`gap`: this connection fell behind and messages were lost; reload what you show."""
    type: Literal["gap"]
    after_seq: int
    session_id: str
    ts: int
    reason: Literal["lagged"]
    discarded: int = Field(description="How many messages were lost.")


class AccessChanged(_Message):
    """`access.changed`: fetch GET /v1/capabilities again."""
    type: Literal["access.changed"]
    ts: int


class Close(_Message):
    """`close`: the server ended the stream (the last message)."""
    reason: Literal["profile_closed", "shutdown", "auth", "timeout", "max_events"]

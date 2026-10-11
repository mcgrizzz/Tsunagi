"""
Statistics (6.6) from Anki's own graphs data: the backend call its Statistics
screen makes, so the numbers are Anki's. `search` keeps the reviews of the
cards it finds; the empty search is the whole collection.
"""
import time
from typing import Any, Dict, List, Optional, Set

from anki.collection import Collection

from ..ops import as_query_op


def _total(counts: Any) -> int:
    """One day's answers (or milliseconds), every kind together."""
    return counts.learn + counts.relearn + counts.young + counts.mature + counts.filtered


def _graphs(col: Collection, search: str) -> Any:
    try:
        return col._backend.graphs(search=search, days=0)  # 0: all history
    except Exception as e:
        # A malformed search is the client's mistake, a 400, as in find_card_ids.
        if type(e).__name__ in ("SearchError", "InvalidInput"):
            raise ValueError(f"Invalid Anki search: {e}") from e
        raise


def _streak(reviews: Any) -> int:
    """Days in a row with reviews up to today; while today has none yet, up to yesterday."""
    studied = {offset for offset in reviews.count if _total(reviews.count[offset])}
    day = 0 if 0 in studied else -1
    streak = 0
    while day in studied:
        streak, day = streak + 1, day - 1
    return streak


@as_query_op
def today_statistics(col: Collection, search: str) -> Dict[str, Any]:
    graphs = _graphs(col, search)
    today = graphs.today
    return {
        "reviews": today.answer_count,
        "duration_ms": today.answer_millis,
        "correct": today.correct_count,
        "learn": today.learn_count,
        "review": today.review_count,
        "relearn": today.relearn_count,
        "filtered": today.early_review_count,
        "mature": {"reviews": today.mature_count, "correct": today.mature_correct},
        "streak": _streak(graphs.reviews),
    }


def _date(col: Collection, offset: int) -> str:
    """Day `offset` (0 today, -1 yesterday) as the date it started."""
    start = col.sched.day_cutoff - 86400 + offset * 86400
    return time.strftime("%Y-%m-%d", time.localtime(start))


@as_query_op
def review_days(col: Collection, search: str, wants: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """One row per Anki day with reviews, for GET /v1/review-days."""
    reviews = _graphs(col, search).reviews
    return [{
        "date": _date(col, offset),
        "reviews": _total(count),
        "duration_ms": _total(reviews.time[offset]),
        "learn": count.learn, "young": count.young, "mature": count.mature,
        "relearn": count.relearn, "filtered": count.filtered,
    } for offset, count in reviews.count.items() if _total(count)]

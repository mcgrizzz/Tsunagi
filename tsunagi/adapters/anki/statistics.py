"""
Statistics (6.6) from Anki's own graphs data: the backend call its Statistics
screen makes, so the numbers are Anki's. `search` keeps the reviews of the
cards it finds (empty: the whole collection); `days` counts back from today,
0 for all history.
"""
import time
from typing import Any, Dict

from anki.collection import Collection

from ..ops import as_query_op


def _total(counts: Any) -> int:
    """One day's answers (or milliseconds), every kind together."""
    return counts.learn + counts.relearn + counts.young + counts.mature + counts.filtered


def _graphs(col: Collection, search: str, days: int) -> Any:
    return col._backend.graphs(search=search, days=days)


@as_query_op
def today_statistics(col: Collection, search: str) -> Dict[str, Any]:
    today = _graphs(col, search, 1).today
    return {
        "reviews": today.answer_count,
        "seconds": round(today.answer_millis / 1000),
        "correct": today.correct_count,
        "learn": today.learn_count,
        "review": today.review_count,
        "relearn": today.relearn_count,
        "filtered": today.early_review_count,
        "mature": {"reviews": today.mature_count, "correct": today.mature_correct},
    }


def _date(col: Collection, offset: int) -> str:
    """Day `offset` (0 today, -1 yesterday) as the date it started."""
    start = col.sched.day_cutoff - 86400 + offset * 86400
    return time.strftime("%Y-%m-%d", time.localtime(start))


@as_query_op
def review_days(col: Collection, search: str, days: int) -> Dict[str, Any]:
    reviews = _graphs(col, search, days).reviews
    items = []
    for offset in sorted(reviews.count, reverse=True):
        count = reviews.count[offset]
        if not _total(count):
            continue
        items.append({
            "date": _date(col, offset),
            "reviews": _total(count),
            "seconds": round(_total(reviews.time[offset]) / 1000),
            "learn": count.learn, "young": count.young, "mature": count.mature,
            "relearn": count.relearn, "filtered": count.filtered,
        })
    studied = {offset for offset in reviews.count if _total(reviews.count[offset])}
    # While today has none yet, the run up to yesterday still counts.
    day = 0 if 0 in studied else -1
    streak = 0
    while day in studied:
        streak, day = streak + 1, day - 1
    return {"items": items, "days_studied": len(items), "streak": streak}

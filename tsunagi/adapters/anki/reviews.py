"""
Review history (the revlog).

Reads, plus one write: insert_reviews, AnkiConnect's insertReviews. The
scheduler is normally the only thing that appends to the revlog, and inserting
rows behind its back discards the undo history and cached study queues (Anki's
own dbproxy behaviour) - the write exists for history imports, not for
recording reviews.
"""
from typing import Any, Dict, List, Optional, Sequence, Set

from anki.collection import Collection

from ...shared.schemas.reviews import ReviewInfo
from ..ops import as_collection_op, as_query_op

# Column order is fixed once here so every query below builds the same row.
COLUMNS = ("id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type")
_SELECT = "select " + ", ".join(COLUMNS) + " from revlog"


def _rows(col: Collection, where: str = "", *args: Any) -> List[ReviewInfo]:
    sql = _SELECT + (f" where {where}" if where else "") + " order by id"
    return [ReviewInfo.parse_obj(dict(zip(COLUMNS, r)))
            for r in col.db.all(sql, *args)]


def _in_clause(values: Sequence[int]) -> str:
    # Ids are ints we produced, so interpolation is safe here and avoids
    # SQLite's 999-variable ceiling that getReviewsOfCards has to batch around.
    return "(" + ",".join(str(int(v)) for v in values) + ")"


@as_query_op
def all_review_ids(col: Collection) -> List[int]:
    """
    Every revlog id, in review order.

    Ids only, deliberately: a mature collection has hundreds of thousands of
    reviews, and the planner hydrates one page of them at a time. Reading a
    single integer column is what keeps a bare listing cheap.
    """
    return [int(i) for i in col.db.list("select id from revlog order by id")]


@as_query_op
def page_review_ids(col: Collection, after_id: Optional[int], limit: int) -> List[int]:
    """
    The next `limit` revlog ids after `after_id` (None = from the start),
    ascending. The keyset page for GET /v1/reviews: the id column is the
    primary key, so this is an index walk - a bare listing never materializes
    the whole revlog again.
    """
    if after_id is None:
        return [int(i) for i in col.db.list(
            "select id from revlog order by id limit ?", int(limit))]
    return [int(i) for i in col.db.list(
        "select id from revlog where id > ? order by id limit ?",
        int(after_id), int(limit))]


@as_query_op
def get_reviews_by_ids(col: Collection, ids: Sequence[int],
                       wants: Optional[Set[str]] = None) -> List[ReviewInfo]:
    if not ids:
        return []
    return _rows(col, f"id in {_in_clause(ids)}")


@as_query_op
def get_reviews_of_cards(col: Collection, card_ids: Sequence[int],
                         wants: Optional[Set[str]] = None) -> List[ReviewInfo]:
    if not card_ids:
        return []
    return _rows(col, f"cid in {_in_clause(card_ids)}")


@as_query_op
def find_review_ids(col: Collection, query: str) -> List[int]:
    """
    Revlog ids for the cards an Anki search matches.

    Anki's search language is about cards and notes, not reviews, so `search`
    means "reviews of the cards this matches" - which is what makes
    `?search=deck:JP` work and gives cardReviews a native home.

    An empty query is the whole collection, and routing that through
    find_cards() only to build a huge IN clause would be pure waste - read the
    revlog directly instead.
    """
    if not query or not query.strip():
        return [int(i) for i in col.db.list("select id from revlog order by id")]
    try:
        card_ids = col.find_cards(query)
    except Exception as e:
        # A malformed search is a client error; without this every typo'd
        # search string becomes a 500. Same guard as find_card_ids.
        if type(e).__name__ in ("SearchError", "InvalidInput"):
            raise ValueError(f"Invalid Anki search: {e}") from e
        raise
    if not card_ids:
        return []
    return [int(i) for i in col.db.list(
        f"select id from revlog where cid in {_in_clause(card_ids)} order by id")]


# ====================
# The one write
# ====================

@as_collection_op
def insert_reviews(col: Collection, rows: Sequence[Sequence[Any]]) -> int:
    """
    Insert raw revlog rows, each 9 ints in COLUMNS order (canonical's
    insertReviews tuple order). Parameterized and transactional where
    canonical string-interpolates a single INSERT - all rows land or none do,
    and the commit bumps the collection's modified time so the rows sync.
    """
    clean: List[List[int]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(COLUMNS):
            raise ValueError(
                f"review {i} must have {len(COLUMNS)} values in the order "
                f"({', '.join(COLUMNS)})")
        try:
            clean.append([int(v) for v in row])
        except (TypeError, ValueError) as e:
            raise ValueError(f"review {i} has a non-integer value: {e}") from e
    if not clean:
        return 0

    def _insert() -> None:
        sql = ("insert into revlog(" + ",".join(COLUMNS) + ") values ("
               + ",".join("?" * len(COLUMNS)) + ")")
        for row in clean:
            col.db.execute(sql, *row)

    col.db.transact(_insert)
    return len(clean)


# ====================
# Aggregates
# ====================

@as_query_op
def reviews_of_deck(col: Collection, deck_name: str,
                    after_id: int = 0) -> List[List[Any]]:
    """
    Rows for one deck, as arrays, for AnkiConnect's cardReviews.

    DEVIATION: canonical resolves the deck with `decks.id(name)`, which CREATES
    a missing deck - a write as a side effect of a read. We resolve by name and
    report nothing for a deck that doesn't exist.

    Scoped to cards whose `did` is exactly this deck, not its subdecks, which
    is canonical's behaviour.
    """
    deck = col.decks.by_name(deck_name)
    if deck is None:
        return []
    return [list(r) for r in col.db.all(
        _SELECT + " where id > ? and cid in (select id from cards where did = ?)"
        " order by id", int(after_id), int(deck["id"]))]


@as_query_op
def latest_review_id(col: Collection, deck_name: str) -> int:
    """Newest revlog id in a deck, or 0. Same by-name resolution as above."""
    deck = col.decks.by_name(deck_name)
    if deck is None:
        return 0
    return int(col.db.scalar(
        "select max(id) from revlog where cid in"
        " (select id from cards where did = ?)", int(deck["id"])) or 0)


@as_query_op
def reviews_today(col: Collection) -> int:
    """Reviews since the last day rollover, per the scheduler's own cutoff."""
    return int(col.db.scalar(
        "select count() from revlog where id > ?",
        (col.sched.day_cutoff - 86400) * 1000) or 0)


@as_query_op
def reviews_by_day(col: Collection) -> List[List[Any]]:
    """
    [[YYYY-MM-DD, count], ...] newest first, in the collection's local day.

    The offset shifts each row back by the rollover hour so a review answered
    at 2am belongs to the previous study day, matching Anki's own graphs.
    """
    import time as _time

    offset = int(_time.strftime("%H", _time.localtime(col.sched.day_cutoff))) * 3600
    return [list(r) for r in col.db.all(
        'select date(id/1000 - ?, "unixepoch", "localtime") as day, count()'
        " from revlog group by day order by day desc", offset)]


@as_query_op
def collection_stats_html(col: Collection, whole_collection: bool = True) -> str:
    """Anki's own stats report as HTML, for getCollectionStatsHTML."""
    stats = col.stats()
    stats.wholeCollection = bool(whole_collection)
    return stats.report()


@as_query_op
def card_review_map(col: Collection, card_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
    """
    {card_id: [review, ...]} for getReviewsOfCards.

    Every requested card gets an entry, empty when it has no reviews, and each
    review omits `cid` - the key already carries it. Canonical's shape.
    """
    keys = COLUMNS[:1] + COLUMNS[2:]          # everything except cid
    out: Dict[int, List[Dict[str, Any]]] = {int(c): [] for c in card_ids}
    if not out:
        return out
    sql = ("select cid, " + ", ".join(keys) + " from revlog where cid in "
           + _in_clause(list(out)) + " order by id")
    for row in col.db.all(sql):
        out[int(row[0])].append(dict(zip(keys, row[1:])))
    return out


# ====================
# Card-oriented revlog reads (AnkiConnect's areDue / getIntervals)
#
# They answer questions about cards rather than about reviews, but they are
# revlog reads, so they live here - one module owns the revlog SQL.
# ====================

def _scoped_card_ids(col: Collection, card_ids: Sequence[int], state: str) -> Set[int]:
    """
    Which of `card_ids` match a search state ("is:new", "is:due", ...) - ONE
    search for the whole batch: `cid:a,b,c` compiles to an indexed
    `c.id in (...)` in Anki's search engine, so this replaces a search PER
    CARD with a single scoped one.
    """
    if not card_ids:
        return set()
    query = "cid:" + ",".join(str(int(c)) for c in card_ids) + " " + state
    return {int(i) for i in col.find_cards(query)}


@as_query_op
def card_intervals(col: Collection, card_ids: Sequence[int],
                   complete: bool = False, *, strict_history: bool = False) -> List[Any]:
    """
    Intervals a card has been given, newest last. 0 for an unseen card -
    including a card put in the review queue without ever being answered.
    strict_history rejects a missing last interval; complete history may be empty.
    """
    ids = [int(c) for c in card_ids]
    new_ids = _scoped_card_ids(col, ids, "is:new")
    ivls: Dict[int, List[int]] = {}
    seen = [c for c in ids if c not in new_ids]
    if seen:
        for cid, ivl in col.db.all(
                "select cid, ivl from revlog where cid in "
                + _in_clause(seen) + " order by id"):
            ivls.setdefault(int(cid), []).append(int(ivl))
    out: List[Any] = []
    for cid in ids:
        if cid in new_ids:
            out.append(0)
        elif complete:
            out.append(ivls.get(cid, []))
        else:
            if strict_history and not ivls.get(cid):
                raise ValueError("list index out of range")
            out.append(ivls[cid][-1] if ivls.get(cid) else 0)
    return out


@as_query_op
def cards_are_due(col: Collection, card_ids: Sequence[int], *,
                  strict_history: bool = False) -> List[bool]:
    """
    AnkiConnect areDue, including its revlog-based learning-card branch: an
    interval below -1200 means the card is in intraday learning, where due-ness
    is a wall-clock question the search index cannot answer.

    Three batch reads regardless of how many cards were asked about: one
    is:new search, one grouped revlog query, one is:due search over whatever
    is left. A reviewless non-new card falls through to the is:due search
    unless strict_history requires an error; an unknown id defaults to False.
    """
    import time as _time

    ids = [int(c) for c in card_ids]
    new_ids = _scoped_card_ids(col, ids, "is:new")
    last: Dict[int, Any] = {}
    seen = [c for c in ids if c not in new_ids]
    if seen:
        for cid, date, ivl in col.db.all(
                "select cid, id/1000.0, ivl from revlog where cid in "
                + _in_clause(seen) + " order by id"):
            last[int(cid)] = (float(date), int(ivl))   # newest row wins
    need_due = [c for c in seen if c not in last or last[c][1] >= -1200]
    due_ids = _scoped_card_ids(col, need_due, "is:due")

    now = _time.time()
    out: List[bool] = []
    for cid in ids:
        if cid in new_ids:
            out.append(True)
        elif strict_history and cid not in last:
            raise ValueError("list index out of range")
        elif cid in last and last[cid][1] < -1200:
            date, ivl = last[cid]
            out.append(date - ivl <= now)
        else:
            out.append(cid in due_ids)
    return out

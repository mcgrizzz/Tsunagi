"""Check real reviewer transitions, scheduling and undo in a disposable profile.

Run with aqt installed (validated with 26.8.1):
    python tools/check_reviewer.py --screenshot /tmp/tsunagi-reviewer.png

Only the temporary collection receives answers/undo. Text-only cards do not
exercise audible playback or Windows window focus.
"""

import html
import sys
import time
import traceback

from qt_smoke import aqt, run, until


def check_reviewer(app, screenshot):
    from tsunagi.http.compat.actions import gui

    col = aqt.mw.col
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Tsunagi reviewer question", "Tsunagi reviewer answer"
    col.add_note(note, col.decks.id("Default"))
    cid = note.cards()[0].id

    def wait(predicate):
        until(app, predicate)

    def text(web):
        result = []
        # A page still loading has no body yet; a script that throws never
        # calls back, so read it defensively.
        web.page().runJavaScript("document.body ? document.body.innerText : ''",
                                 result.append)
        wait(lambda: bool(result))
        return result[0] or ""

    def scheduling():
        card = col.get_card(cid)
        return (
            card.type,
            card.queue,
            card.due,
            card.ivl,
            card.reps,
            card.lapses,
            card.left,
            card.factor,
        )

    initial = scheduling()
    assert gui.ac_guiReviewActive() is False
    assert gui.ac_guiAnswerCard(gui.EaseParams(ease=3)) is False
    assert gui.ac_guiStartCardTimer() is False
    assert gui.ac_guiDeckReview(gui.DeckParams(name="Default")) is True
    reviewer = aqt.mw.reviewer
    wait(lambda: reviewer.card is not None and reviewer.state == "question")
    wait(lambda: "Tsunagi reviewer question" in text(reviewer.web))
    assert gui.ac_guiReviewActive() is True
    current = gui.ac_guiCurrentCard()
    assert current["cardId"] == cid
    assert current["fields"]["Front"]["value"] == note["Front"]
    assert current["nextReviews"] == [
        col.sched.nextIvlStr(reviewer.card, ease, True) for ease in current["buttons"]
    ]
    assert gui.ac_guiAnswerCard(gui.EaseParams(ease=3)) is False
    assert scheduling() == initial
    print(
        "PASS real reviewer entry, current card and question-side answer guard",
        flush=True,
    )

    deadline = time.monotonic() + 0.15
    wait(lambda: time.monotonic() >= deadline)
    elapsed = reviewer.card.time_taken()
    assert elapsed > 0
    assert gui.ac_guiStartCardTimer() is True
    assert reviewer.card.time_taken() < elapsed
    assert gui.ac_guiPlayAudio() is True
    assert gui.ac_guiShowAnswer() is True
    wait(
        lambda: (
            reviewer.state == "answer"
            and "Tsunagi reviewer answer" in text(reviewer.web)
        )
    )
    assert gui.ac_guiShowQuestion() is True
    wait(
        lambda: (
            reviewer.state == "question"
            and "Tsunagi reviewer answer" not in text(reviewer.web)
        )
    )
    assert gui.ac_guiShowAnswer() is True
    wait(lambda: "Tsunagi reviewer answer" in text(reviewer.web))
    labels = [html.unescape(label) for label in gui.ac_guiCurrentCard()["nextReviews"]]
    wait(lambda: all(label in text(reviewer.bottom.web) for label in labels))
    print(
        "PASS timer reset, replay dispatch and rendered question/answer transitions",
        flush=True,
    )

    if screenshot:
        aqt.mw.resize(1000, 750)
        deadline = time.monotonic() + 1
        wait(lambda: time.monotonic() >= deadline)
        assert aqt.mw.grab().save(str(screenshot))

    assert gui.ac_guiAnswerCard(gui.EaseParams(ease=3)) is True
    wait(lambda: col.get_card(cid).reps == 1)
    wait(lambda: aqt.mw.state != "review" or reviewer.state != "transition")
    assert col.db.scalar("select count(*) from revlog where cid = ?", cid) == 1
    assert scheduling() != initial
    print("PASS asynchronous answer persists scheduling and one review log", flush=True)

    assert gui.ac_guiUndo() is True
    wait(lambda: col.db.scalar("select count(*) from revlog where cid = ?", cid) == 0)
    wait(lambda: scheduling() == initial)
    wait(
        lambda: (
            aqt.mw.state == "review"
            and reviewer.card is not None
            and reviewer.card.id == cid
            and reviewer.state == "question"
        )
    )
    wait(lambda: "Tsunagi reviewer question" in text(reviewer.web))
    assert gui.ac_guiCurrentCard()["cardId"] == cid
    print("PASS real undo restores scheduling, review log and question", flush=True)

    assert gui.ac_guiDeckBrowser() is None
    wait(lambda: aqt.mw.state == "deckBrowser")
    assert gui.ac_guiReviewActive() is False
    assert gui.ac_guiShowAnswer() is False
    assert gui.ac_guiPlayAudio() is False
    print("PASS exit to deck browser disables reviewer operations", flush=True)


if __name__ == "__main__":
    try:
        run(check_reviewer, __doc__)
    except Exception:
        traceback.print_exc()
        sys.exit(1)

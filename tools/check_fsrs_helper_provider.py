"""Run the bundled FSRS Helper provider against the real add-on in a disposable
profile (backlog 2b-P). Not in CI: FSRS Helper is not ours to vendor.

    FSRS_HELPER_DIR=/path/to/addons21/759844606 python tools/check_fsrs_helper_provider.py
"""
import datetime
import importlib
import os
import shutil
import sys
import threading
from pathlib import Path

from qt_smoke import run, until

ADDON = "759844606"


def check(app, screenshot):
    import aqt

    from tsunagi.adapters import addon_actions as actions
    from tsunagi.adapters import providers  # noqa: F401  (registers fsrs_helper)
    from tsunagi.adapters.jobs import jobs

    mw = aqt.mw
    src = Path(os.environ["FSRS_HELPER_DIR"])
    shutil.copytree(src, Path(mw.addonManager.addonsFolder()) / ADDON,
                    ignore=shutil.ignore_patterns("__pycache__", "user_files"))
    importlib.import_module(ADDON)  # what Anki does at startup (safe mode skips it)

    col = mw.col
    col.set_config("fsrs", True)
    model = col.models.by_name("Basic (and reversed card)")
    deck = col.decks.id("Check")
    conf = col.decks.config_dict_for_deck_id(deck)
    conf["new"]["perDay"] = 1000
    col.decks.save(conf)
    for i in range(100):
        note = col.new_note(model)
        note["Front"], note["Back"] = f"f{i}", f"b{i}"
        col.add_note(note, deck)
    col.decks.select(deck)
    while (card := col.sched.getCard()) is not None:
        col.sched.answerCard(card, 4)

    provider, _ = actions.find("fsrs_helper")
    assert actions.unavailable(provider) is None, actions.unavailable(provider)
    items = {item.name: item for item in provider.items}
    print("easy_dates:", actions.read(items["easy_dates"], {}), flush=True)

    def job(name, /, **params):
        # From a worker thread, as a request would; the main thread keeps
        # pumping events so the add-on's callbacks and resets can run.
        box = {}
        threading.Thread(target=lambda: box.update(
            id=actions.submit(provider, items[name], actions.validate(items[name], params)))).start()
        until(app, lambda: "id" in box and jobs.snapshot(box["id"])["status"]
              in ("done", "failed", "aborted"), seconds=180)
        snap = jobs.snapshot(box["id"])
        assert snap["status"] == "done", (name, snap["error"])
        assert snap["result"]["settled"], (name, "did not settle")
        print(f"PASS: {name} {params} -> {snap['result']['result']}", flush=True)
        return snap

    config = mw.addonManager.getConfig(ADDON)
    for disperse in (False, True):
        config["auto_disperse_after_reschedule"] = disperse
        mw.addonManager.writeConfig(ADDON, config)
        job("easy_days")
        job("reschedule", recent=True)
    # An easy date on the day most cards are due, so something moves.
    busiest = col.db.scalar("select due from cards where queue = 2 group by due "
                            "order by count() desc limit 1")
    day = (datetime.date.today() + datetime.timedelta(days=busiest - col.sched.today)).isoformat()
    moved = job("set_easy_dates", dates=[day])["result"]["result"]
    assert mw.addonManager.getConfig(ADDON)["easy_dates"] == [day] and moved["cards"] > 0, moved
    # The add-on's own copy (what its window shows and saves) sees the date too.
    assert sys.modules[ADDON].config.easy_dates == [day]
    job("reschedule", deck=deck)
    gap = busiest - col.sched.today + 1
    moved = job("schedule_break", break_days=min(gap, 60), spread_days=7)["result"]["result"]
    assert moved["cards"] > 0, moved

    # Another add-on registering itself, exactly as docs/addon_providers.md shows.
    other = Path(mw.addonManager.addonsFolder()) / "tsunagi_check_provider"
    other.mkdir()
    (other / "__init__.py").write_text(
        "from anki.hooks import addHook\n"
        "def hello(name='you'):\n"
        "    return {'hello': name}\n"
        "addHook('tsunagi.register', lambda registry: registry.provide(\n"
        "    'check_provider', 'Check Provider', actions=[{'name': 'hello', 'level': 'normal',\n"
        "    'run': hello, 'params': {'name': {'type': 'string'}}}]))\n")
    importlib.import_module(other.name)
    assert actions.collect() == []
    provider, _ = actions.find("check_provider")
    assert provider.addon_id == other.name, provider.addon_id
    assert "fsrs_helper" in actions.PROVIDERS  # bundled ones stay
    items = {item.name: item for item in provider.items}
    job("hello", name="Andrew")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    run(check, "FSRS Helper provider against the real add-on")

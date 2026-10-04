"""onChange, onAnswered, onSync, onCounts, as scripted scenarios. Built into ../listen.json by build.py."""
def events(resources=None, types=None):
    q = {}
    if resources: q["resources"] = ",".join(sorted(resources))
    q["types"] = ",".join((["change"] if resources else []) + sorted(types or [])) or "access.changed"
    return {"method": "GET", "path": "/v1/events", "query": q}
def ready(resources=()): return {"send": [{"event": "ready", "data": {"type": "ready", "session_id": "s", "after_seq": 0, "ts": 1, "resources": sorted(resources), "heartbeat_ms": 15000}}]}
def send(*m): return {"send": list(m)}
def msg(t, **data): return {"event": t, "data": {"type": t, "seq": 1, "session_id": "s", "ts": 1, **data}}
def caps(answers="available", sync="available"):
    state = lambda status, reason=None: {"status": status, "reason": reason, "setting": None}
    return {"status": 200, "body": {
        "versions": {"api": "v1", "addon": "0.6.0", "anki": "26.09"},
        "caller": {"name": "Yomine", "role": "Default", "enabled": True, "key": "valid", "this_computer": True, "host": "127.0.0.1"},
        "operations": {"GET /v1/events": {**state("available"), "operation_id": "streamEvents", "options": {
            "cards.answered": state(answers, None if answers == "available" else "Allow Each card you answer in this app's role in Tsunagi settings"),
            "sync": state(sync, None if sync == "available" else "Allow sync events")}}},
        "features": {}}}
CAPS = {"method": "GET", "path": "/v1/capabilities"}
def with_access(**kw):  # the listener checks its option with access(): the cache joins first
    return [{"expect": events(), "stream": True}, ready(), {"expect": CAPS, "response": caps(**kw)}]
cases = [
 {"name": "onChange is called when something in its resource changes, and not for other resources",
  "script": [{"call": {"method": "notes.onChange"}, "as": "s", "listener": "c"},
             {"expect": events(["notes"]), "stream": True}, ready(["notes"]), {"settle": "s", "ok": True},
             send(msg("notes.created", ids=[1], origin="ui")), {"heard": "c", "calls": [None]},
             send(msg("cards.updated", ids=[2], origin="ui")), {"heard": "c", "calls": []},
             send(msg("notes.stale", reason="collection")), {"heard": "c", "calls": [None]},
             send({"event": "gap", "data": {"type": "gap", "after_seq": 0, "session_id": "s", "ts": 1, "reason": "lagged", "discarded": 2}}), {"heard": "c", "calls": [None]},
             {"end": True}, {"wait": 1000}, {"expect": events(["notes"]), "stream": True}, ready(["notes"]), {"heard": "c", "calls": [None]}]},
 {"name": "a connection that can't be made at first fails the call instead of waiting",
  "script": [{"call": {"method": "notes.onChange"}, "as": "s", "listener": "c"},
             {"expect": events(["notes"]), "response": {"status": 503, "body": {"detail": "No active event session"}}},
             {"settle": "s", "error": {"kind": "http", "status": 503}}, {"wait": 60000}, {"quiet": True}]},
 {"name": "onChange on note types listens to models",
  "script": [{"call": {"method": "noteTypes.onChange"}, "as": "s", "listener": "c"},
             {"expect": events(["models"]), "stream": True}, ready(["models"]), {"settle": "s", "ok": True},
             send(msg("models.stale", reason="details_unavailable")), {"heard": "c", "calls": [None]}]},
 {"name": "onChange fails when the app may not read the resource",
  "script": [{"call": {"method": "reviews.onChange"}, "as": "s", "listener": "c"},
             {"expect": events(["reviews"]), "stream": True}, ready([]), {"settle": "s", "error": {"kind": "permission"}}]},
 {"name": "cards.onAnswered checks the report, then hears each answer in client names, with who answered (by, app)",
  "script": [{"call": {"method": "cards.onAnswered"}, "as": "s", "listener": "a"}] + with_access() + [
             {"expect": events(types=["cards.answered"]), "stream": True}, ready(), {"settle": "s", "ok": True},
             send(msg("cards.answered", origin="api", client="Yomitan", card_id=11, ease=3, interval=12, due=20512, queue=2,
                      memory_state={"stability": 14.2, "difficulty": 5.1})),
             {"heard": "a", "calls": [{"cardId": 11, "rating": "good", "interval": 12, "due": 20512, "queue": "review",
                                       "memoryState": {"stability": 14.2, "difficulty": 5.1}, "by": "api", "app": "Yomitan", "ts": 1}]},
             send(msg("cards.answered", origin="ui", card_id=12, ease=1, interval=0, due=1790000000, queue=1, memory_state=None)),
             {"heard": "a", "calls": [{"cardId": 12, "rating": "again", "interval": 0, "due": 1790000000, "queue": "learning", "memoryState": None,
                                       "by": "ui", "app": None, "ts": 1}]}]},
 {"name": "cards.onAnswered fails with the report's reason when the role doesn't allow card answers",
  "script": [{"call": {"method": "cards.onAnswered"}, "as": "s", "listener": "a"}] + with_access(answers="disabled") + [
             {"settle": "s", "error": {"kind": "permission", "detail": "Allow Each card you answer in this app's role in Tsunagi settings"}}]},
 {"name": "collection.onSync calls started and finished",
  "script": [{"call": {"method": "collection.onSync", "args": []}, "as": "s", "listener": "x"}] + with_access() + [
             {"expect": events(types=["sync"]), "stream": True}, ready(), {"settle": "s", "ok": True},
             send(msg("sync", phase="started")), {"heard": "x", "calls": [["started"]]},
             send(msg("sync", phase="finished")), {"heard": "x", "calls": [["finished"]]}]},
 {"name": "decks.onCounts hears the decks whose due counts changed",
  "script": [{"call": {"method": "decks.onCounts"}, "as": "s", "listener": "n"},
             {"expect": events(["decks"]), "stream": True}, ready(["decks"]), {"settle": "s", "ok": True},
             send(msg("decks.counts", decks=[{"id": 1, "new_count": 20, "learn_count": 3, "review_count": 41, "total_in_deck": 1280}])),
             {"heard": "n", "calls": [[{"deckId": 1, "newCount": 20, "learnCount": 3, "reviewCount": 41, "totalInDeck": 1280}]]},
             send(msg("decks.stale", reason="details_unavailable")), {"heard": "n", "calls": []}]},
 {"name": "listeners share one connection: a new need reconnects it with the union",
  "script": [{"call": {"method": "notes.onChange"}, "as": "a", "listener": "ca"},
             {"expect": events(["notes"]), "stream": True}, ready(["notes"]), {"settle": "a", "ok": True},
             {"call": {"method": "decks.onCounts"}, "as": "b", "listener": "cb"},
             {"expect": events(["decks", "notes"]), "stream": True}, ready(["decks", "notes"]), {"settle": "b", "ok": True},
             {"heard": "ca", "calls": [None]},
             {"stop": "b"}, {"expect": events(["notes"]), "stream": True}, ready(["notes"]), {"heard": "ca", "calls": [None]}]},
]

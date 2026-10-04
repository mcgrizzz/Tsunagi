"""The access cache and onAccessChange, as scripted scenarios. Built into ../access.json by build.py."""
def caps(role, key="k1"):
    return {"status": 200, "body": {
        "versions": {"api": "v1", "addon": "0.6.0", "anki": "26.09"},
        "caller": {"name": "Yomine", "role": role, "enabled": True, "key": "valid", "this_computer": True, "host": "127.0.0.1"},
        "operations": {"POST /v1/notes": {"status": "available", "reason": None, "setting": None, "operation_id": "createNotes", "options": {}}},
        "features": {}}}
EVENTS = {"method": "GET", "path": "/v1/events", "query": {"types": "access.changed"}}
CAPS = {"method": "GET", "path": "/v1/capabilities", "query": {}, "keyed": False}
ready = lambda heartbeat=15000: {"send": [{"event": "ready", "data": {"type": "ready", "session_id": "s", "after_seq": 0, "ts": 1, "resources": [], "heartbeat_ms": heartbeat}}]}
def start(role="Reader", heartbeat=15000):
    return [{"call": {"method": "access"}, "as": "first"},
            {"expect": {**EVENTS, "key": "k1"}, "stream": True}, ready(heartbeat),
            {"expect": {**CAPS, "key": "k1"}, "response": caps(role)},
            {"settle": "first", "result": {"role": role}}]
cached = lambda role, name="again": [{"call": {"method": "access"}, "as": name}, {"quiet": True}, {"settle": name, "result": {"role": role}}]
fetched = lambda role, name="again": [{"call": {"method": "access"}, "as": name}, {"expect": CAPS, "response": caps(role)}, {"settle": name, "result": {"role": role}}]
cases = [
 {"name": "the first access() joins the event connection, then reads the report once it is up; later calls answer from it",
  "script": start() + cached("Reader")},
 {"name": "access.changed: the next access() fetches",
  "script": start() + [{"send": [{"event": "access.changed", "data": {"type": "access.changed", "ts": 1}}]}] + fetched("Writer") + cached("Writer", "third")},
 {"name": "a gap: the next access() fetches",
  "script": start() + [{"send": [{"event": "gap", "data": {"type": "gap", "after_seq": 0, "session_id": "s", "ts": 1, "reason": "lagged", "discarded": 3}}]}] + fetched("Reader")},
 {"name": "while the connection is down every access() fetches; after it is back, one more fetch, then cached",
  "script": start() + [{"end": True}] + fetched("Reader", "down1") + fetched("Reader", "down2")
            + [{"wait": 999}, {"quiet": True}, {"wait": 1}, {"expect": EVENTS, "stream": True}, ready()]
            + fetched("Writer", "back") + cached("Writer", "cached")},
 {"name": "reconnecting waits 1 s, then twice as long after each failure",
  "script": start() + [{"end": True}, {"wait": 1000}, {"expect": EVENTS, "response": {"status": 503, "body": {"detail": "No active event session"}}},
                       {"wait": 1999}, {"quiet": True}, {"wait": 1}, {"expect": EVENTS, "response": {"status": 503, "body": {}}},
                       {"wait": 3999}, {"quiet": True}, {"wait": 1}, {"expect": EVENTS, "stream": True}, ready()]},
 {"name": "after a ready, the delay is 1 s again",
  "script": start() + [{"end": True}, {"wait": 1000}, {"expect": EVENTS, "response": {"status": 503, "body": {}}},
                       {"wait": 2000}, {"expect": EVENTS, "stream": True}, ready(), {"end": True},
                       {"wait": 999}, {"quiet": True}, {"wait": 1}, {"expect": EVENTS, "stream": True}, ready()]},
 {"name": "no heartbeat for three intervals means a dead connection",
  "script": start(heartbeat=1000) + [{"wait": 2999}, {"quiet": True}, {"wait": 1}, {"quiet": True}, {"wait": 1000},
                                     {"expect": EVENTS, "stream": True}, ready()]},
 {"name": "a heartbeat keeps the connection alive",
  "script": start(heartbeat=1000) + [{"wait": 2000}, {"send": [{"comment": "ping"}]}, {"wait": 2000}, {"quiet": True}] + cached("Reader")},
 {"name": "close with reason auth reconnects at once",
  "script": start() + [{"send": [{"event": "access.changed", "data": {"type": "access.changed", "ts": 1}}, {"event": "close", "data": {"reason": "auth"}}]},
                       {"expect": EVENTS, "stream": True}, ready()] + fetched("Writer")},
 {"name": "a 401 or 403 to any request: the next access() fetches",
  "script": start() + [{"call": {"method": "notes.update", "args": [1, {"fields": {"Front": "a"}}]}, "as": "write"},
                       {"expect": {"method": "PATCH", "path": "/v1/notes/1", "body": {"fields": {"Front": "a"}}}, "response": {"status": 403, "body": {"detail": "no"}}},
                       {"settle": "write", "error": {"kind": "permission"}}] + fetched("Reader")},
 {"name": "a new key: the next access() fetches with it, and the connection reconnects with it",
  "script": start() + [{"setKey": "k2"}, {"call": {"method": "access"}, "as": "new"},
                       {"expect": {**CAPS, "key": "k2"}, "response": caps("Writer")}, {"settle": "new", "result": {"role": "Writer"}},
                       {"expect": {**EVENTS, "key": "k2"}, "stream": True}, ready()] + fetched("Writer", "after")},
 {"name": "fresh: true always fetches",
  "script": start() + [{"call": {"method": "access", "args": [{"fresh": True}]}, "as": "fresh"}, {"expect": CAPS, "response": caps("Writer")},
                       {"settle": "fresh", "result": {"role": "Writer"}}] + cached("Writer")},
 {"name": "keepAccess off: every access() fetches, and there is no connection",
  "client": {"keepAccess": False},
  "script": fetched("Reader", "one") + fetched("Writer", "two")},
 {"name": "onAccessChange is called with the new report when access changes, not on connecting",
  "script": [{"call": {"method": "onAccessChange"}, "listener": "changes", "as": "sub"},
             {"expect": EVENTS, "stream": True}, ready(), {"quiet": True}, {"heard": "changes", "calls": []},
             {"send": [{"event": "access.changed", "data": {"type": "access.changed", "ts": 1}}]},
             {"expect": CAPS, "response": caps("Writer")}, {"heard": "changes", "calls": [{"role": "Writer"}]},
             {"end": True}, {"wait": 1000}, {"expect": EVENTS, "stream": True}, ready(),
             {"expect": CAPS, "response": caps("Everything")}, {"heard": "changes", "calls": [{"role": "Everything"}]}]},
 {"name": "onAccessChange's fetch serves the next access() too",
  "script": [{"call": {"method": "onAccessChange"}, "listener": "changes", "as": "sub"},
             {"expect": EVENTS, "stream": True}, ready(),
             {"send": [{"event": "access.changed", "data": {"type": "access.changed", "ts": 1}}]},
             {"expect": CAPS, "response": caps("Writer")}, {"heard": "changes", "calls": [{"role": "Writer"}]}] + cached("Writer")},
 {"name": "close() ends every listener without an error",
  "script": [{"call": {"method": "onAccessChange"}, "listener": "changes", "as": "sub"},
             {"expect": EVENTS, "stream": True}, ready(), {"close": True}, {"settle": "sub", "done": True, "result": None}]},
 {"name": "onAccessChange fails when the connection can't be made at first; access() still answers",
  "script": [{"call": {"method": "onAccessChange"}, "listener": "changes", "as": "sub"},
             {"expect": EVENTS, "response": {"status": 503, "body": {"detail": "No active event session"}}},
             {"settle": "sub", "error": {"kind": "http", "status": 503}}] + fetched("Reader", "meanwhile")
            + [{"wait": 1000}, {"expect": EVENTS, "stream": True}, ready()] + fetched("Reader", "up") + cached("Reader")},
 {"name": "a refused key (401) ends onAccessChange with an authentication error",
  "script": [{"call": {"method": "onAccessChange"}, "listener": "changes", "as": "sub"},
             {"expect": EVENTS, "response": {"status": 401, "body": {"detail": "unknown key"}}},
             {"settle": "sub", "error": {"kind": "authentication"}}, {"wait": 60000}, {"quiet": True}]},
]

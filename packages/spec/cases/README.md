# Conformance cases

Each JSON file here holds `cases`: a client call, the HTTP exchanges it must
make, and what it must return. Every client runs all of them (the TypeScript
runner is `packages/typescript/test/spec.test.mjs`).

The cases are written in `source/<name>.py` and built into `<name>.json`,
one case per line, by `source/build.py`. The JSON is not in git: a client's
tests build it first (`npm test` in `packages/typescript` runs `npm run cases`).

```json
{
  "name": "a named value filters by its code",
  "call": { "query": "cards", "steps": [["where", "queue", "eq", "suspended"], ["select", "id"]], "run": ["take", 5] },
  "exchanges": [
    { "request": { "method": "GET", "path": "/v1/cards", "query": { "select": "id", "shape": "object", "where": ["queue==-1"], "limit": "5" } },
      "response": { "status": 200, "body": { "items": [{ "id": 1 }], "next_cursor": null, "stats": {} } } }
  ],
  "result": [{ "id": 1 }]
}
```

**`call`** is one of:

- `{ "query": <resource>, "steps": [[method, ...args]], "run": [runner, ...args] }`:
  a query built with the steps in order, then run. Runners: `["take", n]`;
  `["page", {size, total}]` (the result is `{items, hasMore, total}`);
  `["pages", {size}]` (every page read with `next`, the result their items
  in order); `["count"]`.
- `{ "method": "notes.create", "args": [...] }`: a client method, by its
  path from the client object.

Names are the client's, in camelCase (`noteType`, `createMany`,
`idempotencyKey`). A client in another case converts them, in calls and in
results. `{"$bytes": "<base64>"}` in an argument is a byte array.

**`exchanges`**, in order. Each `request` lists:

- `method` and `path` (after the base URL);
- `query`: every query parameter, a string or a list of strings for one
  repeated; none other may be sent;
- `body`: the JSON body, compared as JSON; left out means no body;
- `keyed`: `true` when an `Idempotency-Key` must be sent, `false` when none
  may be; a string when it must be that key. Left out: not checked.

Each `response` has a `status` and a JSON `body` (or `text` for a non-JSON
body), always sent with `content-type: application/json` unless `text`.
The call must make exactly these requests, no more.

**The outcome** is `result` (compared as JSON; `undefined` and absent are
the same) or `error`: `{ "kind": <kind>, ...fields the error must have }`.
Kinds: `argument` (refused before sending), `http`, `authentication`,
`permission`, `outcomeUnknown`, `itemRejected`, `partialWrite`,
`jobFailed`, `protocol`.

**`client`**, optional: constructor options for the case
(`maxGetUrlLength`).

## Scenarios

Features that listen (the access cache, `onAccessChange`, watches) are
scenarios: a `script` of steps run in order, with a clock the runner moves.

```json
{
  "name": "access is answered from the last report while the connection is up",
  "script": [
    { "call": { "method": "access" }, "as": "first" },
    { "expect": { "method": "GET", "path": "/v1/events", "query": { "types": "access.changed" } }, "stream": true },
    { "send": [{ "event": "ready", "data": { "type": "ready", "resources": [], "heartbeat_ms": 15000 } }] },
    { "expect": { "method": "GET", "path": "/v1/capabilities" }, "response": { "status": 200, "body": "…" } },
    { "settle": "first", "result": { "role": "Reader" } }
  ]
}
```

| Step | Meaning |
| --- | --- |
| `call`, `as` | Start a call without waiting for it; `as` names it. With `query` and `steps`, `method` is called on that query. A method that takes a listener gets a recording one, named by `listener`: for `watch` and `onSync`, named handlers recorded as `[name, ...arguments]` (`["error", kind]` for `error`). |
| `expect`, then `response` or `stream` | A request the client must have made by now (any pending one that matches `method` and `path`), checked like an exchange's request, plus `key`: the `X-Api-Key` it must carry. `stream: true` answers with an open event stream. |
| `send` | Messages on the open stream: `{event, data}`, or `{comment}`. |
| `end` | The open stream ends. |
| `wait` | Move the clock this many milliseconds. |
| `quiet` | No request is pending. |
| `settle`, then `result`, `error` or `ok` | Wait for a named call. With `done: true`, wait for its subscription's `done`. `ok: true`: it must succeed, whatever it returns. |
| `stop` | Stop the named call's subscription. |
| `heard`, `calls` | What a recording listener was called with since the last `heard`: each call's argument, the list of them when there are several, `null` when none. |
| `setKey` | The client's key provider returns this from now on. |
| `close` | The client's `close()`. |

An access snapshot, as a result or a listener argument, is compared as
`{ "role": <caller role> }`. Unless the case says otherwise, the client is
made with the key `k1`. At the end, no request may be pending.

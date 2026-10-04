# Tsunagi client behavior

What every Tsunagi client library does, whatever its language. The
TypeScript client (`packages/typescript`) follows it; any later client
(Rust is planned) follows it too, so an app gets the same results from
either.

- This page says what a client does, in no particular language. Each
  client spells it in its own idiom: `noteType` in TypeScript is
  `note_type` in Rust, an async iterator in one may be a stream in the
  other. The behavior, the requests sent and the values returned are the
  same.
- [`cases/`](cases) holds the conformance cases: calls, the exact requests
  they send, the responses they get and what the client must return. Every
  client runs them in its tests.
- [`names.json`](names.json) is the client vocabulary that every client's
  generator reads: names, renames, and the operations a client sends.
- Each client also runs a live test against the real server in Tsunagi's
  CI (`tests/test_<language>_client.py`), covering the scenarios listed at
  the end of this page.

A change to client behavior changes this page and the cases in the same
commit, and every client follows before it lands.

## Names and values

Row types come from Tsunagi's API description
(`tests/snapshots/openapi.json`): for each list in `names.json`
`resources`, the row schema of its `GET` response. Nested objects (a
note's fields, a card's memory state) become their own types.

A wire name becomes the client's name by, in order:

1. `fieldsBySchema[schema][wire]`, a rename on one row type;
2. `fields[wire]`, a rename everywhere (`model_name` is `noteType`, `mod`
   and `mtime` are `modified`);
3. otherwise the wire name in the language's case (`deck_name`,
   `deckName`).

Sorts use `sortsBySchema[schema][wire]` first, then the same rules. A
row's key, the field that identifies it, is `id` unless `keys` names
another (a tag's `name`, a media file's `filename`). Names in
`omit` don't exist in the client (`usn` everywhere; a card's `flags`, which
duplicates `flag`). Nested types are named by `nestedTypes`, row types by
`types`.

**Coded values.** A field with `x-values` in the description reads and
filters by name, never by number: the value's text in the language's case
(`sibling_buried` is `siblingBuried` in TypeScript). A string field with an
`enum` reads the same way (a failure's `invalid_note` is `invalidNote`). `valueOverrides`
replaces a name: a review's `ease` 0 is null (`rating: null`), since the row
records no answer.

**Nullable.** A field is null only where the description says
`x-nullable`, or where a value override gives null.

**Decoding a row.** The client checks every value it returns against the
description, and refuses the response (a protocol error) when:

- a selected field is missing;
- a value has the wrong type (a string for a number, a non-finite number);
- a field that can't be null is null;
- a coded field has a code the description doesn't list.

Nested objects decode the same way and use their client names (a note
field's `ord` is `index`).

**Generated.** From the description and `names.json`, each client generates
(and decodes every answer and event message through):

- each resource's row type and its field table (wire name, kind, values,
  nullability), its sorts and its key;
- for each operation in `names.json` `operations`: its method and path, its
  request body in wire names (so an encoder can't send a key the server
  doesn't take), and its answers by status, in client names, decoded through
  the same tables. In an answer, a field the schema doesn't require may be
  absent, and reads as null when it can be null;
- each event message (`x-events` on `GET /v1/events`): its schema, and the
  resource or events option that carries it;
- each row field's and search's `x-from`, for watching;
- the error body (`detail`, and `reason` on a 503: `busy`, `closed`,
  `syncing`).

The rest is written by hand on top: the query builder, the friendly inputs
(below) and how they map to the bodies, watching and listening. Answers are
read-only.

## Queries

Every list in `names.json` `resources` is a query, except `addons`, which
is a plain list. A query describes rows and runs nothing until one of
`take`, `page`, `iterate` or `count` is called. Every method returns a new
query; the old one is unchanged.

| Method | Effect |
| --- | --- |
| `search(text)` | Anki search (cards, notes, reviews). Replaces a previous search. |
| `where(field, operator, value)` | A filter. Several mean all must hold. |
| `orderBy(sort, direction)` | One of the resource's sorts, ascending by default. Replaces a previous order. |
| `distinctOn(field)` | One row per value of a field: the first in the order. |
| `select(fields...)` | Only these fields. The row type has exactly these. |
| `values(field)` | Each row's value of one field, bare. |
| `take(n)` | At most `n` rows, one request. `take(0)` sends nothing. |
| `page(size = 50, total = false)` | One page, and a way to get the next. |
| `iterate(size = 100)` | Every row, a page at a time, fetched only as it is consumed. |
| `count()` | How many rows match. Reads none of them. |

Without `select`, rows have every field, as the server sends them. On cards
that renders each card's question and answer, so a client's docs say to
select what you need.

**Operators.** `eq` and `ne` on any single value; `gt`, `gte`, `lt`,
`lte` on numbers; `contains`, `startsWith`, `endsWith` on free text (not on
named values); `in` and `notIn` with a list. `null` only on a field that can
be null.

### The request

A query is `GET <path>` with these parameters, or, when the URL would be
longer than 2,000 characters, `POST <path>/query` with the same names in a
JSON body:

| Parameter | Value |
| --- | --- |
| `select` | Wire names, comma-separated. Left out without `select`. |
| `shape` | `scalar` for `values`, otherwise `object`. |
| `where` | One clause per filter, repeated: `<wire><op><value>`. |
| `search` | The Anki search, as given. |
| `order` | `<wire sort>:asc` or `:desc`. |
| `distinct_on` | The wire name. |
| `include` | `total` with `page(total)` and `count()`. |
| `limit` | `n`, the page size, or `0` for `count()`. |
| `cursor` | The previous page's `next_cursor`, for the next page. |

A clause's operator is `==`, `!=`, `>`, `>=`, `<`, `<=`, `~=` (contains),
`^=` (starts with), `$=` (ends with), ` in` or ` not in`. The value is
JSON: strings quoted and escaped, numbers as numbers, `true`, `false`,
`null`; a list is `[a,b]` with no spaces. A named value is sent as its code
(`queue in[-2,-3]`; `rating eq null` is `ease==0`).

### Pages

A page has its rows, whether there is a next page (`next_cursor` isn't
null), the total when asked for, and a way to read the next one with the
same query and size. A cursor the server already gave for this query is a
protocol error, so a loop can't go on forever. More rows than the limit is
a protocol error.

### Checks before sending

A client refuses these before any request, so a mistake fails at the call
(a type error in typed languages, an argument error at run time):

- a field, sort or operator the resource doesn't have, in client names;
- a value of the wrong type, or a value name the field doesn't list;
- `null` on a field that can't be null;
- `in`/`notIn` without a list, or a list with another operator;
- `values` or `distinctOn` on a list or object field;
- `select` with no fields; `take` with a negative count; a page size below 1.

## Writes

Every write sends an `Idempotency-Key`: a new random key per call unless the
caller gives one. Writes are never retried by the client. The body is
encoded before anything else is awaited (a key provider, the network), so a
caller changing its input afterwards can't change what is sent.

| Method | Request | Returns |
| --- | --- | --- |
| `notes.create(note)` | `POST /v1/notes`, a list of one | the created note, or an item error |
| `notes.createMany(notes)` | `POST /v1/notes` | per-item results (below) |
| `notes.update(id, patch)` | `PATCH /v1/notes/{id}` | nothing |
| `notes.check(notes)` | `POST /v1/notes:check`, `{notes}`; a read, no key | one check per note, in order |
| `notes.upsert(note)` | `POST /v1/notes:upsert`, a list of one | created or updated, or an item error |
| `notes.upsertMany(notes)` | `POST /v1/notes:upsert` | per-item results |
| `notes.delete(ids)` | `POST /v1/notes:delete`, `{note_ids}` | `affected` |
| `cards.<verb>(ids, ...)` | `POST /v1/cards:<verb>`, `{card_ids, ...}` | `affected` |
| `cards.answer(answers)` | `POST /v1/cards:answer`, `{answers: [{card_id, ease}]}` | `affected` |
| `media.upload(file)` | `POST /v1/media`, a list of one | the stored file, or an item error |
| `media.uploadMany(files)` | `POST /v1/media` | per-item results |
| `collection.sync()` | `POST /v1/collection:sync` | the result, after waiting for the job |
| `collection.startSync()` | the same | a handle to wait on |

The card verbs are `suspend`, `unsuspend`, `bury`, `unbury`, `forget`
(`restore_position`, `reset_counts`, both false by default), `setDueDate`
(`days`, in Anki's syntax), `changeDeck` (a name or an id), `reposition`
(`starting_from` 0, `step_size` 1, `randomize` and `shift_existing` false by
default) and `setFlag` (a flag name, sent as its code). `answer` takes a
rating name, sent as `ease`.

**A note's body.** `deck` and `noteType` are a name (`deck_name`,
`model_name`) or `{id}` (`deck_id`, `model_id`). `fields`, `tags`.
`duplicates` maps to `allow_duplicate`, `duplicate_scope` and
`duplicate_scope_options` (`deck_name`, `check_children`,
`check_all_models`). `audio`, `video`, `picture`: lists of files, each
exactly one of `data` (bytes, sent as base64), `url` or `path`, with an
optional `filename` and `fields`. A patch sends only what was given; `tags`
replaces, `addTags`/`removeTags` add and remove, `noteType` retypes.
Upsert adds `match` (`matchField`) and `on_match` (`fieldRules` with
`replaceIfEmpty` as `replace_if_empty`, `tagRule`, `separator`).
`create` and `createMany` can ask for card ids and duplicate ids
(`include=cards,duplicate_ids`), `upsert` for card ids, `check` for
duplicate ids.

**Per-item results.** A batch's response has `created` (and `updated` for
upsert) and `failed`, each item with its `index`. The client returns one
result per submitted item, in input order: a success with its value (the
answer's item: a created note's `index`, `id`, `cards`, `files`), or a
failure (the answer's failure: `index`, `code` by name, `message`, and for
notes `duplicateNoteIds` and `attachment`). A missing, repeated or
out-of-range index is a protocol error, and so is a code the description
doesn't list; for a write either means the outcome is unknown.

- A single-item method returns the value, or raises the item's failure.
- A batch method raises a partial-write error carrying every result when
  any item failed (successes are not rolled back), or returns every result
  when the caller asks to collect them.
- An empty batch sends nothing.

**Outcome unknown.** When a write was sent and the client can't tell what
happened, it raises "outcome unknown" with the key, and never retries:

- the connection failed or was cancelled after sending;
- the server answered 5xx (a 503 doesn't cancel a write);
- the response can't be decoded.

**Sync.** `POST /v1/collection:sync` answers the result (200) or a job (202,
`job_id`). A job is polled at `GET /v1/jobs/{id}`, first after 500 ms, each
wait 1.5 times longer up to 5 s, until `done` (the result), `failed` or
`aborted` (a job error with the server's detail). Waiting has its own
deadline (120 s by default); when it passes, the client raises a wait
timeout carrying the handle, so the app can wait again. Waiting never
submits again.

## Errors

| Kind | When | Keeps |
| --- | --- | --- |
| HTTP error | any non-2xx answer | status, the body, `detail`, `reason`, `errors` |
| authentication | 401 | as above |
| permission | 403 | as above |
| outcome unknown | a write whose result is unknown (above) | the key, the cause |
| item rejected | a single-item write's item failed | the failure |
| partial write | a batch with failed items | every result |
| job failed | a job ended `failed` or `aborted` | the job id, status, detail |
| wait timeout | waiting for a job passed its deadline | the handle |
| request timeout | a request passed its deadline (30 s by default) | |
| transport | the request couldn't be made | the cause |
| protocol | a response the description doesn't allow | |

An error's message never contains server text, which can hold note
content; `detail` is there for the app to show. A client never decides
anything by matching English text.

## Access

`access()` returns a snapshot of `GET /v1/capabilities`: the versions, the
caller (`name`, `role`, `enabled`, `key`: `valid`, `unknown` or `none`,
`thisComputer`, `host`), and each operation's state. A snapshot answers
whether a client method or query is available: the client maps each method
to its operation (`notes.create` to `POST /v1/notes`, a query on cards to
`GET /v1/cards`) and reads that operation's `status`. Checks take a method or
a query, never a name. Checking never runs the operation, and a request is
never held back by a snapshot: each is checked by the server and can still
fail with a permission error.

**Kept current (`keepAccess`, on by default).** The client keeps the last
snapshot and returns it without a request while it is known to be current:

1. The first `access()` fetches the report and joins the event connection
   (below), which then always carries `access.changed`.
2. A snapshot is current when its fetch started while the connection was up
   (after `ready`) and nothing below happened since it started. Calls while a
   fetch is running share it.
3. The snapshot stops being current on:
   - `access.changed`;
   - `gap`;
   - the connection dropping, and every new `ready`;
   - a different key: the client reads its key on each `access()`, and on a
     change also reconnects the event connection with the new key;
   - a 401 or 403 answer to any request.
4. While the connection is down, nothing is current: each `access()`
   fetches.
5. `access({ fresh: true })` always fetches.

With `keepAccess` off, every `access()` fetches and joins nothing.

**`onAccessChange(listener)`.** Whenever the snapshot stops being current
because of the server (`access.changed`, `gap`, a reconnect), the client
fetches the report at once and calls the listener with the new snapshot; a
fetch that fails is not reported (the next `access()` fetches). Like every
listener (below), it completes once the connection is up. A refused key
(401) ends it with an authentication error.

`health()` reads `GET /v1/health`: the server, port, versions, the
collection's state (`ready`, `syncing`, `closed`, `busy`) and profile, and
the caller.

## The event connection

One connection to `GET /v1/events` per client, shared by every feature
that listens: the access cache, `onAccessChange`, and the features below.

- **What it asks for.** The union of what its listeners need:
  `resources=` the resources, comma-separated and sorted; `types=` `change`
  (every data event of those resources) when there are resources, plus
  `cards.answered` and `sync` when asked for. With no resources and no
  types, `types=access.changed`, which needs no permission. Every stream
  gets `access.changed`.
- **Opening and closing.** It opens when the first listener joins and closes
  when the last one leaves, or on `close()`. When a listener joins that
  needs something the connection doesn't carry, the client reconnects with
  the new union; listeners already there then see a new `ready`.
- **Keeping it up.**
  - `ready` gives `heartbeat_ms`; with nothing received for three of those,
    the connection is dead.
  - A dead or dropped connection, or `close` (any reason), reconnects after
    a delay: 1 s, doubling to 30 s, back to 1 s after a `ready`. `close`
    with `auth` reconnects at once.
  - Listeners learn of each drop and each `ready`.
- **The first try.** A listener that hasn't seen `ready` yet fails with the
  error when the connection can't be made (the server unreachable, a 5xx
  such as no profile open), so an awaited `watch` or `on…` call doesn't wait
  forever; drops after a `ready` are retried. A reconnect the client makes on
  purpose (a new need, a new key) doesn't count.
- **Refusals.** 401 ends every listener with an authentication error and
  closes the connection. 403 (the app may not read the collection) ends the
  listeners that needed data, with a permission error, and the client
  reconnects with what remains.
- **Subscriptions.** Each listening feature returns a subscription: `stop()`
  ends it; `done` settles when it ends: resolves on `stop()` or `close()`,
  rejects with the error that ended it otherwise. A cancellation signal can
  be given instead of calling `stop()`.

## Watching a query

`watch(handlers)` keeps an app in step with a query: every row matching its
search and filters, reported as it changes. It is on `notes`, `cards`,
`reviews`, `decks`, `noteTypes` and `tags` (the server sends no events for
media or deck presets), and not on a query with `orderBy`, `distinctOn` or
`values`: changes have no order, and one row per value can't be kept current
from per-row changes. Limits don't apply; a watch covers every matching row.

```text
watch = query.watch({
  added(rows, change)     the first load (change.initial), new rows, rows that joined
  updated(rows, change)   rows whose selected values changed
  removed(keys, change)   rows deleted, or no longer matching
  error(error)            the error that ended the watch
})
```

- Every handler is optional. Rows have the query's selected fields plus the
  resource's key (`id`; a tag's `name`), which the watch adds to the select
  when it isn't there. `removed` gets keys.
- `change` says `initial` (the first load), and who made the change when
  the server said: `by` (`ui` or `api`) and `app` (the app's name, for
  `api`); both null when the change was found by reading again.
- The call completes once the first load has been delivered, and fails with
  the error when it can't be made (a permission error when the app can't
  read the resource). It returns a subscription.
- After that, an error ends the watch only when it would repeat: 401, 403,
  a protocol error, or a handler raising. Anything else (a dropped
  connection, a 5xx, a timeout) is retried: the watch reads everything
  again after 1 s, doubling to 30 s.

**What the watch keeps:** each row's key and a fingerprint of its selected
values (a hash of the row as the server sent it). Not the rows.

**Its connection need:** its resource (`notes`, `cards`, `reviews`,
`decks`, `models` for note types, `tags`), plus the resources whose changes
can change its rows, from the description's `x-from`: on the list's
`search` parameter when the query has a search (what Anki's search reads:
`deck:`, `note:`, tags, card states), and on each selected field built from
another resource (a card's `deckName` from `decks`, its `fields` from
`notes` and `models`). The connection is shared, so a watch acts only on
messages about its own resources.

If `ready.resources` lacks the watch's own resource, the app may not read
it: the watch fails with a permission error. A related resource missing is
ignored.

**What each message does.**

| Message | Then |
| --- | --- |
| `<own>.created`, `.updated` (ids); `reviews.created`; `decks.counts` (each deck's `id`) | check those keys |
| `<own>.deleted` (ids) | `removed` for keys seen before; no request |
| cards ids on a notes watch | find their notes (`notes`, `search=cid:<ids>`, values `id`), then check those |
| notes ids on a cards watch | find their cards (`cards`, `where=note_id in[<ids>]`, values `id`), then check those |
| ids from another of its resources (cards on a reviews watch) | nothing: only that resource's `.stale` is followed |
| any `.stale` of its resources; `gap`; a `ready` after a drop | read everything again |

**Checking keys** is one request, read in pages of 2,000: the query
(search, filters, select) narrowed to those keys. On notes and cards with a
search, the ids go into the search, `(<search>) nid:<ids>` or
`(<search>) cid:<ids>`, so Anki narrows before it searches (measured
2026-10-04 on 5,410 notes: about 15 ms against 20 ms for the filter);
otherwise a filter, `<key> in[<keys>]`. Then, for each key:

| Matches now | Seen before | Handler |
| --- | --- | --- |
| yes | no | `added` |
| yes | yes, other fingerprint | `updated` |
| yes | yes, same fingerprint | none |
| no | yes | `removed` |
| no | no | none |

**Reading everything** (the first load, and each read again): wait for the
connection's `ready`, read the query in pages of 2,000 (no order), then
compare with what was seen: new keys `added`, missing keys `removed`, other
fingerprints `updated`. A read that fails delivers nothing and is retried.

**Batching and order.** One piece of work runs at a time: a read, or a check.
Messages that arrive meanwhile are gathered and handled together next: a
read again replaces any check, deletes win over updates of the same key, and
a key's latest message gives its `by`/`app`. Handlers are called in the order
`removed`, `updated`, `added`, once per `by`/`app` within a piece of work.

## Listening

Methods that call a listener as things happen. Each joins the event
connection, completes once the connection is up (after `ready`), fails when
the app may not receive what it asked for, and returns a subscription.

| Method | Connection need | Calls the listener with |
| --- | --- | --- |
| `<resource>.onChange(listener)` | the resource | nothing: something changed |
| `cards.onAnswered(listener)` | `types=cards.answered` | the answer, and who answered |
| `collection.onSync({started, finished})` | `types=sync` | nothing |
| `decks.onCounts(listener)` | `resources=decks` | the decks whose due counts changed |

- **`onChange`** is on every resource Tsunagi sends events for (the ones a
  watch is on). Each of the resource's messages counts (created, updated,
  deleted, stale), and so do `gap` and a `ready` after a drop. Messages that
  arrive while the listener is still running (until the value it returns
  settles, when it returns one) are one more call afterwards, not one each.
  It doesn't follow related resources: for "the 20 newest, kept current",
  run the query again in the listener.
- **`cards.onAnswered`**: the `cards.answered` message in client names and
  values: `cardId`, `rating` (from `ease`), `interval`, `due`, `queue` by
  name, `memoryState` (`{stability, difficulty}` or null), who answered
  (`by`, `app`), and `ts`. Every card answer, in Anki or through
  either API. Needs the capabilities report's
  `operations["GET /v1/events"].options["cards.answered"]` to be available;
  otherwise it fails with a permission error carrying the report's reason.
- **`collection.onSync`**: `started` and `finished` for each sync's `phase`.
  Needs the `sync` option, like `cards.answered`.
- **`decks.onCounts`**: `[{deckId, newCount, learnCount, reviewCount,
  totalInDeck}]`, from `decks.counts`. Fails with a permission error when
  `ready.resources` lacks `decks`.

`onChange` fails like `onCounts` when `ready.resources` lacks its resource.

## Transport

- The base URL is an HTTP(S) server root without credentials, query or
  fragment; a path prefix is kept (a reverse proxy). Requests stay under
  `<root>/v1/`.
- The key goes in `X-Api-Key`, read again for every request (it may
  rotate), never in a URL.
- Redirects are refused; cookies are never sent.
- `raw.request(method, path, body)` reaches any endpoint and returns the
  status, headers and undecoded JSON. A raw write sends a key only when the
  caller gives one.

## Live scenarios

Each client's live test, against the real server on a fresh collection,
covers at least:

- access and health of a keyless local caller;
- creating notes, one with a file, a batch with a duplicate (its duplicate
  ids), an update, a check, an upsert;
- queries with each operator kind, through `GET` and `POST /query`, paged
  and iterated, `count`;
- every resource read whole (no `select`), and each of its sorts;
- named values both ways (flag, queue, rating, review type);
- card verbs, a media upload, a note delete;
- a watch's first load on a search, and `onChange` subscribing;
- `access()` served from the cache, and `onAccessChange` called after a
  role change;
- a card answer heard by `cards.onAnswered` (with the Everything role).

Changes reach watches and `onChange` through Anki's operation hooks, which
only a running Anki fires; the test server doesn't. The scenarios in
`cases/` cover them, and a release is checked on a desktop Anki: a watch on
a search sees a note added, edited, losing its tag and deleted.

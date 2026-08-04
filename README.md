# Tsunagi

> HTTP API for Anki with advanced querying and pagination

**Tsunagi** (繋ぎ = “connection”) exposes your Anki collection over a small, local HTTP server so other tools can talk to it. It’s aimed at integrations, automations, and external apps that want fast, typed, queryable access to Anki data.

> **Status:** early/experimental. I’m building this in public and I’ll keep breaking things until it feels right. Once it’s complete, I’ll publish a proper comparison against AnkiConnect.

## Why this exists

AnkiConnect is great and battle-tested, but while building [Yomine](https://github.com/mcgrizzz/Yomine) I kept running into patterns that felt longwinded and lossy.

**A concrete example: get all models and their field names.**

Here's how I tackle this with AnkiConnect in Yomine:

1) Fetch names + IDs  
```json
{"action":"modelNamesAndIds","version":6}
```

2) Then, for **each** model name, fetch field names  
```json
{"action":"modelFieldNames","version":6,"params":{"modelName":"Basic"}}
```

Here are some issues I have with this:

- **Redundant internal work.** `modelNamesAndIds` first gathers names via `all_names_and_ids()` throws out the ids, then in a loop, looks up each model id by name. But Anki’s internal `all_names_and_ids()` already has what we want in one call to the DB, both the names and ids.
- **Name→ID round-tripping.** `modelFieldNames` takes a single **name** as input, which forces another lookup to get the ID again.
- **Data is thrown away.** `modelFieldNames` returns only the field **names**, even though the underlying call had richer field metadata (descriptions, fonts, ordinals, etc.). If you want any of that, you have to make more calls.

**How Tsunagi handles the same task**

The idea is: fewer round-trips, no unnecessary work, and you choose exactly what to keep.

1) Get model names and IDs (routes to `all_names_and_ids()` under the hood):
```bash
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name'
```

2) In one shot, get field names for a set of IDs:
```bash
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=fields[].name' \
  --data-urlencode 'where=id in [1487718035000,1487718035001]'
```

If you need richer metadata, just ask for it:

```bash
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=fields[].(name,ord,description,font)'
```

No special endpoints, no throwaway filtering-just `select` what you want and go.

**Design goals, summarized**

- **Query planner** chooses the fastest route (search/index/column/full fetch).
- **Thread-safe** via Anki’s `QueryOp`/`CollectionOp` — reads run off the UI
  thread, writes are undoable, and requests time out instead of hanging when
  Anki is busy.
- **Typed I/O** with Pydantic.
- **Small query DSL** for filters + projections.
- **Cursor pagination** for large scans.
- **GET/POST parity** so URL queries and JSON bodies are equivalent.

There’s also an **AnkiConnect shim** at `POST /`, so you can adopt this
gradually without ripping anything out — see
[AnkiConnect compatibility](#ankiconnect-compatibility).

## Table of Contents

- [Tsunagi](#tsunagi)
  - [Why this exists](#why-this-exists)
  - [Table of Contents](#table-of-contents)
  - [Install](#install)
    - [Dependencies](#dependencies)
  - [Usage](#usage)
    - [Filter Syntax](#filter-syntax)
    - [Field Selection](#field-selection)
    - [Pagination](#pagination)
    - [URL Encoding Tips](#url-encoding-tips)
  - [API](#api)
    - [Query Parameters](#query-parameters)
    - [Response Format](#response-format)
    - [Endpoints](#endpoints)
  - [Event stream](#event-stream)
  - [Roadmap](#roadmap)
  - [Contributing](#contributing)
  - [Maintainers](#maintainers)
  - [License](#license)

## Install

Not published yet. If you’re adventurous, you can build the addon locally:

```bash
# from the repo root
python tools/build_addon.py
```

Then install the produced file in Anki. Tsunagi runs **inside Anki** and starts a local server (default: `http://127.0.0.1:7777`).

Settings live in a dialog (Tools → Tsunagi Settings, or the add-on's Config
button): server host/port, API key, CORS allowlist, media limits, and the
opt-in gates for routes that are off by default. Everything applies on save —
server-level keys by restarting the embedded server automatically. The
underlying JSON keys are documented in `config.md`.

### Dependencies

Dependencies are bundled with the addon. All dependencies are pure-Python (Pydantic v1.10.22, FastAPI 0.109.2), requiring no platform-specific native wheels. Requires Anki 23.10 or newer.

## Usage

Default base URL: `http://127.0.0.1:7777`

```bash
# List all models (Anki “note types”)
curl http://127.0.0.1:7777/v1/models

# Filter by name (case-insensitive substring)
curl --get "http://127.0.0.1:7777/v1/models" --data-urlencode 'where=name~=Basic'

# Select a subset of fields
curl --get "http://127.0.0.1:7777/v1/models" --data-urlencode 'select=id,name'

# Combine selection + filtering
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name' \
  --data-urlencode 'where=type==0'
```

You can also send the exact same query as JSON (see [GET/POST parity](#endpoints)).

### Filter Syntax

```text
# Equality / comparison
?where=id==123
?where=sort_field>=5

# Substring match (case-insensitive)
?where=name~=Basic

# Lists
?where=id in[123,456,789]
?where=name not in["Basic","Cloze"]

# Nested fields
# (example: filter models whose fields contain a field named "Front")
?where=fields[].name==Front

# Multiple filters (AND semantics; repeat the param)
?where=type==0&where=name~=medical
```

### Field Selection

```text
# Top-level fields
?select=id,name,type

# Array projection
?select=fields[].name

# Multi-field with aliases
?select=fields[].(name:label,ord:index)
```

> Tip: If you only select a single field, you can also set `shape=scalar` to get back an array of values instead of objects (see below).

### Pagination

```bash
# First page
curl --get "http://127.0.0.1:7777/v1/models" --data-urlencode 'limit=10'

# Next page (use next_cursor from prior response)
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'limit=10' \
  --data-urlencode 'cursor=eyJpZCI6MTAwfQ'
```

### URL Encoding Tips

Query operators (`==`, `>=`, `~=`, brackets, quotes, etc.) can be annoying to shell-escape. Use `--data-urlencode` with curl (as shown above) to avoid surprises.

## API

### Query Parameters

| Parameter | Type      | Default  | Description |
|-----------|-----------|----------|-------------|
| `select`  | `string`  | -        | Comma-separated fields to return. Supports array projection and aliasing. |
| `where`   | `string`* | -        | Filter expression. Repeat the parameter for multiple ANDed filters. |
| `search`  | `string`  | -        | Anki search string (e.g. `deck:Japanese tag:verb`, `is:due`). Search-backed resources only (`/v1/notes`, `/v1/cards`); others return 400. |
| `shape`   | `string`  | `auto`   | `auto` (objects), `object` (always objects), `scalar` (single-field results as values). |
| `limit`   | `integer` | `1000`   | Items per page (1–5000). |
| `cursor`  | `string`  | -        | Opaque pagination cursor returned by the API. |

\* For POST JSON, you can pass a single string or an array of strings for `where`.

Field names and bare values may be non-ASCII: `?where=fields[].value==犬` and
`?select=単語` both work. Quote values containing spaces or punctuation:
`?where=name=="Basic (and reversed)"`.

**Filters are complete.** If a row matching your `where` exists anywhere in
the collection, it is returned — no partial scans, no retry loops. `limit`
bounds the *results*, not the search: `/v1/notes` enumerates ids first, then
loads rows a batch at a time until your page is full or the collection is
exhausted. `next_cursor` is `null` when there is genuinely nothing more.

The cost is that a `where`-only query over a large collection loads notes
until it fills the page. Pair it with `search` whenever you can — that pushes
the narrowing into Anki's own index, and `where` then refines a much smaller
set: `?search=tag:verb&where=fields[].value~=犬`.

### Response Format

```json
{
  "items": [ { /* your data */ } ],
  "next_cursor": "eyJpZCI6NTAwfQ",
  "stats": { "duration_ms": 12.5 }
}
```

### Endpoints

Every resource below supports the query parameters above, plus
`POST {path}` (create), `PATCH {path}/{id}`, `DELETE {path}/{id}`.

- **`/v1/models`** - Note types (“models” in Anki terms), with `fields` and
  `templates` subresources (`POST/PATCH/DELETE /v1/models/{id}/fields/{name}`,
  `PUT /v1/models/{id}/fields:order`).
- **`/v1/decks`** - Decks. Nested names use `::`; creating `A::B` creates `A`.
  Filtered (dynamic) decks appear in reads. Due counts (`new_count`,
  `learn_count`, `review_count`, `total_in_deck`) come from the scheduler, so
  they're only computed when your `select`/`where` mentions one — and then it's
  one call for the whole page, not one per deck. `desired_retention` (the
  per-deck FSRS override, newer Anki than 23.10; 501 there) reads and patches
  as a fraction (`0.85`); explicit `null` clears the override.
- **`/v1/deck-configs`** - Deck options groups. Returned as Anki's config dicts
  verbatim (newer scheduler keys survive a read-modify-write), so `select` and
  `where` reach into `new`/`rev`/`lapse`. `PATCH` merges recursively. Assign one
  to a deck with `PATCH /v1/decks/{id} {"config_id": ...}`. The FSRS per-preset
  knobs are ordinary keys here: `desiredRetention` on every supported version,
  `fsrsParams5`/`fsrsParams6`/`weightSearch` where the running Anki has them.
- **`/v1/notes`** - Notes. Supports `search`. `fields` come back as
  `[{name, value, ord}]` (so `where=fields[].name==Front` works); writes accept
  that array *or* a plain `{"Front": "犬"}` map. `cards` is only computed when
  your `select`/`where` asks for it.
  - **`POST /v1/notes:check`** - “can these be added?” per candidate, with
    `duplicate_note_ids` — without adding anything.
- **`/v1/cards`** - Cards. Supports `search`. Read-only as a resource: cards are
  generated from notes by a model's templates, so there is no `POST` or
  `DELETE`. `due` is passed through raw — it means a queue position, a day
  number or a timestamp depending on `queue`. The note-derived fields
  (`model_name`, `css`, `fields`, `question`, `answer`) and `retrievability`
  (FSRS's recall probability right now — a backend call per card) are only
  built when your `select`/`where` asks for them. The FSRS columns
  (`memory_state`, `desired_retention`, `decay`, `last_review_time`) are always
  present, null until FSRS has seen the card.
  - Scheduling is batch verb routes, so a bulk change is one undo entry:
    `POST /v1/cards:suspend`, `:unsuspend`, `:bury`, `:unbury`, `:forget`,
    `:set-due-date`, `:change-deck`, `:reposition`, `:set-flag`, `:set-ease`.
  - **`POST /v1/cards:set-memory-state`** overwrites per-card FSRS state
    (stability/difficulty, desired retention, decay) — how FSRS helper tools
    reschedule. A normal undoable write through the scheduler, but off by
    default: enable `gates.cards_set_memory_state` in the config. Omitted
    fields are left alone; explicit `null` clears. `decay` needs a newer Anki
    than 23.10 (501 there).
- **`/v1/tags`** - Tags. `GET` (with optional `prefix`), `PATCH /v1/tags/{tag}`
  to rename and `DELETE` to remove — both apply to the tag *and its children*,
  like Anki. Plus `POST /v1/tags:bulk-add`, `:bulk-remove` and `:clear-unused`.
- **`/v1/media`** - Media files. `GET /v1/media/{filename}` streams raw bytes
  with a real `Content-Type`; `POST /v1/media` takes base64 `data` or a `url`
  (local `path` is off by default, see `gates.media_allow_local_path` in config) and
  returns the filename Anki **actually** stored — it renames on collision.
  Filter the listing with `prefix`/`suffix`; media is a flat namespace, not a
  DSL-queryable resource.
- **`/v1/reviews`** - Review history from the revlog, read-only and
  keyset-paginated on the review timestamp. `?search=` takes Anki query syntax
  and means "reviews of the cards this matches"; `where=card_id==...` uses an
  index instead. Writing rows is deliberately absent — the scheduler owns the
  revlog.
- **`/v1/fsrs:*` and `/v1/jobs`** - FSRS computations, beyond anything
  AnkiConnect exposes. `POST /v1/fsrs:compute-params` (optimize from review
  history) and `:evaluate-params` (log loss / RMSE of given parameters) can run
  for minutes on a real collection, so they answer **202 with a job id**:
  poll `GET /v1/jobs/{id}` for `status` (`queued → running → done|failed|aborted`),
  best-effort `progress {current, total}`, and the `result`; cancel with
  `POST /v1/jobs/{id}:abort` — a 200 there guarantees the job ends `aborted`
  (Anki's own abort flag has blind spots, so if the computation finishes
  underneath, the result is discarded; these are pure reads, nothing is
  written). One job runs at a time (Anki's progress and abort are global) — a
  second submit gets a 409. Jobs live in memory only.
  `POST /v1/fsrs:simulate`, `:simulate-workload` and `:optimal-retention` wrap
  Anki's FSRS simulator and answer synchronously; they need a newer Anki than
  23.10 (501 there), as do compute/evaluate options beyond `search`/`params`.
  Anki's own sparse-history behaviour is surfaced as-is: 23.10 fails the job
  with "Insufficient review history", newer Anki reports `done` with empty
  `params`. While an optimization runs, Anki holds the collection lock — other
  API calls may 503 until it finishes.
- **`/v1/gui:*`** - Drives the running app: `:browse`, `:select-card`,
  `:edit-note`, `:add-cards` (prefill the Add dialog — what asbplayer's "Open
  in Anki" needs), `:set-add-note-data`, `:show-question`, `:show-answer`,
  `:answer-card`, `:play-audio`, `:start-card-timer`, `:undo`, `:deck-browser`,
  `:deck-overview`, `:deck-review`, `:import-file`, `:exit`, plus
  `GET /v1/gui/current-card` and `GET /v1/gui/selected-notes`.
- **`/v1/collection:*` and `/v1/profiles`** - `:sync`, `:export`, `:import`,
  `:reload`, `:check-database`; `GET /v1/profiles` and `POST /v1/profiles:load`.
- **GET `/v1/health`** - Simple health check (never requires an API key).

### AnkiConnect compatibility

`POST /` speaks AnkiConnect's protocol, so existing tools work unchanged —
point them at `http://127.0.0.1:7777` instead of `:8765`. Yomitan and
asbplayer are tested end to end. The shim is a thin translation over the same
adapters the `/v1` API uses, so there is no second path into Anki.

One practical difference worth knowing: every mutation goes through Anki's
`CollectionOp`, so writes land in the undo history and **work while the
browser is open with the note selected** — a case that fails against
AnkiConnect's legacy `startEditing()`/`stopEditing()` approach.

`GET /actions` lists the implemented actions. **119 of AnkiConnect's 122** are
in place — the three left out write to the database behind the scheduler's back
— see [docs/ankiconnect_parity.md](docs/ankiconnect_parity.md) for the full
table, the handful of deliberate behavioural deviations, and the two places
AnkiConnect's own documentation disagrees with its code.

**`/v1` is a superset.** Every action has a native equivalent, including the
GUI ones, so nothing requires the shim. It exists for tools you don't control.

**GET/POST parity**

Any GET query can be expressed as a POST to the same resource with `/query`:

```bash
# GET
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name' \
  --data-urlencode 'where=name==Basic' \
  --data-urlencode 'limit=20'

# POST (same query as JSON)
curl -X POST "http://127.0.0.1:7777/v1/models/query" \
  -H "Content-Type: application/json" \
  -d '{
        "select": "id,name",
        "where": ["name==Basic"],
        "limit": 20
      }'
```

## Event stream

`GET /v1/events` streams live collection events as Server-Sent Events
(`text/event-stream`) — no extra dependencies, works with `curl -N` and the
browser `EventSource` API. Delivery is live-only and best-effort: there is no
replay, and a client that falls behind gets a `reset` with
`"reason": "lagged"` after older events are dropped.

| Event | Payload (plus `seq`, `ts` epoch ms) | Meaning |
|---|---|---|
| `op` | `{"origin": "api"\|"ui"\|null, "changes": ["card", "note", ...], "label": "Update Note"}` | A completed operation; `changes` lists the true OpChanges flags and `label` (when known) is the localized name of the operation. `origin` is `"api"` for changes made through Tsunagi, `"ui"` when an Anki window acted on its own behalf, and `null` when Anki didn't attribute the operation to any window (many of its actions don't). |
| `review` | `{"card_id", "ease"}` | A card answered in Anki's reviewer. Fires just before the matching `op`. |
| `sync` | `{"phase": "started"\|"finished"}` | Sync lifecycle; a finished sync is followed by a `reset`. |
| `reset` | optionally `{"reason": "lagged"}` | Everything may have changed — refetch what you care about. |
| `close` | `{"reason": "shutdown"\|"timeout"\|"max_events"\|"auth"}` | Final frame before the stream ends. `auth` means the API key changed after this stream connected — reconnect with the current key. |

```bash
# Watch everything (Ctrl+C to stop); heartbeat comments every 15s
curl -N "http://127.0.0.1:7777/v1/events"

# Scripting: return after the next event or 30 seconds, whichever first
curl -N "http://127.0.0.1:7777/v1/events?max_events=1&timeout=30"
```

```js
// EventSource can't send headers, so this route also accepts ?api_key=.
// The page's origin must be in cors_allowlist.
const es = new EventSource("http://127.0.0.1:7777/v1/events?api_key=...");
es.addEventListener("review", (e) => console.log(JSON.parse(e.data)));
es.addEventListener("op", (e) => console.log(JSON.parse(e.data)));
```

**Events are invalidation signals, not change records.** Anki's change
events carry which *kinds* of thing changed, never record ids (its own UI
requeries on them too). The pattern is notify + refetch: on an `op` with
`"note"` in `changes`, ask the API what changed —

```bash
# Notes edited today / added today (Anki search syntax)
curl --get "http://127.0.0.1:7777/v1/notes" --data-urlencode 'search=edited:1'
curl --get "http://127.0.0.1:7777/v1/notes" --data-urlencode 'search=added:1'
```

— or simply refetch whatever your app is displaying. The `review` event is
the exception: it comes from a richer hook and carries the `card_id`
directly.

What you won't see: media writes and import/export run outside Anki's
change-tracking (no `op` fires), raw database edits by other addons are
invisible, some of Anki 23.10's own dialogs (e.g. deck options) don't route
through change-tracking either, and Tsunagi routes whose backend call
reports no change details are dropped as indistinguishable from no-ops.

## Roadmap

- Anki Connect parity + shim
- Event stream (SSE at `GET /v1/events`) — shipped, see above

If you want a specific endpoint or behavior, please open an issue.

## Contributing

PRs welcome! A good flow is:

1. Check or open an [issue](https://github.com/mcgrizzz/Tsunagi/issues) to discuss the approach.
2. Fork and create a feature branch.
3. Add tests if you’re touching behavior.
4. Run the checks and open a PR.

This is a solo project; I’ll review when I come up for air. Thoughtful bug reports are gold.

## Maintainers

[@mcgrizzz](https://github.com/mcgrizzz)

## License

License [MIT](LICENSE)

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
  --data-urlencode 'select=flds[].name' \
  --data-urlencode 'where=id in [1487718035000,1487718035001]'
```

If you need richer metadata, just ask for it:

```bash
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=flds[].(name,ord,description,font)'
```

No special endpoints, no throwaway filtering-just `select` what you want and go.

**Design goals, summarized**

- **Query planner** chooses the fastest route (index/column/full fetch).
- **Thread-safe** via Anki’s `QueryOp`/`CollectionOp`.
- **Typed I/O** with Pydantic.
- **Small query DSL** for filters + projections.
- **Cursor pagination** for large scans.
- **GET/POST parity** so URL queries and JSON bodies are equivalent.

I’m also planning an **AnkiConnect shim** so you can adopt this gradually without ripping anything out.

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

### Dependencies

Dependencies are bundled with the addon. I may pin to an earlier **pydantic** to avoid platform-specific wheels.

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
?where=sortf>=5

# Substring match (case-insensitive)
?where=name~=Basic

# Lists
?where=id in[123,456,789]
?where=name not in["Basic","Cloze"]

# Nested fields
# (example: filter models whose fields contain a field named "Front")
?where=flds[].name==Front

# Multiple filters (AND semantics; repeat the param)
?where=type==0&where=name~=medical
```

### Field Selection

```text
# Top-level fields
?select=id,name,type

# Array projection
?select=flds[].name

# Multi-field with aliases
?select=flds[].(name:label,ord:index)
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
| `shape`   | `string`  | `auto`   | `auto` (objects), `object` (always objects), `scalar` (single-field results as values). |
| `limit`   | `integer` | `1000`   | Items per page (1–5000). |
| `cursor`  | `string`  | -        | Opaque pagination cursor returned by the API. |

\* For POST JSON, you can pass a single string or an array of strings for `where`.

### Response Format

```json
{
  "items": [ { /* your data */ } ],
  "next_cursor": "eyJpZCI6NTAwfQ",
  "stats": { "duration_ms": 12.5 }
}
```

### Endpoints

- **GET `/v1/models`** - List/query note types (“models” in Anki terms).  
- **GET `/v1/health`** - Simple health check.

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

## Roadmap

- Anki Connect parity + shim
- Event stream (watch changes) /or websocket so you can listen for Card Added events, Card reviewed etc.

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

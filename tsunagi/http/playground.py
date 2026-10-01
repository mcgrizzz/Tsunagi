"""Scalar's browser integration and the shared API introduction."""

API_DESCRIPTION = """## Overview

Tsunagi provides a REST API for your running Anki collection. Browse the endpoints
in the sidebar, inspect their schemas and code examples, then choose **Test
Request** to edit parameters or a JSON body and send the request to Anki.

## Authentication

If you configured an API key in Tsunagi settings, enter it in **Authentication**.
Native endpoints accept `X-API-Key` or `Authorization: Bearer <key>`. Leave it blank
when authentication is disabled. The health endpoint is public. AnkiConnect RPC
uses its own `key` field in the JSON body.

## Core concepts

### Notes, cards and note types

Choose the resource that owns the data you want to work with:

**Notes** contain field values and tags. Use note endpoints to add or edit content.

**Cards** contain scheduling and review state. Use card endpoints to inspect due
dates or change scheduling.

**Models** are Anki's note types: the field definitions and templates that control
card structure and appearance.

A note can generate several cards. For example, a note type with forward and
reverse templates creates two cards from the same field values. Edit the note
to change their shared content; work with the cards to change their schedules.

### Find the data you need

For notes, cards and reviews, `search` accepts the same query syntax as Anki's
browser. Use `tag:verb` to find tagged content, or `deck:Japanese` to restrict a
query to a deck.

- **`search`** matches an Anki browser query, such as `tag:verb`.
- **`where`** filters resource fields: `mod>1790000000`, `name~=Basic` (names
  containing “Basic”), `model_name in ["Kiku","Kiku+"]`. Several `where`
  clauses must all match.
- **`select`** chooses returned fields: `select=id,name` returns
  `[{"id": 1, "name": "Basic"}, …]`, and `select=id` returns `[{"id": 1}, …]`.
  Add `shape=scalar` to get one field's bare values instead: `[1, …]`.
- **`order`** sorts: `order=due` or `order=note_modified:desc`. Cards and notes
  use Anki's Browser sorts, by their Browser names (`due`, `interval`, `ease`,
  `lapses`, `reviews`, `created`, `note_modified`, `deck`, `note_type`,
  `sort_field`, …), so `due` orders new, learning and review cards as the
  Browser does. Row fields that sort the same work too: `reps`, `mod`, and `id`
  on notes. Other resources sort by a field of their rows, such as
  `order=id:desc` for the newest reviews. Without `order`, rows come in
  ascending id.
- **`distinct_on`** keeps one row per value of a field, the first in `order`:
  `GET /v1/reviews?distinct_on=card_id&order=id:desc` is each card's latest
  review, and `distinct_on=note_id` on cards is one card per note. `where`
  applies first. On cards, notes and reviews it takes a column field, and every
  `where` clause must be on a column too; use `search` for the rest.
- **`limit`** sets the page size, such as `10`.
- **`cursor`** continues a query using the response's `next_cursor`.

A `where` clause is a field, an operator (`==`, `!=`, `~=`, `>`, `>=`, `<`, `<=`,
`in`, `not in`) and a value. Numbers, `true`, `false` and `null` are written as
in JSON. **Write text as a JSON string**, and a list as a JSON array, so any
name is safe, including quotes and backslashes: build the value with your
language's JSON encoder, such as `"model_name in " + JSON.stringify(names)` in
JavaScript or `"model_name in " + json.dumps(names)` in Python.

Check each endpoint for its supported fields and filters. In the request
console, enter parameter values directly; the client handles URL encoding.

### Choosing rows: `search` or `where`

Use `search` to choose cards and notes: it is Anki's own search, fast and with
Anki's rules. Use `where` for what search can't do: exact values in the rows
you get back, and resources Anki can't search, such as reviews and decks.

- Notes of a note type: `search=note:Kiku`
- Cards in a deck and its subdecks: `search=deck:Mining`
- Suspended cards: `search=is:suspended`
- Cards with an interval of 21 days or more: `search=prop:ivl>=21`
- Notes edited in the last 2 days: `search=edited:2`
- Notes edited since an exact moment: `search=edited:2&where=mod>=1790000000`
  (the search narrows quickly; `where` makes it exact to the second)
- Notes whose first field is a word: `where=first_field in ["食べる"]`, with
  `search=deck:Mining` to look in one deck only
- Reviews answered Again: `where=ease==1` on `/v1/reviews`; there, `search`
  chooses the cards whose reviews you get

### GET parameters or a JSON body

Many list endpoints also provide a **Query … (POST)** operation. Both forms
perform the same query. For example, these requests find up to ten notes tagged
`verb` and return their IDs:

```http
GET /v1/notes?search=tag%3Averb&select=id&limit=10
```

For `POST /v1/notes/query`, enter this JSON body:

```json
{
  "search": "tag:verb",
  "select": "id",
  "limit": 10
}
```

Use the POST query form when a JSON body is easier to compose. **Create note**
is a separate operation at `POST /v1/notes`.

### Read the next page

A paginated response has three parts:

- **`items`** holds the results on this page, shaped by your query.
- **`next_cursor`** is the token for the following page. A value of `null` means
  there are no more results.
- **`stats`** contains metadata about how the query was processed.

To continue, copy `next_cursor` into the next request's `cursor` parameter or
JSON property. Keep the search, filters, field selection and page size the same.
Treat the cursor as an opaque token: copy it as returned. Clear it when starting
a different query. A small `limit`, such as `10`, makes initial requests easier
to inspect.

### Check feature support and job status

`GET /v1/capabilities` reports all native operations in one place. Each operation
has a `status`: `available`, `disabled` for your app (its role lacks the
permission, or the app is turned off), or `unsupported` by this Anki version.
Conditional options carry the same status, plus a reason and the permission or
setting that controls them. AnkiConnect actions remain separate at `GET /actions`.

Look up an operation by method and path, such as
`operations["POST /v1/cards:set-memory-state"]`. FSRS scheduling appears under
`features.fsrs_scheduling`; computations that work while scheduling is off remain
available. See [native discovery](https://github.com/mcgrizzz/Tsunagi/blob/main/docs/capabilities.md)
for the response layout.

For an operation that returns an asynchronous job, use its returned job ID to
poll `GET /v1/jobs/{job_id}` for status and results.

### Errors

Tsunagi API route and validation errors are JSON with `detail`, a message you
can show. A 422 also lists each problem in `errors`, and a 503 says why in
`reason`: `busy`, `syncing` or `closed`. A request refused for its Host header
or website origin gets a plain-text 403 instead. The status says what to do:

| Status | Means | What to do |
| --- | --- | --- |
| 200, 201 | Done; 201 created something | |
| 202 | Accepted as a job | Poll `GET /v1/jobs/{job_id}` |
| 400 | The request's values are wrong: an unknown field, a bad search or cursor | Fix the request |
| 401 | No usable key | Send a valid key |
| 403 | The app's role lacks the permission (`detail` names it), or the app is off | Change the role on the settings page |
| 404 | What you named doesn't exist | |
| 409 | Valid, but it clashes with the collection: a name or id that's taken, a duplicate note, a job already running, a full sync Anki must do | Change the request, or wait |
| 422 | The body or parameters don't match the operation | Fix the request (`errors` lists each problem) |
| 500 | Tsunagi failed | Report it: it's a bug |
| 501 | This Anki version lacks the feature | Update Anki |
| 502 | AnkiWeb refused or couldn't be reached | Retry later |
| 503 | Anki is busy, syncing or has no profile open (`reason`) | Retry; a write may still finish |

A 503 doesn't cancel a write: Anki may still finish it. Send an
`Idempotency-Key` header (a new UUID per request) with any write, and the same
key when you retry it: the retry gets the first attempt's result, marked
`Idempotent-Replayed: true`, instead of writing again.

## Try a request

Start with `GET /v1/health`, or **Notes → List notes** with `limit=10`. Health
needs no key or open profile. Its `caller` says who the request counts as (app,
role) and whether its key is `valid`, `unknown` (counts as no key) or `none`,
so sending your key checks it.
The console sends real requests to your current Anki profile, including changes
when you use a write operation.

[Swagger](/docs) · [ReDoc](/redoc) · [OpenAPI JSON](/openapi.json)
"""

# Pin the standalone bundle so an upstream release cannot silently change the UI.
SCALAR_SCRIPT_URL = "https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.68.0/dist/browser/standalone.js"

PLAYGROUND_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tsunagi API reference</title>
  <style>body { margin: 0; } #loading { padding: 24px; font: 16px system-ui; }</style>
</head>
<body>
  <div id="loading">Loading Tsunagi API reference…
    <a href="/docs">Swagger</a> · <a href="/redoc">ReDoc</a> · <a href="/openapi.json">OpenAPI JSON</a>
  </div>
  <div id="app"></div>
  <script src="__SCALAR_SCRIPT_URL__"></script>
  <script>
    if (window.Scalar) {
      Scalar.createApiReference('#app', {
        url: '/openapi.json',
        baseServerURL: window.location.origin,
        layout: 'modern',
        modelsSectionLabel: 'Schemas',
        hideClientButton: true,
        persistAuth: false,
        withDefaultFonts: false,
        showDeveloperTools: 'never',
        agent: {disabled: true},
        mcp: {disabled: true},
        telemetry: false,
        authentication: {preferredSecurityScheme: 'ApiKey'},
        onLoaded: () => { document.getElementById('loading').hidden = true; }
      });
    } else {
      document.getElementById('loading').prepend('Could not load Scalar. Use one of the reference links below. ');
    }
  </script>
</body>
</html>'''.replace('__SCALAR_SCRIPT_URL__', SCALAR_SCRIPT_URL)

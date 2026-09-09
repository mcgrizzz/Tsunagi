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
- **`where`** filters resource fields. For models, `name~=Basic` matches names
  containing “Basic”.
- **`select`** chooses returned fields. Use `id` to return only IDs.
- **`limit`** sets the page size, such as `10`.
- **`cursor`** continues a query using the response's `next_cursor`.

Check each endpoint for its supported fields and filters. In the request
console, enter parameter values directly; the client handles URL encoding.

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

Available FSRS operations depend on the Anki version. Before using one, read
`GET /v1/capabilities` and check its `available` flag and `unsupported_options`.
FSRS being supported and FSRS being enabled in the collection are separate values.

For an operation that returns an asynchronous job, use its returned job ID to
poll `GET /v1/jobs/{job_id}` for status and results.

## Try a request

Start with `GET /v1/health`, or **Notes → List notes** with `limit=10`.
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

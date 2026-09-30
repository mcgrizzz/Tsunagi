# API reference and playground

While Anki is running, open **<http://127.0.0.1:7777/>** (your port, if you
changed it). It's an interactive reference of every endpoint, built from the
running server, where you can send real requests.

## Try a request

1. Pick an endpoint in the sidebar, or search for it.
2. Click **Test Request**, fill in the parameters or JSON body, and send it.
3. The actual response and HTTP status appear below.

A health check or a notes query with a small `limit` is a good first try.
Requests that change things change your real collection.

## Keys

- If your app has a key, enter it under **Authentication** (as `X-Api-Key` or
  a Bearer token). It isn't kept after the page reloads.
- `GET /v1/health` needs no key. Its `caller` says who a request counts as:
  the app and role, and whether its key is `valid`, `unknown` or `none`.
  AnkiConnect requests (`POST /`) take the key as `"key"` in the JSON body.
- A key that matches no app counts as no key, so on this computer a mistyped
  key still works with the no-key role. Health's `caller.key` is `unknown` then.
- **401** means Tsunagi found no usable key. **403** means the request isn't
  allowed; the response says why (except for AnkiConnect requests from a
  website that isn't allowed, which get an empty 403, as in AnkiConnect).
- Tsunagi API route and validation errors have `detail`, a message you can
  show; a **422** also lists each problem in `errors`. A refused Host header or
  website origin gets a plain-text 403.

## Other formats

Swagger UI is at `/docs`, ReDoc at `/redoc`, and the raw schema at
`/openapi.json`.

The reference page loads its viewer ([Scalar](https://scalar.com), pinned to
1.68.0) from jsDelivr, and Swagger UI and ReDoc load theirs from there too, so
all three need internet access unless your browser has them cached. The raw
schema at `/openapi.json` always works. Scalar's AI features and telemetry are
turned off.

## Page size

Queries and media listings return **every match when `limit` is left out**,
with `next_cursor: null`. `/v1/cards?select=id,note_id` returns those two fields
for every card.

To read a page at a time, add `limit`, such as
`/v1/cards?select=id,note_id&limit=100`. While `next_cursor` isn't `null`, send
the same query again with `cursor=<next_cursor>`. Leaving `limit` out on a
follow-up returns everything that's left.

- There's no upper limit; zero and negative limits are refused.
- Everything at once uses more memory; pages let your app show the first
  results sooner.
- Nothing is cached between pages: each page reads the current collection.

## Browser check (for contributors)

An optional Chromium check drives the real viewer against the generated
schema: parameters, JSON bodies, keys, responses, the server address, narrow
windows and a blocked download of the viewer. Install Playwright and Chromium
in a separate Python environment, then run:

```sh
TSUNAGI_BROWSER_PYTHON=/path/to/browser-env/bin/python \
  python -m pytest -q tests/test_playground.py
```

To run it offline, set `TSUNAGI_SCALAR_BUNDLE` to a downloaded copy of the
pinned viewer. The real page always loads the pinned version from jsDelivr.

# API reference and playground

Open Tsunagi's base URL (by default `http://127.0.0.1:7777/`) to use the
[Scalar API reference](https://scalar.com/products/api-references/integrations/html-js).
It reads the running server's `/openapi.json`, so endpoint navigation, parameter
and body schemas, response schemas and client code examples follow the API.

Select an endpoint in the sidebar or search for it. Choose **Test Request** to
open the console, edit query parameters or a JSON body, and send the request.
The console shows the actual response and HTTP status. Requests go directly to
the host and port of the page. Begin with a health check or a notes query with a
small limit. Write operations change the current Anki collection.

If an API key is configured, enter it in Scalar's **Authentication** control.
Native endpoints accept either `X-API-Key` or a Bearer token. Credentials are not
persisted across page reloads. The public health route does not require a key;
AnkiConnect RPC at `POST /` uses the `key` field in its JSON body.

The overview explains notes, cards, models, queries, pagination and capabilities.
Swagger remains at `/docs`, ReDoc at `/redoc`, and the schema at `/openapi.json`.
The Scalar browser bundle is pinned to version 1.68.0 and loaded from jsDelivr;
it requires internet access unless already cached. If it cannot load, reference
links remain visible. No Scalar proxy is configured; AI features and telemetry
are disabled.

## Choosing a page size

Collection queries and media listings default to `limit=1000`. Set a larger
positive limit when you want more data in one response, for example
`/v1/cards?select=id,note_id&limit=10000`; there is no fixed upper cap.
Larger pages reduce the number of requests but use more memory per response.
If `next_cursor` is not `null`, keep the same query and pass it as `cursor` to
get the remaining results. Smaller pages let your app process each chunk sooner.

## Browser verification

The optional Chromium check exercises the real Scalar bundle with the
application's generated schema and disposable responses: editable GET parameters,
POST JSON bodies, authentication, response display, the current server address,
credential reset, narrow layout and a blocked-CDN fallback.

Install Playwright and Chromium in a separate Python environment, then run:

```sh
TSUNAGI_BROWSER_PYTHON=/path/to/browser-env/bin/python \
  python -m pytest -q tests/test_compat_downloads.py tests/test_playground.py
```

For an offline browser test, set `TSUNAGI_SCALAR_BUNDLE` to a downloaded copy of
the pinned standalone bundle. The production page still loads the pinned CDN URL.

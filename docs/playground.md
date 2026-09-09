# API playground

Open Tsunagi's base URL (by default `http://127.0.0.1:7777/`) in a browser while
Anki is running. Start with **Find notes**:

1. Enter an Anki search, such as `tag:verb`, or leave it blank to browse notes.
2. Choose **Find notes** to see a page of results.
3. Choose **Show cards** beside a note to query its cards automatically.
4. Choose **Load next page** below the results to continue the current query.

The task picker also offers cards, decks, note types, review history, server
status, supported features, collection settings and other JSON read operations.
See [capabilities](capabilities.md) for the difference between FSRS support and
whether FSRS is enabled.

Search and page size appear first. **Advanced query options** contains field
selection, filters, response format and cursors. Array parameters such as field
filters accept one value per line. Queries start with 10 results per page;
changing a filter clears the cursor. Search example buttons fill the search
without sending it.

Results appear as rows with a short content preview. Expand **Full JSON
response** to see every returned field. **Request details** previews the current
form's URL and headers; **Request that produced these results** records the
request associated with the displayed response. Switching tasks clears the old
results. HTTP status and elapsed time appear above the results.

If authentication is enabled, open **API key (if required)** and enter your key.
It is sent in the `X-API-Key` header, redacted from displayed requests and kept
only until this page closes or reloads. A 401 response opens the key field.
Requests can be cancelled and time out after 30 seconds. Opening the page only
loads the schema; it does not query or change collection data.

Operations, parameter descriptions, required fields, types and defaults come
from the running server's `/openapi.json`. Reload the page after updating the
add-on to load its new schema. Requests use the page's host and port. Swagger at
`/docs` and ReDoc at `/redoc` provide the complete API, including writes, streaming
and file downloads.

## Browser verification

The optional browser check uses Chromium with disposable responses and the
application's generated OpenAPI schema. It checks search encoding, repeated
filters, pagination, required paths, authentication errors, cancellation,
schema changes, text rendering and a narrow viewport.

Install Playwright and its Chromium browser in a separate Python environment,
then run the tests from an environment with Tsunagi's normal test dependencies:

```sh
TSUNAGI_BROWSER_PYTHON=/path/to/browser-env/bin/python \
  python -m pytest -q tests/test_compat_downloads.py tests/test_playground.py
```

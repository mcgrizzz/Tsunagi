# API playground

Open Tsunagi's base URL (by default `http://127.0.0.1:7777/`) in a browser while
Anki is running. The landing page offers guided, editable read workflows:

- **Check runtime and capabilities:** inspect versions, supported FSRS operations
  and collection settings. Capability support and FSRS enablement are separate;
  see [capabilities](capabilities.md) before choosing an FSRS operation.
- **Find notes and their cards:** search notes with Anki syntax, then copy a note
  ID into the card search as `nid:<ID>`.
- **Browse collection data:** inspect decks, note types, cards and review history.
- **Explore all JSON read operations:** choose another JSON GET operation,
  including job status and GUI state. Streaming and file download endpoints are
  available through the API reference.

Choose a step, edit the parameters, then select **Send request**. Nothing runs
automatically except loading the OpenAPI schema. The page displays the request
URL and headers, HTTP status, elapsed time and response body. The response keeps
its own request snapshot when you change the form. API keys are sent in the
`X-API-Key` header, redacted from displayed requests and kept only in page memory.

Collection queries start with a limit of 10. Array parameters such as `where`
accept one value per line. **Next page** uses the returned cursor with the same
query; changing a filter clears the cursor. **Next step** selects the next
operation without sending it. Requests can be cancelled and time out after 30
seconds.

Operations, parameter descriptions, required fields, types and defaults come
from the running server's `/openapi.json`. Reload the page after updating the
add-on to load its new schema. Requests use the page's host and port. Swagger at
`/docs` and ReDoc at `/redoc` remain available for the full API, including writes.

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

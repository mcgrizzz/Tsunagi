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

- **Notes** hold fields and tags. **Models** (note types) define their fields and
  card templates. **Cards** are generated from notes and carry scheduling state.
- Collection queries support field selection (`select`), filters (`where`), and
  pagination (`limit`, `cursor`). Notes, cards and reviews also accept Anki browser
  search syntax through `search`, for example `tag:verb` or `deck:Japanese`.
- Paginated responses contain `items`, `next_cursor` and `stats`. Pass the returned
  cursor with the same query to get the next page. Begin with a small `limit`.
- Many queries offer both GET parameters and an equivalent POST JSON body.
- Check `/v1/capabilities` before using FSRS operations; supported operations and
  whether FSRS is enabled are reported separately. Async jobs are polled through
  `/v1/jobs/{job_id}`.

## Try a request

Start with **Health → Check health**, or **Notes → List notes** with `limit=10`.
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

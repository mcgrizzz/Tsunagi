# Tsunagi Configuration

Changes take effect after restarting Anki (or switching profiles).

### `enabled`
Set to `false` to stop Tsunagi from starting its server.

### `host`
Address the server binds to. Keep the default `127.0.0.1` (loopback only)
unless you know exactly what exposing Anki on your network means.

### `port` / `prefer_port`
- `port: 0` (default): use `prefer_port` (7777). If it's busy, Tsunagi shows a
  warning and does not start (no random fallback port).
- `port: <n>`: force a specific port; startup fails if it's busy.

### `api_key`
- Empty (default): **authentication is off** (same as AnkiConnect). The server
  only listens on loopback.
- Non-empty: every request must present the key.
  - REST API (`/v1/...`): send `X-Api-Key: <key>` or
    `Authorization: Bearer <key>` headers.
  - AnkiConnect endpoint (`POST /`): send a top-level `"key"` field in the
    JSON body (AnkiConnect convention). Missing/wrong key returns the
    canonical `"valid api key must be provided"` error.
  - The docs pages (`/docs`, `/openapi.json`) and the liveness probe
    (`/v1/health`) stay reachable without a key.

### `cors_allowlist`
Origins allowed to call Tsunagi from a browser. Requests from other origins
get a 403; requests without an `Origin` header (curl, scripts, desktop apps)
are unaffected.

The default `"http://localhost"` behaves exactly as it does in AnkiConnect:
besides `http://localhost` itself, it also allows `127.0.0.1` origins and
**all browser extensions** (`chrome-extension://`, `moz-extension://`,
`safari-web-extension://`). That's what lets extensions like Yomitan connect
with no setup. Remove it to require every extension to be listed explicitly.

Add website origins as full origins (e.g. `"https://example.com"`); `"*"`
allows everything. Entries are also added automatically when you click **Yes**
on the permission dialog (shown when a client calls the AnkiConnect
`requestPermission` action). Remove an entry to revoke access.

### `log_level`
Uvicorn log level (`critical`, `error`, `warning`, `info`, `debug`).

### `op_timeout_seconds`
How long a request may wait for Anki (busy with a dialog, sync, etc.) before
returning HTTP 503 instead of hanging.

### `media_max_bytes`
Largest file accepted by a media upload (default 64 MiB). Applies to base64
uploads, URL downloads, and local files alike.

### `media_fetch_timeout_seconds`
Timeout for downloading media from a URL (default 30).

### `media_allow_local_path`
When `true`, media uploads may name a file **on this computer** for the server
to read (`{"path": "C:/pictures/dog.png"}`), which is how AnkiConnect's
`storeMediaFile` behaves. Off by default: with it on, anything that can reach
the API can make Anki read any file your user account can read. Turn it on
only if you use local scripts that pass file paths. Base64 `data` and `url`
uploads work either way.

### `ankiconnect_import_offered` / `config_version`
Internal bookkeeping - don't edit. (`ankiconnect_import_offered` records that
the one-time "import settings from AnkiConnect" dialog was shown; set it back
to `false` to be offered again.)

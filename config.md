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
Website origins (e.g. `"https://example.com"`) allowed to call Tsunagi from a
browser. `"*"` allows every origin. Entries are added here automatically when
you click **Yes** on the permission dialog (triggered by a client calling the
AnkiConnect `requestPermission` action, e.g. Yomitan's connection test).
Remove an entry to revoke access.

### `log_level`
Uvicorn log level (`critical`, `error`, `warning`, `info`, `debug`).

### `op_timeout_seconds`
How long a request may wait for Anki (busy with a dialog, sync, etc.) before
returning HTTP 503 instead of hanging.

### `ankiconnect_import_offered` / `config_version`
Internal bookkeeping - don't edit. (`ankiconnect_import_offered` records that
the one-time "import settings from AnkiConnect" dialog was shown; set it back
to `false` to be offered again.)

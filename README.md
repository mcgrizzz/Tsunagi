# Tsunagi

Tsunagi (繋ぎ, “connection”) is an Anki desktop add-on that lets other apps read
and update your collection over HTTP. It provides a native API with field
selection, filters and pagination, plus an AnkiConnect-compatible API for
existing integrations.

The project is experimental. It targets Anki 23.10 and newer; individual features,
especially FSRS operations, depend on the running Anki version.

- [Install](#install)
- [Quick start](#quick-start)
- [Move from AnkiConnect](#move-from-ankiconnect)
- [Settings](#settings)
- [Query your collection](#query-your-collection)
- [Troubleshooting](#troubleshooting)
- [Developing Tsunagi](#developing-tsunagi)

## Install

Build an add-on package from this repository using Python 3.9 or newer with pip:

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
python tools/build_addon.py
```

The first build downloads the pinned runtime dependencies and creates
`dist/tsunagi-<version>.ankiaddon`. In Anki, open **Tools → Add-ons → Install from
file**, select that package, then restart Anki.

Runtime dependencies are bundled in the package. End users do not need to install
Python libraries into Anki. Tsunagi runs inside Anki and uses its active profile;
keep Anki open while using an integration.

## Quick start

1. Open **Tools → Tsunagi Settings**, or select Tsunagi in the add-ons window and
   choose **Config**. On **Connection**, enable the server and choose a port.
   A fresh configuration uses `127.0.0.1:7777`.
2. Choose **Save**, then open <http://127.0.0.1:7777/> in your browser. Substitute
   your configured port if you changed it or imported AnkiConnect settings.
3. In the Scalar API reference, try **GET /v1/health**, then list a small number
   of notes or note types. If you set an API key, enter it under **Authentication**.

The request console operates on your active Anki collection. Write operations
make real changes.

From a terminal, check the server and list up to ten note types:

```sh
curl "http://127.0.0.1:7777/v1/health"

curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name' \
  --data-urlencode 'limit=10'
```

These examples use a POSIX shell. In Windows PowerShell, use `curl.exe` for curl
and place each command on one line instead of using the shell continuations above.

When an API key is configured, add `-H "X-API-Key: YOUR_KEY"` to native API
requests. `Authorization: Bearer YOUR_KEY` is also accepted. The health check
remains accessible without a key.

The base URL serves [Scalar](docs/playground.md). Other reference formats are
available at `/docs` (Swagger), `/redoc` and `/openapi.json`.

## Move from AnkiConnect

Existing clients can use the AnkiConnect protocol at `POST /`. You can either
point them at Tsunagi’s host and port or import AnkiConnect’s connection settings:

1. Open Tsunagi Settings → **Connection**.
2. Choose **Import AnkiConnect settings**. This fills the API key and port and
   appends AnkiConnect’s website origins to your current list, removing duplicates.
   Unsaved origins already entered in the form are included.
3. Review the pending changes. **Save** disables AnkiConnect and stops its server
   before applying Tsunagi’s settings, allowing Tsunagi to take over the port.
   **Cancel** discards the pending import.

After a successful port handover, clients can keep their existing connection
address. If you use a different Tsunagi port, update the client accordingly.

AnkiConnect requests put the API key in the JSON body’s `key` property, rather
than the native API’s authentication header. For example, with authentication off:

```sh
curl "http://127.0.0.1:7777/" \
  -H "Content-Type: application/json" \
  -d '{"action":"version","version":6}'
```

`GET /actions` lists implemented actions. See the
[compatibility notes](docs/ankiconnect_parity.md) for coverage and intentional
behavior differences. The shim shares Tsunagi’s Anki adapters; compatibility
handling preserves action-specific arguments, results and errors.

## Settings

Changes on all tabs apply when you choose **Save**. Tsunagi restarts its API
server when needed; ordinary settings changes do not require restarting Anki.

| Tab | What you can change |
| --- | --- |
| **Connection** | Enable the server, host, preferred or fixed port, and AnkiConnect import. |
| **Access** | API key, allowed website origins, local-file access and FSRS memory-state permissions. |
| **Advanced** | Upload size, download and operation timeouts, and logging. |

**Ports:** only the numeric field for the selected mode is shown. Preferred mode
uses the saved preferred port; fixed mode uses the specified port. Neither mode
silently switches to another port if that port is busy.

**Access:** `127.0.0.1` accepts connections from this computer only. A blank API
key allows requests without a key. Website origins are entered one per line,
including the scheme, for example `https://app.asbplayer.dev`; `*` allows all
origins. Origin permission and API-key authentication are separate checks.

Local-file media access and rewriting FSRS memory state are off by default.
Enable them when an integration needs those capabilities. Their scope is
explained beside the controls.

**Restore all defaults** resets every tab and cancels a pending import. It changes
the form only until you choose Save. The underlying JSON keys, including developer
options, are documented in [config.md](config.md).

## Query your collection

Notes hold content and tags. Note types, called **models** in the API, define
fields and templates. Cards are generated from notes and hold scheduling state.
A note with forward and reverse templates produces two cards sharing that content.

For list endpoints that support querying:

| Parameter | Purpose |
| --- | --- |
| `select` | Choose returned fields, such as `id,name`. |
| `where` | Filter fields, such as `name~=Basic` for a case-insensitive substring. Repeat it to combine filters with AND. |
| `search` | Use Anki browser syntax on notes, cards and reviews, such as `tag:verb` or `deck:Japanese`. |
| `limit` | Set the page size; start with a small value such as `10`. |
| `cursor` | Continue using the previous response’s `next_cursor`. |

For example, retrieve note-type names and their field names in one request:

```sh
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name,fields[].name' \
  --data-urlencode 'limit=10'
```

Many list endpoints also accept a JSON query at `/query`. These two requests
find up to ten notes tagged `verb` and return their IDs:

```sh
curl --get "http://127.0.0.1:7777/v1/notes" \
  --data-urlencode 'search=tag:verb' \
  --data-urlencode 'select=id' \
  --data-urlencode 'limit=10'

curl "http://127.0.0.1:7777/v1/notes/query" \
  -H "Content-Type: application/json" \
  -d '{"search":"tag:verb","select":"id","limit":10}'
```

`POST /v1/notes/query` queries notes; `POST /v1/notes` creates one. Check the
reference for each endpoint’s supported parameters and operations.

Paginated responses contain `items`, `next_cursor` and `stats`. Copy a non-null
`next_cursor` into the next request’s `cursor`, keeping the other query parameters
the same. Stop at `null`. Treat cursors as opaque, and omit the cursor when starting
a new query. For large note/card queries, use `search` to narrow the candidates
before applying additional field filters.

Beyond collection queries, the API provides scheduling, media, review history,
GUI actions, import/export, profiles and FSRS operations. Read
[`/v1/capabilities`](docs/capabilities.md) before using version-dependent features:
operation availability and FSRS being enabled are reported separately. For an
asynchronous operation, poll `/v1/jobs/{job_id}` using its returned job ID.

`GET /v1/events` provides live Server-Sent Events for collection activity:

```sh
curl -N "http://127.0.0.1:7777/v1/events"
```

Use events to trigger a refresh of relevant data. Delivery is best-effort with no
replay; handle `reset` by refetching. Not every operation produces an event or an
undo entry. Consult the endpoint descriptions for behavior before relying on
undo, transactional writes or notifications.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Connection refused | Anki is open, a profile is loaded, the server is enabled, and the client uses the configured port. |
| Port is busy | Another process may own it. If that is AnkiConnect, use the settings import/Save handover, or choose distinct ports. |
| HTTP 401 or an API-key error | Match the configured key. Native requests use a header; AnkiConnect requests use the JSON `key` property. |
| A website is denied access | Check its origin on the Access tab, including scheme and any port. Supplying an API key does not grant origin permission. |
| A request times out or returns a busy error | Finish any blocking dialog or long-running operation in Anki, then retry. Operation timeout is on Advanced. |
| An FSRS feature is unavailable | Inspect `/v1/capabilities`; support depends on the Anki version and requested options. |
| The API works but Scalar does not load | Scalar’s browser bundle loads from a CDN. Check that connection, or use `/openapi.json` with another client. |

For a bug report, include the Anki version, operating system, action or endpoint,
expected behavior and the error response. Remove API keys and private note content.

## Developing Tsunagi

### Environment and build

Use a virtual environment from the repository root. This follows the CI setup:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install pytest ruff "httpx<0.28" anki
python tools/build_addon.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. On Python
3.9, install `anki==23.10` in place of `anki`; newer Anki packages need a newer
Python. The repository’s [CI configuration](.github/workflows/ci.yml) records its
version matrix.

The build vendors dependencies from [tools/requirements.lock.txt](tools/requirements.lock.txt)
into `lib/shared`, then packages the add-on into `dist`. It rebuilds those generated
directories and updates the build timestamp in `meta.json`. Anki itself is a test
dependency and is never bundled. After the wheel cache is populated,
`python tools/build_addon.py --offline` builds using cached wheels.

### Tests

Build first so the tests can import the vendored runtime dependencies, then run:

```sh
ruff check .
python -m pytest -q
```

Backend tests use temporary Anki collections. Optional Qt checks need a separate
interpreter with `aqt` and its Qt dependencies. For example, point the settings
check at that interpreter:

```sh
TSUNAGI_GUI_PYTHON=/path/to/qt-env/bin/python \
  python -m pytest -q tests/test_settings_dialog_qt.py
```

`tools/check_browser_startup.py`, `tools/check_add_cards.py` and other targeted
Qt checks can also run with that interpreter. The shared Qt smoke harness creates
a temporary profile. Use disposable profiles for development and GUI experiments.
Offscreen checks do not establish Windows foreground-window behavior.

The `tests/test_upstream_*.py` modules are an optional AnkiConnect parity audit.
They require an upstream checkout and are separate from ordinary regression
coverage. Keep new regressions focused; do not grow the broad oracle suite as a
substitute for testing Tsunagi behavior directly.

### Sync to a development installation

Install a built package first. To copy source changes into a chosen development
add-on folder:

```sh
python tools/dev_sync.py --dest /path/to/Anki2/addons21/tsunagi
```

Add `--watch` to keep copying source edits, or `--full` after rebuilding dependencies
to copy `lib/` too. Copying files and reloading the running add-on are separate steps:
restart Anki, or use the development reload options documented in [config.md](config.md).
Changes to the root `__init__.py` or bundled dependencies require a full restart.

### Code organization and contributions

- `tsunagi/http/` contains native routes, the AnkiConnect shim and HTTP middleware.
- `tsunagi/adapters/` integrates with Anki, including settings and operation dispatch.
- `tsunagi/shared/` contains schemas and shared query/error handling.
- `tools/` contains packaging, development sync and targeted checks.

Prefer Anki’s public APIs. Keep unavoidable database access in the adapter layer,
and account for the running Anki version. Use existing operation dispatch for
threading and undo behavior; GUI work belongs on the Qt main thread.

Discuss substantial changes in an [issue](https://github.com/mcgrizzz/Tsunagi/issues),
add focused tests for behavior changes, and include validation results in your PR.

## Maintainer and license

Maintained by [@mcgrizzz](https://github.com/mcgrizzz). Licensed under [MIT](LICENSE).

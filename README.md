<h1 align="center">Tsunagi</h1>
<p align="center"><strong>Connect your Anki collection to the tools you use.</strong></p>
<p align="center">
  <a href="#why-use-tsunagi">Why Tsunagi?</a> ·
  <a href="#install">Install</a> ·
  <a href="#move-from-ankiconnect">Switch from AnkiConnect</a> ·
  <a href="#api-guide">API guide</a> ·
  <a href="#developing-tsunagi">Development</a>
</p>

Tsunagi (繋ぎ, “connection”) is an Anki desktop add-on for dictionary tools, mining
apps and scripts. Keep using AnkiConnect integrations, or use the native API to
request related data together, select the fields you need and listen for changes.

> [!NOTE]
> Tsunagi is experimental and targets **Anki desktop 23.10 and newer**. Some
> features, especially FSRS operations, depend on your Anki version and settings.

## Why use Tsunagi?

[Don't care? Take me to setup.](#install)

### Keep your existing tools

The **AnkiConnect compatibility API** lets existing integrations connect to
Tsunagi. The settings importer copies your port and API key and merges allowed
websites, so your tools can keep their connection settings.

Compatibility requests use Tsunagi's internal routing and shared Anki adapters,
so **existing tools may see performance benefits too**. Any speedup depends on
the requests and your collection. See the [compatibility notes](docs/ankiconnect_parity.md)
for action coverage and known differences.

### Ask for the data your app needs

Tsunagi grew out of work on [Yomine](https://github.com/mcgrizzz/Yomine), where
fetching related Anki data meant combining several results and discarding fields
the app didn't need. The native API gives apps more control over those requests:

| Feature | What it lets your app do |
| --- | --- |
| **Field selection and filters** | Fetch names and IDs for a note-type picker, or include field definitions for an editor. |
| **Related data in one query** | Request note types and their field names together. |
| **Pagination and Anki search** | Work through large collections in small pages; narrow notes, cards and reviews with browser search syntax. |
| **Collection events** | Refresh relevant data when activity occurs, instead of repeatedly checking for changes. |
| **Interactive API reference** | Explore requests and check which operations are available, disabled in settings or unsupported. |

For note types and their fields, an AnkiConnect workflow typically asks for the
type names, then fields for each type. `multi` can batch actions, but the app still
assembles the results. Tsunagi can return them in [one query](#query-your-collection).

These native features need an app that uses them. Switching add-ons alone won't
give an existing AnkiConnect client the new queries, pagination or event stream.
You can use both kinds of integration together.

## Install

Install Tsunagi in **Anki desktop** using its AnkiWeb add-on code:

**Add-on code:** `<ANKIWEB_ADDON_ID>` *(placeholder until publication)*

1. In Anki, open **Tools → Add-ons → Get Add-ons**.
2. Paste the code above and click **OK**.
3. Restart Anki, then follow the [quick start](#quick-start).

<details>
<summary>Build the installation file from source</summary>

With Git and Python 3.9 or newer (including pip) installed, run:

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
python tools/build_addon.py
```

The build downloads and bundles the required libraries. In Anki, open
**Tools → Add-ons → Install from file** and select
`dist/tsunagi-<version>.ankiaddon`. Restart Anki, then follow the
[quick start](#quick-start). No separate library installation inside Anki is needed.

</details>

## Quick start

> [!TIP]
> Already using AnkiConnect? Follow [Move from AnkiConnect](#move-from-ankiconnect)
> to copy your settings and switch servers when you save.

For a fresh setup:

1. Open **Tools → Tsunagi Settings**.
2. On **Connection**, leave **Enable Tsunagi server** checked and keep the default
   host and preferred port. Click **Save**.
3. Open **<http://127.0.0.1:7777/>**. Seeing the interactive API reference confirms
   that Tsunagi is reachable.
4. In your tool, set the Anki connection address to **`http://127.0.0.1:7777`**.
   If it asks for a port separately, enter **`7777`**.

Keep Anki open with the profile you want to use. If you change the port or set an
API key under **Access**, use those same values in your tool.

You don't need to write API requests for existing integrations. To explore the API,
choose an operation in the reference and use **Test Request**. Start with the
health check or a small note query.

> [!IMPORTANT]
> The reference connects to your open Anki collection. Requests that add, edit or
> delete data act on that collection; this is not a separate sample environment.

## Move from AnkiConnect

1. Open **Tools → Tsunagi Settings → Connection**.
2. Click **Import AnkiConnect settings**.
3. Review the filled-in values and pending-change summary.
4. Click **Save** to switch over, or **Cancel** to leave your setup as it was.

| Setting | What happens |
| --- | --- |
| **Port and API key** | Copied from AnkiConnect so tools can keep using the same address and key. |
| **Allowed websites** | Added to your existing list, including unsaved entries, with duplicates removed. |
| **AnkiConnect server** | Disabled and stopped on Save, before Tsunagi takes over the port. |

Nothing switches over until you save. If you change the imported port or key,
update your tools too. See [compatibility notes](docs/ankiconnect_parity.md) for
known differences between the two add-ons.

## Settings

Open **Tools → Tsunagi Settings**, or select Tsunagi under **Tools → Add-ons** and
click **Config**.

| Tab | What you'll find |
| --- | --- |
| **Connection** | Server on/off, host and port, AnkiConnect settings import. |
| **Access** | API key, allowed websites, local-file access and FSRS memory-state permissions. |
| **Advanced** | Media limits, timeouts and logging. |

**Save** applies every tab and restarts the server if needed. **Cancel** discards
unsaved changes. **Restore all defaults** resets every tab and cancels a pending
AnkiConnect settings import; review the values before saving.

- **Address and port:** for tools on the same computer, keep `127.0.0.1`.
  Preferred and fixed port modes both use the number shown and report a conflict
  if it's busy; they don't silently choose another port.
- **API key:** an optional shared secret. Leave it blank to turn authentication
  off, or enter the same key in Tsunagi and your tool.
- **Allowed website origins:** one address per line, including `http://` or
  `https://` and any port, but no page path. For example, `https://app.asbplayer.dev`.
  Website permission and an API key are separate checks.
- **Optional permissions:** local media paths and rewriting FSRS memory state
  start disabled. Enable them when an integration needs them.

For the underlying configuration keys and development reload options, see
[config.md](config.md).

## Troubleshooting

| What you see | What to check |
| --- | --- |
| **Tool cannot connect** | Keep Anki open with a profile loaded. Confirm Tsunagi is enabled and the tool uses the same port. |
| **Port already in use** | Use the AnkiConnect settings importer to take over its port, or choose a free port and update your tool. |
| **401 / API key error** | Enter the same API key in Tsunagi and the tool. |
| **Website denied access** | Add its origin under Access, including the scheme and port. An API key alone doesn't grant website permission. |
| **Anki busy / request timed out** | Finish open prompts or long-running work. For a package import that returned a job ID, poll that job instead of submitting it again. |
| **FSRS operation unavailable** | Check the native capabilities report in the API reference for a settings explanation or an Anki-version restriction. |
| **API reference won't load** | Its interface loads from an online CDN. The local API can still work without the reference page. |
| **Anki window stays behind another app** | Windows may flash Anki's taskbar button instead of allowing it to take focus. Bring the window forward through the taskbar. |

For unresolved problems, [open an issue](https://github.com/mcgrizzz/Tsunagi/issues)
with your Anki version, operating system and the request or tool involved.
Remove API keys and private note content from examples.

## API guide

The **[Scalar reference](docs/playground.md)** at <http://127.0.0.1:7777/> is the
full operation catalogue. It includes notes, cards, models, decks, scheduling,
media, review history, GUI actions, import/export, profiles and FSRS tools.

| Entry point | Purpose |
| --- | --- |
| `GET /v1/health` | Check that the server responds; no API key required. |
| `GET /v1/capabilities` | One report of native operations, feature states and restricted options. |
| `POST /` | AnkiConnect action requests. |
| `GET /actions` | AnkiConnect action inventory. |
| `/openapi.json` | OpenAPI schema; `/docs` and `/redoc` offer alternative reference views. |

### Authentication

When an API key is set, native requests accept `X-API-Key: YOUR_KEY` or
`Authorization: Bearer YOUR_KEY`. AnkiConnect requests carry it in the JSON
body's `key` property. The examples below assume authentication is off.

Shell examples use POSIX syntax. In Windows PowerShell, use `curl.exe` and put
each command on one line instead of using shell continuations.

### Query your collection

**Notes** hold fields and tags. **Models** (note types) define fields and card
templates. **Cards** are generated from notes and hold scheduling state.

Fetch note-type names and their field names together:

```sh
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name,fields[].name' \
  --data-urlencode 'limit=10'
```

For list endpoints that support querying:

| Parameter | Purpose |
| --- | --- |
| `select` | Choose returned fields, such as `id,name`. |
| `where` | Filter fields, such as `name~=Basic` for a case-insensitive substring. Repeat filters to combine them with AND. |
| `search` | Use Anki browser syntax on notes, cards and reviews, such as `tag:verb` or `deck:Japanese`. |
| `limit` | Set the page size; start small, for example `10`. |
| `cursor` | Continue with the previous response's `next_cursor`. |

Paginated responses contain `items`, `next_cursor` and `stats`. Keep the query
unchanged when passing a cursor, stop at `null`, and omit the cursor to start a
new query. Treat cursor values as opaque. For large note/card queries, use
`search` to narrow candidates before applying additional field filters.

<details>
<summary>Equivalent GET and POST query examples</summary>

These requests return up to ten IDs of notes tagged `verb`:

```sh
curl --get "http://127.0.0.1:7777/v1/notes" \
  --data-urlencode 'search=tag:verb' \
  --data-urlencode 'select=id' \
  --data-urlencode 'limit=10'

curl "http://127.0.0.1:7777/v1/notes/query" \
  -H "Content-Type: application/json" \
  -d '{"search":"tag:verb","select":"id","limit":10}'
```

Many list endpoints have a `/query` counterpart. `POST /v1/notes/query` queries
notes; `POST /v1/notes` creates a note. Check each route's supported parameters.

</details>

### Discover features and follow changes

[`GET /v1/capabilities`](docs/capabilities.md) reports whether each native operation
is **available**, **disabled in settings** or **unsupported by your Anki version**.
Restricted options include reasons and relevant setting names.

`GET /v1/events` streams collection activity using Server-Sent Events:

```sh
curl -N "http://127.0.0.1:7777/v1/events"
```

Use events to trigger a refresh. Delivery is best-effort with no replay; handle
`reset` by refetching. Not every operation produces an event or an undo entry.
Consult the operation description before relying on notifications or undo.

### Import UI versus package import

| Request | What its response means |
| --- | --- |
| Native `POST /v1/gui:import-file` | Anki accepted the request to open the import UI. It doesn't wait for file selection or import completion; no job ID is created. |
| AnkiConnect `guiImportFile` | Anki's initial GUI call returned, usually after file selection or cancellation. It doesn't guarantee the import finished. |
| Native `POST /v1/collection:import` | **200** returns import counts; **202** returns a job ID if the import outlasts the operation timeout. |

Both GUI requests accept an optional path to skip the picker. The compatibility
request has a dispatch timeout, but time spent interacting with the accepted
dialog has no operation deadline. Your HTTP client can still impose its own timeout.

Programmatic package imports use saved Anki options unless explicitly overridden.
For a **202** response, poll `/v1/jobs/{job_id}` using the ID or `Location` header;
the same import continues. `done` includes counts in `result`; `failed` includes
an `error`. **Poll rather than resubmitting the import.**

Import jobs have no progress or abort API. They share a single active job slot
with FSRS; another submission returns **409**. Records are held in memory and
lost on restart or add-on reload. Set your client timeout longer than Tsunagi's
operation timeout to allow the job response to arrive. The AnkiConnect
`importPackage` response contract is unchanged.

### AnkiConnect requests

For example, ask for the supported protocol version:

```sh
curl "http://127.0.0.1:7777/" \
  -H "Content-Type: application/json" \
  -d '{"action":"version","version":6}'
```

The shim shares Tsunagi's Anki adapters while preserving action-specific
arguments, results and errors. See the [compatibility notes](docs/ankiconnect_parity.md).

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
into `lib/shared`, then packages the add-on into `dist`. It rebuilds `lib/` and
replaces the archive for the current version after validation. Anki itself is a test
dependency and is never bundled. After the wheel cache is populated,
`python tools/build_addon.py --offline` builds using cached wheels.

### Package for AnkiWeb

Keep the release version in `tools/version.py`, `tsunagi/shared/version.py` and
`pyproject.toml` aligned, then run from the repository root:

```sh
python tools/build_addon.py
```

The script prints the upload path and creates two files:

| File | Purpose |
| --- | --- |
| `dist/tsunagi-<version>.ankiaddon` | Upload this file to [AnkiWeb](https://ankiweb.net/shared/addons/). It also works with **Install from file**. |
| `dist/tsunagi-<version>.ankiaddon.sha256` | SHA-256 checksum for verifying the package. |

The package includes runtime code, assets, bundled dependencies and license notices.
It excludes local `meta.json`, bytecode, development tools, tests and handoff docs.
The script checks required files, JSON and ZIP integrity before replacing a previous
package. It does not upload anything. Use `--offline` to reuse cached dependencies
or `--refresh` to download them again; these options cannot be combined.

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

The broad AnkiConnect comparison suite is archived in Git at `eea649e`:
`tests/test_upstream_differential.py`, `tests/test_upstream_decks.py`,
`tests/test_upstream_permissions.py` and `tests/upstream_support.py`. It established
compatibility against pinned upstream code; routine tests retain focused Tsunagi
regressions and action-inventory checks. For a specific renewed comparison, recover
that revision in a separate checkout and set `TSUNAGI_ANKICONNECT_CHECKOUT` to the
upstream checkout. The broad audit is not part of the maintained test suite.

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

### Code organization

- `tsunagi/http/` contains native routes, the AnkiConnect shim and HTTP middleware.
- `tsunagi/adapters/` integrates with Anki, including settings and operation dispatch.
- `tsunagi/shared/` contains schemas and shared query/error handling.
- `tools/` contains packaging, development sync and targeted checks.

Prefer Anki’s public APIs. Keep unavoidable database access in the adapter layer,
and account for the running Anki version. Use existing operation dispatch for
threading and undo behavior; GUI work belongs on the Qt main thread.

# Tsunagi

Tsunagi (繋ぎ, "connection") connects your Anki desktop collection to other apps.
Dictionary tools, mining apps and your own scripts can use it to add notes, look
up cards and work with Anki without doing everything by hand.

Tools can connect through the AnkiConnect compatibility API or use Tsunagi's
native API to choose, filter and page through Anki data.

The project is experimental and targets Anki 23.10 and newer. Some features,
especially FSRS tools, depend on your Anki version.

- [Why use Tsunagi?](#why-use-tsunagi)
- [Install](#install)
- [Quick start](#quick-start)
- [Move from AnkiConnect](#move-from-ankiconnect)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)
- [Query your collection](#query-your-collection)
- [Developing Tsunagi](#developing-tsunagi)

## Why use Tsunagi?

[Don't care? Take me to setup.](#install)

Tsunagi grew out of work on [Yomine](https://github.com/mcgrizzz/Yomine). AnkiConnect
could provide the data the app needed, but getting related information often meant
several actions, combining their results, and throwing away the parts that weren't
needed. Tsunagi lets the app ask for that information together.

Take note types and their field names. With AnkiConnect, a typical workflow asks
for the note-type names, then the fields for each type. You can batch those actions
with `multi`, but the app still has to assemble the results. Tsunagi can return the
note types and their fields in one query. The [example below](#query-your-collection)
shows what that looks like.

There are other benefits for apps using the native API:

- Choose which fields come back, and filter the results before they reach your
  app. A note-type picker might need just names and IDs; an editor can ask for
  field definitions too. The app receives the fields it needs without downloading the rest.
- Read a large collection a page at a time. Ask for ten results, then continue
  from where you left off. You can use Anki's search syntax to narrow the query.
- Listen for collection activity instead of repeatedly checking for changes.
  The event stream tells an app when it should refresh its data. Delivery is
  best-effort, so it isn't a complete change history.
- Work with scheduling, media, review history and FSRS computations. The API
  reports which features your Anki version supports, and the interactive reference
  lets you try a request before writing code.

Existing AnkiConnect integrations can connect through Tsunagi's compatibility
API. The settings importer copies their connection settings so you can keep the
same address. See the [compatibility notes](docs/ankiconnect_parity.md) for known
differences.

The new queries, pagination and events are part of Tsunagi's native API. An
existing AnkiConnect client won't start using them just because you switch
add-ons. If your current setup does everything you need, you may have little
reason to change it. Tsunagi lets you keep those integrations while using apps
that use the new queries and event stream.

## Install

You need Anki desktop and a Tsunagi installation file ending in `.ankiaddon`.
The installation method documented here uses a package built from this repository.
If you do not have that file yet, expand the build instructions below.

<details>
<summary>Build the installation file from source</summary>

You will need Git and Python 3.9 or newer with pip. Run these commands in a terminal:

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
python tools/build_addon.py
```

The build downloads the required libraries and puts the installation file in the
`dist` folder, named `tsunagi-<version>.ankiaddon`.

</details>

Once you have the file:

1. Open Anki and choose **Tools → Add-ons**.
2. Click **Install from file** and select the `.ankiaddon` file.
3. Restart Anki.

The package includes the libraries it needs. You do not need to install anything
else inside Anki.

## Quick start

**Already using AnkiConnect?** Follow [Move from AnkiConnect](#move-from-ankiconnect)
to copy your existing connection settings.

For a fresh setup:

1. Open **Tools → Tsunagi Settings** in Anki.
2. On **Connection**, leave **Enable Tsunagi server** checked. Keep the default
   host and preferred port unless your tool needs different settings.
3. Click **Save**.
4. Open <http://127.0.0.1:7777/> in your browser. You should see Tsunagi's
   interactive API reference. This confirms that the server is reachable.
5. In the tool you want to connect, set its Anki connection address to
   `http://127.0.0.1:7777`. If it asks for a port separately, enter `7777`.

Keep Anki open while using your connected tools. They work with the profile
currently open in Anki.

If you chose a different port, replace `7777` in the address with that number.
If you set an API key on the **Access** tab, enter the same key in your tool's
connection settings.

You do not need to write requests to use an existing integration. If you want to
explore the API yourself, the [interactive reference](docs/playground.md) lets you
choose an operation and use **Test Request**. Start with the health check or a
small list of notes. Requests that add, edit or delete data affect your real
collection.

## Move from AnkiConnect

The importer copies your connection settings so existing tools can keep using
the same address.

1. Open **Tools → Tsunagi Settings → Connection**.
2. Click **Import AnkiConnect settings**.
3. Review the filled-in settings and the pending-change summary.
4. Click **Save** to switch over, or **Cancel** to leave your setup as it was.

The import copies AnkiConnect's API key and port. It **adds** its allowed websites
to your current list, including entries you have just typed. It removes duplicates
and keeps your existing entries.

Nothing switches over until you save. Saving disables AnkiConnect and stops its
server before Tsunagi takes over the port. After a successful switch, your tools
can keep their existing address and key. If you choose a different port or key,
update those settings in the tools too.

For action coverage and known differences, see the
[AnkiConnect compatibility notes](docs/ankiconnect_parity.md).

## Settings

Open **Tools → Tsunagi Settings**, or select Tsunagi in **Tools → Add-ons** and
click **Config**. There are three tabs:

| Tab | Use it to… |
| --- | --- |
| **Connection** | Turn the server on or off, change its address or port, and import AnkiConnect settings. |
| **Access** | Set an API key, allow websites to connect, and enable optional permissions. |
| **Advanced** | Change file-size limits, how long requests can wait, and logging. |

**Save** applies changes from every tab. Tsunagi restarts its server if needed;
you normally do not need to restart Anki. **Cancel** discards unsaved changes.

### Address and port

For tools running on the same computer, keep the host at `127.0.0.1`.
The port is the number after the colon in the connection address, such as `7777`.

Choose **Use preferred port** or **Use a fixed port**, then enter the number in
the field shown. Both modes use that number; Tsunagi will report a problem if it
is already in use instead of silently picking another one.

### Keys and allowed websites

An **API key** is a shared secret that your tool sends when it connects. Leave it
blank if you do not want to require a key. If you set one, use the same value in
both Tsunagi and the tool.

**Allowed website origins** controls which websites can connect. Enter the address
where the tool runs, one per line. For example, `https://app.asbplayer.dev`. Include
`http://` or `https://` and any port, but no page path. A key and website permission
are separate: a website needs permission even if it knows your key.

The optional permissions let tools read local media files by path or rewrite FSRS
memory state. They start off and have explanations beside them; enable one when
an integration needs it.

### Restore defaults

**Restore all defaults** resets every tab and cancels a pending AnkiConnect import.
You can review the reset values before saving, or choose Cancel to keep your saved
settings. For the underlying configuration keys, see [config.md](config.md).

## Troubleshooting

| What you see | What to try |
| --- | --- |
| Your tool cannot connect | Keep Anki open with a profile loaded. Check that Tsunagi is enabled and that the tool uses the same port. |
| The port is already in use | If AnkiConnect is using it, use the import steps above to switch over. Otherwise, choose a free port and update your tool's address. |
| A key error or "401" | Copy the API key from Tsunagi into your tool's connection settings. |
| A website is denied access | Add the website's address under Access, including `https://` or `http://` and any port. An API key alone does not allow a website. |
| A request times out or Anki is busy | Finish any open prompt or long-running task in Anki, then try again. |
| An FSRS feature is unavailable | The feature may need a newer Anki version. Look for capabilities in the API reference to check which operations are available. |
| The reference page does not load | Its interface loads from an online CDN. Check your internet connection; the local API can still work even if that page fails to load. |

When reporting a bug, include your Anki version, operating system, the tool or
operation you were using, and the error message. Remove API keys and private note
content.

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
[`/v1/capabilities`](docs/capabilities.md) for one report of native operations:
each entry says whether it is available, disabled in settings, or unsupported by
your Anki version. Restricted options include a reason and the setting to change. For an
asynchronous operation, poll `/v1/jobs/{job_id}` using its returned job ID.

`GET /v1/events` provides live Server-Sent Events for collection activity:

```sh
curl -N "http://127.0.0.1:7777/v1/events"
```

Use events to trigger a refresh of relevant data. Delivery is best-effort with no
replay; handle `reset` by refetching. Not every operation produces an event or an
undo entry. Consult the endpoint descriptions for behavior before relying on
undo, transactional writes or notifications.

### Authentication and AnkiConnect requests

The examples above use a POSIX shell. In Windows PowerShell, use `curl.exe` for
curl and place each command on one line instead of using shell continuations.

When an API key is configured, add `-H "X-API-Key: YOUR_KEY"` to native API
requests. `Authorization: Bearer YOUR_KEY` is also accepted. The health check
at `/v1/health` remains accessible without a key.

AnkiConnect requests go to `POST /` and put the key in the JSON body's `key`
property. For example, with authentication off:

```sh
curl "http://127.0.0.1:7777/" \
  -H "Content-Type: application/json" \
  -d '{"action":"version","version":6}'
```

`GET /actions` lists implemented actions. The shim shares Tsunagi's Anki adapters;
compatibility handling preserves action-specific arguments, results and errors.
The API reference is also available at `/docs` (Swagger), `/redoc` and
`/openapi.json`.

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

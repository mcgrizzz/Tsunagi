# Tsunagi Configuration

The usual way to change these settings is the **settings page**: the Config
button on the add-on, or Tools → Tsunagi Settings. It opens inside Anki and
talks to Tsunagi directly, not through the API, so no API client, website or
card template can read or change these settings. This page documents the
underlying keys, which you can still edit as JSON in `meta.json` if you
prefer.

Saving the settings page applies Tsunagi settings immediately: per-request keys
(`apps`, `roles`, the `no_key_*` roles, `cors_allowlist`, the `media_*`
limits and `gates`) are simply
read live, and server-level keys (`enabled`, `host`, `port`, `prefer_port`,
`log_level`, `op_timeout_seconds`) are applied by restarting the embedded
server on the spot. If you edit `meta.json` as JSON instead, the server-level
keys only take effect after restarting Anki (or switching profiles);
`dev_watch_seconds` always needs an Anki restart.

The **AnkiConnect** section shows whether the standard AnkiConnect addon is
installed and enabled, and when settings were last imported. **Import AnkiConnect settings** stages its
API key, port and allowed website origins into the form, and selects **Enable
Tsunagi server**. Review the values and click **Save** to disable AnkiConnect, stop
its current listener, and start Tsunagi on the imported port. **Cancel** leaves
both addons unchanged, and so does **Revert this page** on the AnkiConnect page.
The last-import date is saved with a successful import and remains visible after
AnkiConnect is disabled or removed. Importing again updates that date; ordinary
settings edits and restoring defaults preserve it. Older imports have no date
record and are shown as unavailable history.
The explicit takeover imports `webBindPort` (normally 8765) into both **Port**
and **Preferred port**. Existing allowed origins, including unsaved form entries,
are retained; imported origins are appended without duplicates. Optional capability
gates are unchanged. The separate startup import-only offer keeps Tsunagi's port
because that offer leaves AnkiConnect running. AnkiConnect's API key becomes the
key of the app **AnkiConnect key**; an empty AnkiConnect key does not replace an
existing one. The standard AnkiConnect timer and listener are stopped before Tsunagi restarts.
If the selected port is still occupied, the handover is cancelled and the prior
addon state is restored. An unsupported AnkiConnect runtime requires a manual
disable and Anki restart before importing. Detection alone never disables it.

### `enabled`
Set to `false` to stop Tsunagi from starting its server.

### `host`
Address the server binds to. Keep the default `127.0.0.1` (loopback only)
unless you know exactly what exposing Anki on your network means.

Any address other than loopback (for example `0.0.0.0` to use Tsunagi from
your phone) lets other devices on your network connect. They get **No
access** unless they send an app's key (see below), because
`no_key_remote_role` is `none` by default.

Requests must name a loopback address (`localhost`, a loopback IP, or `[::1]`),
the configured host, or, when bound beyond loopback, any plain IP address such
as this computer's LAN address in their `Host` header. Other names receive
HTTP 403, even when their browser origin is allowed; this blocks DNS
rebinding, which always uses a domain name. Forwarded-host headers do not
override this check. Names listed in `allowed_hosts` are also accepted.

If another device still cannot connect, the operating system's firewall is the
usual cause. On Windows, Anki is typically allowed on networks marked
**Private** and blocked on **Public** ones: mark your home network as Private
(Settings → Network & internet → your network → Network profile type).

### `allowed_hosts`
Host names this computer is reached by through a proxy running on it, such as
Tailscale Serve (`["pc.tailnet.ts.net"]`; default `[]`). The `Host` check
above also accepts them. Bare names only: no `http://`, no port. In the
settings page: **Server → Other host names**. Applies immediately.

Tailscale Serve passes the name the phone used as `Host` (checked live), so
until its name is listed here Tsunagi answers 403 "Disallowed Host header".
A request that a proxy forwarded never counts as **this computer**, even with
a loopback `Host`: Tsunagi looks for `Tailscale-User-Login` (Serve always adds
it and removes any a client sends) and the usual `Forwarded`, `X-Forwarded-For`,
`X-Forwarded-Host` and `X-Real-IP` headers. So keyless requests through Serve
get `no_key_remote_role` (**No access** by default). See
[Remote access](docs/remote_access.md).

### `port` / `prefer_port`
- `port: 0` (default): use `prefer_port` (7777). If it's busy, Tsunagi shows a
  warning and does not start (no random fallback port).
- `port: <n>`: force a specific port; startup fails if it's busy.

### Apps and permissions: `apps`, `roles`, `no_key_local_role`, `no_key_remote_role`, `addon_enabled`

Every request comes from an **app** or from one of two **No key** rows, and
each has a **role** that decides what it may do. The defaults behave like
AnkiConnect: programs on this computer need no key and can do everything
AnkiConnect allows; other devices need a key.

- `apps` (default `[]`): `[{"name": "Yomitan", "key": "...", "role": "default"}]`.
  An app sends its key as `X-Api-Key: <key>` or `Authorization: Bearer <key>`
  on `/v1/...`, as `?api_key=<key>` on `/v1/events` only, or as the top-level
  `"key"` field on the AnkiConnect endpoint (`POST /`). On the settings page,
  **Apps & keys → Add app** creates one with a random 32-character key and
  copies it; **New key** replaces a key.
- `no_key_local_role` (default `"default"`): the role for requests without a
  key from **this computer**, meaning the connection comes from a loopback
  address and the `Host` names one (`127.0.0.1`, `localhost`, `[::1]`). Set it
  to `"none"` to make every local program use a key.
- `no_key_remote_role` (default `"none"`): the role for requests without a
  key from anywhere else, including through a local proxy such as Tailscale
  Serve. Anything other than `"none"` lets anyone who can reach the port use
  that role without a key.
- A key that matches no app counts as no key, as in AnkiConnect.
- A request without a key whose role is `none` gets HTTP 401 (`/v1/...`) or
  `"valid api key must be provided"` (`POST /`). A request whose role lacks
  what the route needs gets HTTP 403 naming the app, the role and the
  missing permission, or the same text as the AnkiConnect `error`.
- The docs pages (`/docs`, `/openapi.json`) and `/v1/health` need no key.

Built-in roles:

| Role id | Name | Grants |
| --- | --- | --- |
| `default` | Default (like AnkiConnect) | `read`, `write`, `gui`, `sync`, `manage`, `events:changes`, enabled `normal` add-on actions |
| `read_only` | Read-only | `read`, `events:changes` |
| `everything` | Everything | every permission, including every enabled add-on action |
| `none` | No access | nothing |

`roles` (default `{}`) adds your own roles or replaces a built-in one under
the same id: `{"tagger": {"name": "Tagger", "grants": ["read", "write:tags"]}}`.
An app whose role does not exist gets nothing.

A grant is a whole area or one name in it. Each route in the API reference
shows the permission it needs (`x-permission`).

| Area | Names | What it covers |
| --- | --- | --- |
| `read` | `read:notes`, `read:cards`, `read:decks`, `read:deck_configs`, `read:models`, `read:tags`, `read:reviews`, `read:media`, `read:collection`, `read:addons` | Reading anything, FSRS computations, jobs, capabilities, the event stream |
| `write` | `write:notes`, `write:cards`, `write:decks`, `write:deck_configs`, `write:models`, `write:tags`, `write:reviews`, `write:media` | Adding, changing and deleting. Tagging notes is `write:tags`. Undo needs the whole `write` area |
| `gui` | | Opening and driving Anki's windows on this computer |
| `sync` | | Syncing with AnkiWeb |
| `manage` | | Import, export, check database, reload, switch profile, close Anki |
| `events` | `events:changes`, `events:reviews` | Which messages the event stream sends: changes to the collection, and each card you answer |
| `local_files` | | Media uploads that name a file **on this computer** (`{"path": "C:/pictures/dog.png"}`), as AnkiConnect's `storeMediaFile` allows. Anything with it can make Anki read any file your account can read |
| `memory_state` | | `POST /v1/cards:set-memory-state`: overwriting cards' FSRS memory state, desired retention and decay |
| `addon` | `addon:<provider>/<action>` | Running add-on actions you enabled (see below). The area covers every enabled action; a name covers one |

**Add-on actions.** Tsunagi can run add-ons' actions for you: FSRS Helper's
through a provider bundled with Tsunagi (`GET /v1/addons/fsrs_helper/actions`
lists them), and any add-on that registers itself
([Add-on providers](docs/addon_providers.md)). Reading their data
needs only `read:addons`. Every other action is disabled until you enable
it: `addon_enabled` (default `{}`) maps `"<provider>/<action>"` to the
level it was enabled at, `normal` or `destructive`:

```json
"addon_enabled": {"fsrs_helper/easy_days": "normal", "fsrs_helper/set_easy_dates": "normal"}
```

Enabled `normal` actions are part of the Default role's defaults, so
resetting Default keeps them; a Default you have edited in `roles` lists
them by name. `destructive` actions are only in Everything (or a role that
names them), and Tsunagi makes an Anki backup before each run. If an
add-on update relabels an action, it is disabled until you enable it again.
The settings page's **Add-ons** page enables and disables actions, and each
role's **Run add-on actions** row chooses which enabled actions that role
may run.

Changes apply immediately. An open event stream closes with reason `auth`
when its app's key or role changes, so the client reconnects with the new
permissions.

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

### `ankiconnect_ignore_origins`
Default: `[]`. Website origins whose AnkiConnect permission requests should be
denied without another prompt. Choosing **No** with **Ignore further requests**
checked adds a nonempty origin to this list. Closing the dialog or denying an
empty origin does not add an entry. Choosing **Yes** grants access and adds the
origin to `cors_allowlist`, regardless of the checkbox.

Remove an entry from this list in the add-on configuration to allow it to ask
again. The list suppresses permission prompts; it does not revoke an existing
allowlist grant. Changes apply immediately.

### `log_level`
Uvicorn log level (`critical`, `error`, `warning`, `info`, `debug`). Tsunagi's
own messages (start and stop, errors with their tracebacks) are logged at
`info`, or at `debug` when this is `debug`.

Both go to Anki's log file for this add-on, `logs/addons/<add-on folder>/`,
inside Anki's data folder (for example `%APPDATA%\Anki2\logs\addons\` on
Windows). It rotates daily and keeps ten days. Attach it to a bug report.

### `op_timeout_seconds`
How long a request may wait for Anki (busy, syncing, etc.) before returning
HTTP 503 instead of hanging. Every 503 body has a `reason`: `busy`, `syncing`
or `closed` (no collection open). `GET /v1/health` reports the same value as
`collection.state`, or `ready`.

A timeout stops the request from waiting; it does not cancel a queued or
running operation. A write may still complete after the 503 response. Check
the collection before retrying, since a retry can repeat the write, or send
an `Idempotency-Key` when creating notes or media so a retry is safe (see
[Create notes and upload media](docs/creating_notes.md)).

### `media_max_bytes`
Largest file accepted by a media upload (default 64 MiB). Applies to base64
uploads, URL downloads, and local files alike.

### `media_fetch_timeout_seconds`
Timeout for downloading media from a URL (default 30).

### `gates`
Switches about the server itself rather than a caller. Read on every request,
so saving toggles them without restarting Anki. (What callers may do moved to
roles; older gate keys in a saved config are ignored.)

- `anki_page_scripts` — when `true`, JavaScript running inside Anki's own
  pages (card templates in the reviewer and previewer, and other add-ons' web
  pages) may use the API like any other local page. Off by default because a
  shared deck's template could otherwise read and change your collection while
  you review it. These pages cannot ask for access with `requestPermission`;
  this switch is the only way to allow them.

### `dev_watch_seconds`
**For working on Tsunagi itself.** When greater than zero, Anki polls the
add-on's own source files that often and restarts the HTTP server when they
change, so `python tools/dev_sync.py --watch` is the whole edit-test loop - no
reinstall, no restart. Leave it at `0` unless you are editing the add-on: it
costs a directory scan per interval and reloads on any file change.

Reloading swaps only Tsunagi's own modules. Changes to `__init__.py` or to the
bundled libraries in `lib/` still need Anki restarted.

### `ankiconnect_import_offered` / `ankiconnect_imported_at` / `config_version`
Internal bookkeeping - don't edit. (`ankiconnect_import_offered` records that
the one-time "import settings from AnkiConnect" dialog was shown; set it back
to `false` to be offered again.) `ankiconnect_imported_at` records the last saved
import as a UTC ISO timestamp, or `null` when no record exists. The prompt flag
does not prove an import happened: declining the prompt also sets it.

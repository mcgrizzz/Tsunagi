# Tsunagi API discovery

`GET /v1/capabilities` reports which Tsunagi API operations your app can use
right now, and why it can't use the others.

```sh
curl "http://127.0.0.1:7777/v1/capabilities"
```

An excerpt of the answer, for a request without a key from this computer
(role Default). The full answer lists every operation and feature; `…` marks
what's left out here:

```json
{
  "versions": {"api": "v1", "addon": "0.5.1", "anki": "26.08.1"},
  "caller": {"name": "No key, this computer", "role": "Default", "enabled": true, "key": "none", "this_computer": true, "host": "127.0.0.1"},
  "operations": {
    …
    "GET /v1/notes": {
      "status": "available",
      "reason": null,
      "setting": "permissions.read:notes",
      "operation_id": "listNotes",
      "options": {}
    },
    "POST /v1/media": {
      "status": "available",
      "reason": null,
      "setting": "permissions.write:media",
      "operation_id": "storeMedia",
      "options": {
        "path": {
          "status": "disabled",
          "reason": "No key, this computer has the role 'Default', which does not allow local_files; change it in Tsunagi's settings",
          "setting": "permissions.local_files"
        }
      }
    },
    …
  },
  "features": {
    "fsrs_scheduling": {"status": "disabled", "reason": "Available but disabled in settings", "setting": "anki.fsrs"},
    …
  },
  "stats": {"duration_ms": 2.56}
}
```

This app may list notes and upload media, but not upload a file by its path
on this computer, and FSRS is off in the collection. AnkiConnect's actions are
listed separately at `GET /actions`.

## Read a capability

Every operation, conditional option and collection feature uses the same status:

| Status | Meaning |
| --- | --- |
| `available` | Your app is allowed to use it. |
| `disabled` | Your app lacks permission or is turned off, or FSRS is off in Anki. `setting` names what to change. |
| `unsupported` | This Anki version can't do it. No setting will change that. |

The report is for the app that asks: the same request with another key can
show different statuses.

`available` only means the operation can run for your app. The request itself
can still fail, for example on invalid input (a simulation with no cards) or
while Anki is busy.

The report needs no permission, so an app whose role is missing something can
see what and why. Two features would tell an app something its role may not
let it read, so an app without that permission sees them as `disabled`, with
`setting` naming the permission: `features.fsrs_scheduling`
(`read:collection`) and `features["addon_actions.<provider>"]` (`read:addons`).

Every supported Anki version provides all FSRS operations and options, so none
of them reports `unsupported`. Tsunagi still checks that each backend method
exists: if a future Anki removed one, that operation would report
`unsupported` and requests to it would get HTTP 501.

## Response layout

| Field | Contents |
| --- | --- |
| `versions` | Tsunagi API identifier, Tsunagi release and running Anki version. |
| `caller` | Who Tsunagi took the request to be, the same as in health (below). `this_computer` and `host` help check a proxy such as Tailscale Serve. |
| `operations` | Tsunagi API operations keyed by `METHOD /path`, using the path templates from OpenAPI. |
| `operations.<key>.operation_id` | The operation's OpenAPI identifier. |
| `operations.<key>.options` | Conditional request options with their own status, reason and setting. Other inputs follow the operation's schema. |
| `features` | Collection features that are not individual HTTP operations, using the same status format. |
| `stats` | Time spent producing the report. |

For example:

- `operations["GET /v1/notes"]` reports note queries.
- `operations["POST /v1/cards:set-memory-state"]` reports whether the memory-state
  write permission is enabled. Its `options["cards[].decay"]` follows the same
  permission and also reports whether this Anki supports that field.
- `options.path` on `POST /v1/media`, `POST /v1/notes` and
  `PATCH /v1/notes/{id}` reports whether your app may send a file by its path
  on this computer. Files sent as `data` or by `url` work either way.
- `operations["POST /v1/fsrs:compute-params"]` reports optimization support,
  including any options that this backend cannot accept.
- `features.fsrs_scheduling` reports the collection's FSRS scheduling switch.
  `setting: "anki.fsrs"` refers to Anki's FSRS setting, not a Tsunagi permission.
- `features["addon_actions.<provider>"]` reports whether an add-on's actions
  can run at all; `unsupported` has a reason, such as the add-on being
  missing. Whether your app may run each action is in
  `GET /v1/addons/<provider>/actions`, as a `status` per action: `allowed`,
  `disabled` (not enabled in Tsunagi's settings), `not_permitted` (your app
  isn't allowed) or `unsupported`.

FSRS computations can run while FSRS scheduling is disabled. Their entries stay
available in that case. The scheduling feature itself reports disabled. Clients
can read each entry directly without combining separate support and enabled flags.

Clients should use the returned statuses instead of maintaining a version table.

Package-import option restrictions and per-deck desired-retention write support
are included as well. `/v1/collection/import-options` is the place to read
saved import choices; clients do not need it to discover unsupported options.

## Request the report

Send your app's key, if it has one. The report needs a profile open in Anki
(503 otherwise). Ask again after switching profiles or changing settings.

`GET /v1/health` stays a small, public liveness check, including when no collection
is open. Its `collection` object gives the open `profile` and a `state`: `ready`,
`syncing`, `closed` (no collection, e.g. during a full sync) or `busy` (Anki
did not answer a trivial read within a second). Every 503 from any route
carries the same value as `reason`, so a client can say "Anki is syncing" rather than "request
failed".

Health's `caller` says who the request counts as, with no profile open
needed, in the same shape as the capabilities report's: the app's `name` (or
the No key row), its `role`, whether the app is `enabled`, what became of the
key, whether the request counted as `this_computer`, and the `host` it was
sent to. The key is `valid`, `unknown` (sent but matching no app, so it counts
as no key, as in AnkiConnect) or `none` (not sent). Send your key to check it:

```json
"caller": {"name": "No key, this computer", "role": "Default", "enabled": true, "key": "unknown", "this_computer": true, "host": "127.0.0.1"}
```

Both endpoints carry the same `versions` identifiers:

| Field | Meaning |
| --- | --- |
| `api` | Tsunagi API contract identifier, currently `v1`. |
| `addon` | Tsunagi release version, also used by OpenAPI's `info.version`. |
| `anki` | Running Anki version. |

Health's `version` field is a release-version alias. The AnkiConnect `version`
action reports its own compatibility protocol version.

# Tsunagi API discovery

`GET /v1/capabilities` is the Tsunagi API's discovery endpoint. It reports all
registered Tsunagi API operations, their current status, and settings or version
restrictions on individual options. AnkiConnect's action list remains at
`GET /actions`.

## Read a capability

Every operation, conditional option and collection feature uses the same status:

| Status | Meaning |
| --- | --- |
| `available` | Your app is allowed to use it. |
| `disabled` | Your app lacks permission (or is turned off). `setting` names the permission. |
| `unsupported` | This Anki version can't do it. No setting will change that. |

A disabled capability has these fields:

```json
{
  "status": "disabled",
  "reason": "No key, this computer has the role 'Default', which does not allow memory_state; change it in Tsunagi's settings",
  "setting": "permissions.memory_state"
}
```

The report is for the app that asks: the same request with another key can
show different statuses.

`available` only means the operation can run for your app. The request itself
can still fail, for example on invalid input or while Anki is busy.

Every supported Anki version provides all FSRS operations and options, so they
report as available. Tsunagi still checks that each backend method exists: if a
future Anki removed one, that operation would report unsupported and requests
to it would receive HTTP 501 instead of failing. An available operation can
still reject its input, for example a simulation with no cards.

## Response layout

| Field | Contents |
| --- | --- |
| `versions` | Tsunagi API identifier, Tsunagi release and running Anki version. |
| `caller` | Who Tsunagi took the request to be: the app (or No key row), its role, whether it counted as this computer, and the `Host` it received. Useful to check a proxy such as Tailscale Serve. |
| `operations` | Tsunagi API operations keyed by `METHOD /path`, using the path templates from OpenAPI. |
| `operations.<key>.operation_id` | The operation's OpenAPI identifier. |
| `operations.<key>.options` | Conditional request options with their own status, reason and setting. Other inputs follow the operation's schema. |
| `features` | Collection features that are not individual HTTP operations, using the same status format. |
| `stats` | Time spent producing the report. |

For example:

- `operations["GET /v1/notes"]` reports note queries.
- `operations["POST /v1/cards:set-memory-state"]` reports whether the memory-state
  write permission is enabled. Its `options["cards[].decay"]` reports Anki's
  support for that field.
- `operations["POST /v1/media"].options.path` reports the local-file permission.
  Disabling this option leaves uploads through `data` or `url` available.
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
are included as well. `/v1/collection/import-options` remains the place to read
saved import choices; clients do not need it to discover unsupported options.

## Request the report

```sh
curl "http://127.0.0.1:7777/v1/capabilities"
```

Send your app's key, if it has one. The report needs a profile open in Anki
(503 otherwise). Ask again after switching profiles or changing settings.

`GET /v1/health` stays a small, public liveness check, including when no collection
is open. Its `collection` object gives the open `profile` and a `state`: `ready`,
`syncing`, `closed` (no collection, e.g. during a full sync) or `busy` (Anki
did not answer a trivial read within a second). Every 503 from any route
carries the same value as `reason`, so a client can say "Anki is syncing" rather than "request
failed". Both endpoints carry the same `versions` identifiers:

| Field | Meaning |
| --- | --- |
| `api` | Tsunagi API contract identifier, currently `v1`. |
| `addon` | Tsunagi release version, also used by OpenAPI's `info.version`. |
| `anki` | Running Anki version. |

Health's `version` field is a release-version alias. The AnkiConnect `version`
action reports its own compatibility protocol version.

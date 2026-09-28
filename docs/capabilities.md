# Tsunagi API discovery

`GET /v1/capabilities` is the Tsunagi API's discovery endpoint. It reports all
registered Tsunagi API operations, their current status, and settings or version
restrictions on individual options. AnkiConnect's action list remains at
`GET /actions`.

## Read a capability

Every operation, conditional option and collection feature uses the same status:

| Status | Meaning |
| --- | --- |
| `available` | Supported and not disabled by a setting. |
| `disabled` | Supported, but your app's role lacks the permission. `setting` names it. |
| `unsupported` | This Anki version lacks the required support. Enabling a setting will not fix it. |

A disabled capability has these fields:

```json
{
  "status": "disabled",
  "reason": "No key, this computer has the role 'Default (like AnkiConnect)', which does not allow memory_state; change it in Tsunagi's settings",
  "setting": "permissions.memory_state"
}
```

The report is for the app that asks: the same request with another key can
show different statuses.

Available entries have a null `reason`. A `setting` can still be present when
its switch is enabled. Entries without a controlling setting use null.
Availability describes support and configuration. A request can still fail because
of invalid inputs, authentication, missing records, a busy collection, or the
current GUI state. Discovery does not execute the operations it lists.

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
- `features["addon_actions.fsrs_helper"]` reports whether Tsunagi can drive
  FSRS Helper: `unsupported` with a reason when it is missing, disabled, did
  not load or is a version whose entry points changed. Whether the calling
  app may run each action is in `GET /v1/addons/fsrs_helper/actions`
  (`status` per action), so
  `operations["POST /v1/addons/{provider_id}/actions/{name}:run"]` itself is
  always available.

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

Send your app's key, if it has one. Discovery requires an open collection and returns
503 while no collection is available. Query it again after switching profiles
or changing settings. It does not return API keys or the website allowlist.

`GET /v1/health` stays a small, public liveness check, including when no collection
is open. Its `collection` object gives the open `profile` and a `state`: `ready`,
`syncing`, `closed` (no collection, e.g. during a full sync) or `busy` (Anki
did not answer a trivial read within a second). A 503 body carries the same
value as `reason`, so a client can say "Anki is syncing" rather than "request
failed". Both endpoints carry the same `versions` identifiers:

| Field | Meaning |
| --- | --- |
| `api` | Tsunagi API contract identifier, currently `v1`. |
| `addon` | Tsunagi release version, also used by OpenAPI's `info.version`. |
| `anki` | Running Anki version. |

Health's `version` field is a release-version alias. The AnkiConnect `version`
action reports its own compatibility protocol version.

## Earlier experimental clients

The old FSRS-only response (`fsrs.supported`, `fsrs.enabled` and
`fsrs.operations`) is replaced by the operation and feature entries above.
Use each entry's `status` instead of the old `available` boolean. Read restricted
options from `options` instead of `unsupported_options`. The response schema is
published in `/openapi.json`.

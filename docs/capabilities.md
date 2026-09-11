# Native API discovery

`GET /v1/capabilities` is the native API's discovery endpoint. It reports all
registered native operations, their current status, and settings or version
restrictions on individual options. AnkiConnect's action list remains at
`GET /actions`.

## Read a capability

Every operation, conditional option and collection feature uses the same status:

| Status | Meaning |
| --- | --- |
| `available` | Supported and not disabled by a setting. |
| `disabled` | Supported, but disabled in settings. `setting` identifies the switch. |
| `unsupported` | This Anki version lacks the required support. Enabling a setting will not fix it. |

A disabled capability has these fields:

```json
{
  "status": "disabled",
  "reason": "Available but disabled in settings",
  "setting": "gates.cards_set_memory_state"
}
```

Available entries have a null `reason`. A `setting` can still be present when
its switch is enabled. Entries without a controlling setting use null.
Availability describes support and configuration. A request can still fail because
of invalid inputs, authentication, missing records, a busy collection, or the
current GUI state. Discovery does not execute the operations it lists.

## Response layout

| Field | Contents |
| --- | --- |
| `versions` | Native API identifier, Tsunagi release and running Anki version. |
| `operations` | Native operations keyed by `METHOD /path`, using the path templates from OpenAPI. |
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

FSRS computations can run while FSRS scheduling is disabled. Their entries stay
available in that case. The scheduling feature itself reports disabled. Clients
can read each entry directly without combining separate support and enabled flags.

Anki 23.10 supports parameter optimization and evaluation, but not Tsunagi's
simulator operations. Its optimizer cannot accept `current_params`,
`ignore_revlogs_before_ms`, `num_of_relearning_steps` or `health_check`; its evaluator
cannot accept `ignore_revlogs_before_ms`. Those options appear as unsupported.
Clients should use the returned statuses instead of maintaining a version table.

Package-import option restrictions and per-deck desired-retention write support
are included as well. `/v1/collection/import-options` remains the place to read
saved import choices; clients do not need it to discover unsupported options.

## Request the report

```sh
curl "http://127.0.0.1:7777/v1/capabilities"
```

Supply your configured API key. Discovery requires an open collection and returns
503 while no collection is available. Query it again after switching profiles
or changing settings. It does not return API keys or the website allowlist.

`GET /v1/health` stays a small, public liveness check, including when no collection
is open. Both endpoints carry the same `versions` identifiers:

| Field | Meaning |
| --- | --- |
| `api` | Native API contract identifier, currently `v1`. |
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

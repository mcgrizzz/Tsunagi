# Runtime versions and capabilities

Use `GET /v1/health` to identify the running server, including when no collection
is open. Its `versions` object separates three identifiers:

| Field | Meaning |
| --- | --- |
| `api` | Native API contract, currently `v1` |
| `addon` | Tsunagi release version; also used by OpenAPI's `info.version` |
| `anki` | Version of the running Anki backend |

The existing health `version` field remains a release-version alias for older
clients. The AnkiConnect `version` action continues to report its compatibility
protocol version independently.

Use `GET /v1/capabilities` with an open collection before offering FSRS operations.
It returns the same `versions` object plus:

| Field | Meaning |
| --- | --- |
| `fsrs.supported` | The backend exposes FSRS computations |
| `fsrs.enabled` | FSRS scheduling is enabled in the open collection |
| `fsrs.operations.<name>.available` | The backend supports this computation |
| `fsrs.operations.<name>.unsupported_options` | Request options unavailable on this backend |

Operation names are `compute_params`, `evaluate_params`, `simulate`,
`simulate_workload` and `optimal_retention`. A computation can be available while
FSRS scheduling is disabled. Availability describes backend support, not whether
particular parameters or review history will produce a successful result.
Discovery never starts a computation or changes the collection setting.

For example, Anki 23.10 supports parameter optimization and evaluation, but lacks
the simulator operations exposed by Tsunagi. Its optimizer does not accept
`current_params`, `ignore_revlogs_before_ms`, `num_of_relearning_steps` or
`health_check`; its evaluator does not accept `ignore_revlogs_before_ms`.
The older backend's differently shaped optimal-retention API is reported as
unavailable. Anki 26.08.1 supports all five operations and these options.
Clients should inspect the returned fields instead of comparing version strings.

```sh
curl http://localhost:7777/v1/health
curl http://localhost:7777/v1/capabilities
```

Supply your configured API key for authenticated requests. Capabilities returns
503 when no collection is open; health remains available. Query capabilities
again after switching profiles or changing the collection's FSRS setting.
The response schemas and descriptions are also exposed in `/openapi.json`.

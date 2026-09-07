# Routing efficiency investigation — 2026-09-07

## Environment and baseline

Live runtime: Windows Anki 26.08.1, disposable `[DEV] Yomine`, 4,547 cards
and 4,547 notes, API key disabled. The user confirmed Anki was minimized.
Before changes, installed route factory, card adapter, and operation-dispatch
files matched the workspace byte for byte. Requests used Windows curl from
WSL; its approximately 250 ms startup/HTTP overhead is separate from the
server timings below. No collection data was changed by this investigation.

Three runs per case, milliseconds, before changes:

| Request | Median | Range | Results |
| --- | ---: | ---: | --- |
| `where=queue==-1&select=id,queue&limit=50` | 329.485 | 299.553–339.682 | 7 |
| `where=queue==-1&limit=50` | 383.020 | 336.077–396.868 | 7 |
| `search=is:suspended&select=id,queue&limit=50` | 1.419 | 1.295–1.562 | Same 7 |
| `select=id&limit=100` | 7.779 | 7.369–8.510 | 100 |
| `where=queue==-1&select=id,queue&limit=250` | 305.640 | 300.110–305.829 | 7 |

The earlier handoff's 11.5-second scan did **not** reproduce. There was no
code change between that handoff and these baseline measurements. Its cause
remains unestablished; the improvement between those sessions is not evidence
for this patch.

## Measured execution path

The native route builds a query plan, enumerates IDs in keyset order, hydrates
candidate batches, evaluates the existing where predicate, and projects the
surviving page. A full filtered listing hydrates only predicate fields during
the scan, then fetches full surviving cards. Each ID batch and hydration batch
runs through a separate serialized Anki QueryOp. Filtering runs in the HTTP
route's worker; QueryOp work runs through Anki's collection executor.

`tools/profile_routing.py` temporarily wraps route and adapter functions in
the running Anki process and records aggregate timings without card content.
These are instrumented timings, not zero-overhead samples. The first narrow
scan took 342.575 ms:

| Work | Calls | Milliseconds |
| --- | ---: | ---: |
| ID enumeration, inside Anki workers | 91 | 5.150 |
| Card hydration, inside Anki workers | 91 | 160.491 |
| Card row construction, included in hydration | 4,547 | 113.256 |
| Deck-name enumeration, included in hydration | 91 | 3.599 |
| Model-to-dictionary conversion | 4,554 | 114.623 |
| Predicate evaluation | 4,547 | 6.727 |
| Before/after-worker waits across both operation types | 182 | 47.000 |

Rows in this table overlap where indicated; they must not all be summed.
Before-worker time includes initial main-thread dispatch and executor queue
wait; after-worker time includes completion delivery and caller wakeup. The
profiler does not split those waits further. It also does not isolate final
HTTP serialization. Server `stats.duration_ms` measures route work, not
end-to-end HTTP latency or isolated SQL time.

The full filtered sample built 4,554 card rows, including seven survivors,
and called scheduling/retrievability helpers only seven times each. That
confirms two-phase rendering worked, but scalar candidates still paid for
individual Anki card loads, full CardInfo construction, and dictionary
conversion. Anki search needed only two operations and hydrated seven cards.
The SQL where DSL and Anki search retain their separate semantics.

Three further instrumented before-change runs:

| Request | Median ms | Range ms |
| --- | ---: | ---: |
| Narrow suspended scan | 348.739 | 328.161–355.106 |
| Full suspended scan | 337.311 | 336.373–342.314 |

## Change and regression coverage

Native card ID/search hydration now reads requested stable scalar columns in
bounded, parameterized SQL batches. It returns ordinary mappings, avoiding
individual card loads, CardInfo construction, and recursive serialization for
those candidate rows. Human-readable aliases and derived flag/suspended/buried
values match the normal card reader. Requested order, duplicates, and skipped
missing IDs are preserved. Empty ID input issues no SQL query.

Full rows, note/render/deck-name fields, and newer FSRS properties use the
existing object reader. Compatibility consumers still receive CardInfo objects.
The where parser/predicate, ID discovery, scan batching, cursors, and QueryOp
scheduling are unchanged. This does not push the where DSL into SQL or Anki
search, change operation serialization, or increase timeouts.

New tests compare scalar values against full responses, prevent per-card and
deck-name loads on scalar requests, exercise sparse matches beyond five scan
batches and across full-response cursors, and check bounded parameterized reads
with duplicate/missing IDs. Focused suite: 172 passed. Full suite: 842 passed,
8 skipped. Ruff passed. Tests use the existing Python 3.10 / Anki 23.10
environment, distinct from the live Anki 26.08.1 runtime.

## Live after-change verification

The patch was synced and reloaded. The installed card adapter and native card
route matched the workspace after verification. The active profile remained
`[DEV] Yomine` with 4,547 cards; Anki was minimized for the comparison.

The reload removed the temporary profiler: its JSONL file did not grow during
the after-change requests. Old log entries were excluded from after-change
results. The table therefore compares **uninstrumented** three-run samples
before and after, not the instrumented baseline above.

| Request | Before median ms | After median ms | After range ms |
| --- | ---: | ---: | ---: |
| Narrow suspended scan | 329.485 | 55.217 | 50.305–62.122 |
| Full suspended scan | 383.020 | 61.174 | 57.784–62.799 |
| Native suspended search, narrow | 1.419 | 0.929 | 0.809–1.554 |
| ID-only 100-card page | 7.779 | 2.069 | 1.972–2.101 |

The suspended scans improved by approximately 6× in these samples. This is a
live end-to-end route improvement for the tested profile and state, not an
isolated SQL benchmark or a promise for all collection sizes/UI states.
No after-change per-phase counts were captured; regression tests establish
the new scalar reader's bounded query and zero per-card-load behavior.

Live correctness checks passed:

- Narrow and full `queue==-1` cursor walks with limit 2 each traversed four
  pages and returned exactly the same seven ordered IDs as Anki search.
- Twenty scalar fields on 100 cards matched their full-response values.
- POST query results matched GET results.
- Missing IDs returned HTTP 200 with an empty list; malformed filters
  returned HTTP 400.
- The active profile and collection size were unchanged.

The historical 11.5-second result remains unexplained. Operation scheduling
counts are unchanged by this patch, so unusually slow main-thread dispatch
could still dominate a scan. Investigate that separately if it reproduces;
do not label this patch a verified fix for that historical delay.

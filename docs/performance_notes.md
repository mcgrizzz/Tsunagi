# Performance notes

[← Documentation](README.md)

Notes for contributors on where the Tsunagi API spends time, what past
optimizations measured, and how benchmark runs are recorded. For measurements
on the real Anki desktop, see [API benchmarks](benchmarks.md).

Everything here was measured on **2026-09-21** with Anki/aqt **26.09.2** and
Python **3.13.9** on Linux, in the test harness unless stated otherwise.

## What the test harness leaves out

The harness uses Anki's real collection code, Rust backend and data. It does
not include:

- a real Anki window, or contention with the UI;
- the handoff of each operation to Anki's main thread through Qt, which the
  harness replaces with a direct call;
- an HTTP server or network socket; requests go through an in-process client.

These are the parts a desktop user actually waits on. Harness timings are for
finding hotspots quickly and repeatably. They are **not a user-facing
comparison**, and they cannot simply be added up to predict desktop latency.

## Harness comparison with AnkiConnect

Measured 2026-09-21, before the 2026-09-23 changes to row building, encoding
and search reads. The Tsunagi figures for reading cards and for note types are
out of date; see [rows from Anki's database](#rows-from-ankis-database).

Each API performs the same task on a fresh copy of a disposable collection, in
the same process. Values are the **median of five runs** after a separate first
run, in **milliseconds**; lower is faster. All 14 tasks were checked to produce
the same data through every API.

### Reading cards

| Full records for | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | ---: | ---: | ---: |
| 100 cards | 15.0 | 18.9 | 19.8 |
| 10,000 cards | 714.5 | 1,090.0 | 1,299.2 |

AnkiConnect is fastest here. Tsunagi validates every record against its
response schema and encodes it as JSON, which costs time on large reads.

### Creating notes

| Task | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | ---: | ---: | ---: |
| 1,000 text notes | 1,533.1 | 1,574.8 | 1,564.2 |
| Save one note and get its two card IDs | 7.4 | 7.5 | 7.1 |

About the same everywhere. Batch creation through the Tsunagi API also returns
the new note IDs and groups the additions into one undo step.

### Duplicate checks

Two versions of the same question, "can these notes be added?":

- **Status and IDs** also returns the IDs of the existing notes that match.
- **Status only** returns just yes or no for each candidate. AnkiConnect and the
  AnkiConnect Shim use one `canAddNotesWithErrorDetail` action; the Tsunagi API
  uses `POST /v1/notes:check?include_duplicate_ids=false`.

| Candidates | Want | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | --- | ---: | ---: | ---: |
| 10 duplicates | Status and IDs | 4.4 | 4.6 | 1.9 |
| 100 duplicates | Status and IDs | 35.6 | 33.2 | 10.8 |
| 10 mixed | Status and IDs | 3.2 | 3.3 | 1.7 |
| 100 mixed | Status and IDs | 19.8 | 17.3 | 7.7 |
| 10 duplicates | Status only | 1.3 | 1.3 | 1.8 |
| 100 duplicates | Status only | 6.1 | 4.9 | 6.6 |
| 10 mixed | Status only | 1.2 | 1.4 | 1.8 |
| 100 mixed | Status only | 5.4 | 3.8 | 5.9 |

"Mixed" candidates include both new and existing notes. The Tsunagi API is two
to three times faster when you need the IDs. When you only need yes or no, it is
slightly slower than the other two in this test. It returns IDs by default; see
[note checks](creating_notes.md#check-without-saving). IDs cost extra because of
[Anki's duplicate check](#where-tsunagi-api-time-goes).

### Note types and their fields

| Task | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | ---: | ---: | ---: |
| 10 note types with field names | 2.1 | 1.8 | 1.5 |
| 100 note types with field names | 9.0 | 4.1 | 7.2 |

### Adding notes with media

Each of 1,000 notes gets its own 16 KiB image and 16 KiB audio file. In the
"existing" case, identical files are already stored. Medians of two runs after a
first run, in **seconds**.

| Storage | Media | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | --- | ---: | ---: | ---: |
| Normal disk (ext4) | New files | 43.93 | 48.29 | 17.67 |
| Normal disk (ext4) | Existing files | 5.12 | 5.24 | 2.38 |
| RAM disk (tmpfs) | New files | 0.910 | 1.017 | 0.992 |
| RAM disk (tmpfs) | Existing files | 0.824 | 0.926 | 0.860 |

On a normal disk, the Tsunagi API is about 2.5 times faster with new files. On a
RAM disk, all three take about a second, so **the gap is mostly disk behavior**.
Treat it with caution: media timings are very sensitive to storage and to the
order runs happen in. Restoring the collection between runs does not reset the
operating system's file caches.

Individual new-file runs on disk: AnkiConnect 41.47–46.39 s, AnkiConnect Shim
47.17–49.41 s, Tsunagi 17.47–17.86 s.

The Tsunagi API receives all 2,000 files in one `POST /v1/media` request, then
all notes in one `POST /v1/notes` request. AnkiConnect and the AnkiConnect Shim
take the attachments in one `addNotes` request. All three still store each of
the 2,000 files through Anki's media backend, and every run verifies the saved
bytes and field references.

### How the tasks map to each API

| Task | AnkiConnect and AnkiConnect Shim | Tsunagi |
| --- | --- | --- |
| Read all cards | `findCards`, then `cardsInfo` | `GET /v1/cards` selecting equivalent fields; no `limit` returns everything |
| Create text notes | One `addNotes` action | One `POST /v1/notes` with an array |
| Create notes with media | One `addNotes` action with attachments | One `POST /v1/media` array, then one `POST /v1/notes` array |
| Duplicate status only | One `canAddNotesWithErrorDetail` action | One `POST /v1/notes:check?include_duplicate_ids=false` |
| Duplicate status and IDs | `canAddNotesWithErrorDetail`, then `findNotes` for the duplicates, inside one `multi` | One `POST /v1/notes:check` |
| Note types with field names | `modelNamesAndIds`, then `modelFieldNames`, inside one `multi` | One model query selecting `id,name,fields[].name` |
| Save a note and get its card IDs | `addNote`, then `findCards` | One `POST /v1/notes?include=cards` |

- These tasks mostly follow AnkiConnect's action shapes, so the Tsunagi API is
  measured doing AnkiConnect's job, not the other way around.
- Batching AnkiConnect's follow-up actions in `multi` gives it the same
  single-request advantage. The tool can also measure them as separate requests
  (`model_fields`, `duplicate_ids`), but those are not the numbers above.
- Creation tasks use distinct, valid notes with `allowDuplicate: false`, so they
  measure successful writes. On failure the APIs differ: AnkiConnect's
  `addNotes` undoes its successful additions if any input fails, while the
  Tsunagi API keeps them and reports which inputs were rejected. See
  [batch creation](creating_notes.md).
- The card-save task uses a note type that makes two cards. Duplicate checks
  never create notes.
- Card reads request everything at once (`--batches 0`). Positive batch values
  measure paging instead: the Tsunagi API follows cursors, AnkiConnect splits
  `cardsInfo`. The Tsunagi API has no implicit page limit.

## Where Tsunagi API time goes

What profiling the [harness comparison](#harness-comparison-with-ankiconnect)
showed, and what the current optimizations keep intact.

- **Query responses:** standard pages are rendered straight to bytes by
  Python's C JSON encoder, with the settings Starlette's `JSONResponse` uses.
  A page with a value the encoder can't handle, or with a `"_sa`-prefixed key
  that FastAPI would drop, falls back to FastAPI's encoder for the whole page;
  custom response schemas keep normal validation. The page envelope is built
  without re-validating its items, which are typed `Any`.
- **Rows from Anki's database:** reviews, notes and cards read through the
  Tsunagi API are plain dicts with the schema's field names and types, built
  without per-row validation (see
  [below](#rows-from-ankis-database)). Rows that are still models, such as
  write results, use a shared exporter that keeps human-readable names.
- **Note checks:** the adapter uses the already-validated request models. It
  resolves each distinct note type and deck once per request and still checks
  every candidate against the current collection. Turning off duplicate IDs
  skips only the extra ID lookup, not duplicate detection. FastAPI validates the
  plain result records once against the response schema, so invalid output is
  still rejected. The 100-candidate check performs 202 validations: 100 inputs,
  100 results and two envelopes.
- **Duplicate IDs:** Anki's own duplicate check
  [retrieves candidate note IDs and fields](https://github.com/ankitects/anki/blob/26.08.1/rslib/src/notes/mod.rs#L580)
  but [reports only a validation state](https://github.com/ankitects/anki/blob/26.08.1/proto/anki/notes.proto#L106)
  to add-ons. Tsunagi therefore needs a second lookup to return matching IDs.
  Returning them from Anki's original check would avoid that repeated work.
- **Selected fields:** one top-level field is read directly from each row;
  several are copied in one C-level step per row. Nested and unusual selections
  keep the general projection. Review reads select only the requested columns
  in SQL.
- **Note type loading:** field metadata still needs Anki's note type records. The
  100-note-type task makes 100 record loads and one names-list call, and 401
  model-validation calls. Skipping unused templates does not remove those.
- **Batch note creation:** one collection operation shares note type and deck
  lookups, validates each candidate against the current collection, and returns
  IDs without reloading saved notes. The 1,000-note task resolves the note type
  and deck once, performs 1,000 note writes, and merges undo entries after each
  success. Backend writes dominate. Event subscribers can request card-ID
  details; the benchmark has none.
- **Media batches:** decoding and downloads stay on the request thread. Each
  storage dispatch holds at most 64 files and aims for at most 8 MiB of decoded
  data; a larger allowed file is stored alone. The 2,000 small uploads need 32
  dispatches, then one operation creates the notes. Every file still goes
  through Anki's media backend.
- **Media storage:** storage cost includes work inside Anki's Rust backend, which
  Python profiling sees only at the backend-call boundary. Wall-clock differences
  cannot separate filesystem cost from SQL cost.

None of these optimizations keep collection results between requests or share
mutable note objects between cards. Client input is still validated. Rows read
from Anki's own database are not validated per row; contract tests cover them
instead.

## Filtered card projections

Measured with the two-phase scan it describes; see
[a two-phase filtered scan](dataflow/get_cards_filtered.md#measured-effect).

## Single-field queries

Before 2026-09-23, `GET /v1/notes?select=id` made the same Anki search call as
the AnkiConnect Shim's `findNotes`. It then turned each ID into a `{"id": n}`
row, projected it, flattened it back to a number, and re-validated every item
against the page schema. Because the item type starts with `Any`, that
validation returned the same objects. Now:

- The page envelope is built without the per-item validation, for every query.
- A single top-level field from plain rows is read directly. Aliases, lists,
  unusual types and `shape=object` still take the general path;
  `tests/test_query_single_field.py` checks both paths agree.
- JSON encoding handles plain list items inline.

On the real desktop, reading all note IDs (4,547 notes before, 4,561 after),
median time for a successful request in milliseconds:

| Simultaneous requests | Tsunagi API before | Tsunagi API after | AnkiConnect Shim after |
| --- | ---: | ---: | ---: |
| 1 | 10.8 | 5.5 | 3.2 |
| 16 | 142.6 | 58.2 | 25.9 |
| 64 | 556.6 | 217.3 | 103.4 |
| 256 | 1,421.2 | 570.2 | 263.9 |

In the harness, one request for 4,547 IDs went from 7.1 ms to 2.7 ms against the
Shim's 1.9 ms, and from about 122,000 to 9,000 function calls. The remaining gap
is per-request routing and planning work that the Shim does not do.

## Rows from Anki's database

Decided 2026-09-23: rows read from Anki's own database are built with the
schema's field names and types, without validating each row. The values come
from Anki's tables and objects, so per-row validation could only fail on data
Anki itself would not write, and it cost most of the request's time. The
schemas still document the API and validate client input. Write results and
the AnkiConnect Shim's `cardsInfo` still build validated models.

`tests/test_review_rows.py`, `test_note_rows.py` and `test_card_rows.py` check
the rows against the schemas on every CI runtime. They use values that differ in
every position, so a field paired with the wrong source also fails; the card
test turns FSRS on so memory state, retention and decay are checked. Each was
confirmed to fail on deliberately broken builders.

Responses were compared byte for byte before and after, on deterministic
harness collections, across 25 review, 17 note and 17 card query shapes plus
paging, POST queries and the AnkiConnect Shim's related actions. Cards were also
compared on Python 3.9 / Anki 23.10.

Harness timings, median of three requests:

| Read | Before | After | AnkiConnect Shim |
| --- | ---: | ---: | ---: |
| 150,000 reviews, 8 fields | 2,025 ms | 497 ms | 410 ms |
| 4,500 notes with 24 fields each | 973 ms | 328 ms | 355 ms |
| 2,500 full card rows | 794 ms | 386 ms | 684 ms |

The AnkiConnect Shim's `notesInfo` uses the same note rows, so it also got
faster (809 ms before).

## One-pass search reads

A search normally collects matching IDs, then reads the rows in slices of 250,
each a separate Anki operation. That keeps any one operation short and lets
`where` filters and paging work on IDs. For a complete, unfiltered result (no
`where`, `limit` or `cursor`), a resource can now read every matching row in one
query instead (`SearchSpec.rows`). Reviews use it: find the matching cards, then
read their reviews by card ID, as the AnkiConnect Shim does.
`tests/test_search_rows.py` checks when each path is taken.

Measured on the desktop (`[DEV] Yomine`), median of ten runs:

| Workload | Before | After | AnkiConnect Shim |
| --- | ---: | ---: | ---: |
| One deck's review history (anki-mcp-server) | 1,002 ms | 797 ms | 709 ms |
| Known-word snapshot (Yomine) | 2,066 ms | 1,569 ms | 1,107 ms |

Before this, an experiment raised the slice size from 250 to 10,000 on the
installed add-on. Review history improved only 11%, the known-word snapshot not
at all, and mined-card status got slower, so the slice size is unchanged.
Timing one review request showed the rest: Tsunagi's server work took 418 ms of
a 659 ms request, and its response is about 30% larger (18.8 MB against
14.5 MB) because each review carries named keys.

## Membership filters

For `in [...]` and `not in [...]` filters that reach Python filtering, Tsunagi
builds one membership set per clause instead of one per row. Each row still reads
its current values. The same code serves notes, cards and other query
resources; Anki search and index routes can bypass it entirely.

The diagnostic selects note IDs from `GET /v1/notes`, filtering `tags[]` against
a supplied list. Only the shared filter module differs between the two columns.

| Notes scanned | Tags in the filter | Before (ms) | Now (ms) |
| --- | ---: | ---: | ---: |
| 100 | 10 | 2.2 | 2.2 |
| 100 | 1,000 | 6.1 | 5.6 |
| 10,000 | 10 | 155.3 | 150.9 |
| 10,000 | 1,000 | 259.1 | 177.4 |

- "Before" is the filter from `e3a59e8`. Medians of seven requests after a
  separate first request.
- The largest case returns 5,000 matching IDs and builds one set instead of
  10,000. An equality filter on 10,000 notes, as a control, measured 147.5 ms
  before and 150.2 ms now.
- Workers run one after another on copies of the same disposable collection and
  repeat reads on their open collection. Separate checks confirm GET/POST
  results, set-construction counts, and that a saved tag edit shows up in the
  next query immediately.

## Qt dispatch overhead

Tsunagi runs collection work through Anki's operation system, which hands it to
Anki's main thread and back. The harness replaces that handoff with a direct
call so its profiles stay repeatable. This separate tool measures the real
handoff: Tsunagi's operation wrappers with real Qt signals, Anki's task manager,
`QueryOp`, `CollectionOp` and progress widgets, with near-empty work inside. It
runs offscreen with a stand-in main window, using PyQt6 6.11.0.

| Work arrangement | Total (ms) | Outside the actual work (ms) |
| --- | ---: | ---: |
| 100 separate read operations | 7.527 | 6.966 |
| One read operation doing the same 100 reads | 0.215 | 0.074 |
| 100 separate write operations | 40.202 | 40.077 |
| One write operation with 100 empty results | 0.424 | 0.413 |

Medians of five runs after a first run. Read operations count an empty
collection's notes; write operations return empty change flags.

Batching work into one operation avoids nearly all of this overhead, where the
operation's behavior allows it. It still has to keep validation order, undo
steps, events and fresh data correct. These numbers leave out real writes, window
repainting, undo-menu rendering, sockets and other add-ons, so they can't simply
be added to other timings to predict desktop performance.

## How benchmark runs are recorded

### Harness reports

`dist/benchmarks/current-*.json` holds the current harness results.
`current-run-manifest.json` records the commands, run times and source hashes for
all six groups, and confirms the source did not change during the run. A
source-dirty flag also counts documentation edits.

The main reports record versions, source hashes, run order, first and repeated
timings, response sizes, request and action counts, worker peak memory,
verification fingerprints, and a separate profiled run. Peak memory includes the
interpreter and test setup, not just one request. The filter report records
timings, set-construction counts and the live-edit check, without a profile or
memory figure.

Verification compares complete equivalent card records in order. Write checks
compare note and card counts, fields, tags and media content, ignoring generated
IDs and timestamps. Model and duplicate checks compare IDs and relationships
against the collection. Profiling runs separately from the timed runs, and its
cumulative timings overlap. API and backend call counts are not SQL query counts.

AnkiConnect runs through its own HTTP handler without a listening socket, and
Tsunagi through FastAPI's in-process test client. Both include request decoding,
the work itself, response encoding and client decoding, but the transport layers
differ.

### Client workload reports

`dist/benchmarks/workloads-upstream-2026-09-23.json`,
`workloads-shim-2026-09-23c.json` and `workloads-native-2026-09-23c.json`, with
`workloads-native-2026-09-23d.json` for the two review workloads after the
one-pass read, and `workloads-upstream-2026-09-23b.json` with
`workloads-lookup-{native,shim}-2026-09-23.json` for the two Yomitan lookups
after duplicate scope options were added, and `workloads-fixed-{upstream,shim,native}-2026-09-23.json` for the asbplayer
cache and the two anki-mcp-server review workloads, rebuilt to match those
clients' code exactly. Each workload records every trial's time, request count,
response size and a fingerprint of the normalized answer, a sample answer, the
runner's source hashes, the profile's note count before and after, and any
leftover benchmark notes or media. Generated media names are replaced with
placeholders before fingerprinting, so trials compare.

### Live connection reports

Current raw reports (`upstream` is AnkiConnect, `shim` the AnkiConnect Shim,
`native` the Tsunagi API):

- `dist/benchmarks/live-connections-upstream.json` (2026-09-21, 4,547 notes).
  `current-live-run-manifest.json` lists it with its hash.
- `live-connections-shim-2026-09-23.json` and
  `live-connections-native-2026-09-23.json` (4,561 notes), after the single-field
  query fix. They replace `live-connections-shim-rerun.json` and
  `live-connections-native-rerun.json`, which are kept for the before/after
  comparison.

All runs used the same client source. Within each date, the runs verified the
same note IDs.

The installed AnkiConnect web server and utility module matched the pinned
reference used in the harness, but its main module differed, so the live run is
not labeled with that commit. `live-upstream-source.json` records the installed
source hashes. For each Tsunagi run, the installed modules matched the measured
source.

Reports separate HTTP errors, API errors, timeouts, refused or reset
connections, connections closed without a response, and incomplete or incorrect
responses. Each sample records its outcome, the stage it reached and its elapsed
time. The client's own tests simulate silent closes, truncated replies, errors
and wrong IDs; those simulated outcomes are not findings about either add-on.

## Reproduce these measurements

Use Python 3.13.9 and Anki/aqt 26.09.2 to match this snapshot, plus the test
dependencies and a built `lib/shared` directory. The harness needs Python 3.12
or newer. These commands use disposable collections and never contact a running
Anki. In the tool options, `native` is the Tsunagi API, `shim` the AnkiConnect
Shim and `upstream` AnkiConnect.

The harness comparison needs a checkout of upstream AnkiConnect at
`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`:

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads read_cards,add_text,duplicate_ids_multi,duplicate_mixed_multi,duplicate_status,duplicate_mixed_status,model_fields_multi,save_card_ids \
  --read-sizes 100,10000 --write-sizes 1000 --workflow-sizes 10,100 \
  --batches 0 --repeats 5 --implementations native,upstream,shim \
  --output dist/benchmarks/current-core.json

python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads add_media_new,add_media_existing --write-sizes 1000 \
  --implementations native,shim,upstream --repeats 2 \
  --output dist/benchmarks/current-media.json
```

Run these one after another, and stop heavy background work such as video
transcoding while timing. For the RAM-disk media check, add
`--scratch-dir /dev/shm` and use a different output path. For a quick smoke
test, use `--write-sizes 40 --repeats 2`.

The other measurements need no AnkiConnect checkout:

```sh
python tools/benchmark_filtered_projection.py --sizes 100 10000 --repeats 5 \
  --output dist/benchmarks/current-filtered-projection.json

python tools/benchmark_filtering.py --baseline-ref e3a59e8 \
  --rows 100 10000 --allowed 0 10 1000 --repeats 7 \
  --output dist/benchmarks/current-filtering.json

python tools/benchmark_dispatch.py --count 100 --repeats 5 \
  --output dist/benchmarks/current-dispatch.json
```

`--allowed 0` adds the equality control, and the baseline commit must exist in
your local checkout. The dispatch tool needs an environment with aqt and PyQt.

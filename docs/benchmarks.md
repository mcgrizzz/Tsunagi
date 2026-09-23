# API benchmarks

[← Documentation](README.md)

This page reports the current comparison of upstream AnkiConnect, Tsunagi's
AnkiConnect compatibility API, and its native endpoints. It is updated in place.

**The processing tables use disposable collections and do not measure
end-to-end desktop latency.** Each implementation runs separately. The harness
verifies the resulting data before accepting a sample.

A separate [live connection benchmark](#live-connection-benchmark) runs against
a full Anki testing session to measure concurrent requests and disconnects.

## Current results

Measured **2026-09-21** on Anki/aqt **26.09.2**, Python **3.13.9**, Linux/WSL.
All tables use the current working tree after `be6cb46`, including the pending
compatibility and routing fixes. The run manifest records source hashes and
confirms that the measured source stayed unchanged throughout the run. Upstream
AnkiConnect is pinned to `de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`.

The core comparison uses five repeated trials after a separately recorded
first-use trial. Every trial starts from a restored collection. All **14 core
workloads** passed their equivalence checks. Times are in **milliseconds**;
lower is faster.

| Equivalent task | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| 100 cards, full equivalent records | 15.0 | 18.9 | 19.8 |
| 10,000 cards, full equivalent records | 714.5 | 1,090.0 | 1,299.2 |
| 1,000 text notes | 1,533.1 | 1,574.8 | 1,564.2 |
| 10 duplicates: status and note IDs | 4.4 | 4.6 | 1.9 |
| 100 duplicates: status and note IDs | 35.6 | 33.2 | 10.8 |
| 10 mixed candidates: status and note IDs | 3.2 | 3.3 | 1.7 |
| 100 mixed candidates: status and note IDs | 19.8 | 17.3 | 7.7 |
| 10 duplicates: status only | 1.3 | 1.3 | 1.8 |
| 100 duplicates: status only | 6.1 | 4.9 | 6.6 |
| 10 mixed candidates: status only | 1.2 | 1.4 | 1.8 |
| 100 mixed candidates: status only | 5.4 | 3.8 | 5.9 |
| 10 models with their field names | 2.1 | 1.8 | 1.5 |
| 100 models with their field names | 9.0 | 4.1 | 7.2 |
| Save one note and get its two card IDs | 7.4 | 7.5 | 7.1 |

Creating 1,000 text notes is close across the three implementations. Native
batch creation returns created note IDs and groups successful additions into
one undo step. Native checks are faster when the client needs duplicate status
and matching IDs together. Full-card reads remain faster through upstream;
loading 100 models with fields is fastest through the shim in this fixture.

The **status plus IDs** rows include each API's work to find matching notes.
The **status only** rows omit those searches on both sides: AnkiConnect and the
shim use one `canAddNotesWithErrorDetail` action; native uses
`POST /v1/notes:check?include_duplicate_ids=false`.

For 100 duplicates, native takes 10.8 ms with IDs and 6.6 ms without them.
Skipping IDs removes 100 duplicate searches, but the native status-only median
is still higher than the equivalent AnkiConnect and shim medians in this fixture.
The default native check still returns IDs. See
[note checks](creating_notes.md#check-without-saving) for the response and policy.

These are different tasks, not a single overall speed score. Fewer HTTP requests
do not guarantee less server processing: native responses include schema
validation, field selection and their response envelope. The timings compare
implementations in this environment; they do not isolate individual code changes.

### Media writes

Each of 1,000 notes has a unique 16 KiB image and 16 KiB audio attachment. The
existing-media case starts with those exact files already stored. Medians below
use two repeated trials after first use; times are in **seconds**. These trials
use disposable collections under `/tmp` on ext4.

| Media state | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| New files | 43.93 | 48.29 | 17.67 |
| Existing identical files | 5.12 | 5.24 | 2.38 |

New-file repeated samples: AnkiConnect 41.47–46.39 s; shim 47.17–49.41 s; native 17.47–17.86 s.
Compare these with the [tmpfs control](#storage-sensitivity) before generalizing
the ranking. Restoring collections does not reset filesystem caches or disk history.

Native sends all 2,000 attachments in one `POST /v1/media` array, uses the
returned filenames in fields, and submits one `POST /v1/notes` array:
**two requests**. Upstream and the shim accept attachments in one `addNotes`
request. All three still call Anki's media storage backend 2,000 times.

## Live connection benchmark

`tools/benchmark_connections.py` sends real HTTP requests to an already-running
Anki testing profile. It includes the socket connection, Anki's normal event loop
and operation scheduling, and receiving and validating the response. It only
reads note IDs; it does not add, edit or delete collection data.

The runner checks the profile name and server identity before testing. Each
successful read must contain the same note IDs as the preflight search. Tests run
one implementation at a time, with the other add-on disabled and Anki restarted
when switching between AnkiConnect and Tsunagi.

| Case | What it checks |
| --- | --- |
| 1, 16, 64 and 256 simultaneous reads | Whether each new connection receives a complete, correct response within five seconds |
| 256 reads with a 30-second deadline | Whether a longer wait allows the burst to finish |
| Clients disconnect during headers or after sending a request | Whether fresh requests still work afterward |
| One incomplete request body held open | Whether an independent read can finish within one second while that connection remains open |

Each case runs three times. Every attempt opens a new connection without retries.
Reports distinguish HTTP errors, API errors, timeouts, refused/reset connections,
connections closed without a response, and incomplete or incorrect responses.
Latency percentiles cover successful attempts only; failure counts must be read
alongside them. Client-initiated disconnects are counted separately from server
failures, and sending a request before disconnecting does not prove it executed.

Run the client on the same operating system as Anki for a loopback measurement:

```sh
python tools/benchmark_connections.py \
  --url http://127.0.0.1:7777 --profile "YOUR TEST PROFILE" \
  --implementation shim --output dist/benchmarks/live-connections-shim.json
```

Repeat with `--implementation native` in the same Tsunagi session. Then disable
Tsunagi, enable AnkiConnect, restart Anki, and run with `--implementation upstream`
and its port. Keep the profile, query, server settings and background workload
unchanged. `--preflight-only` checks the setup without load testing. If needed,
set `TSUNAGI_BENCH_API_KEY` in the client's environment; keys are not saved in
reports. These measurements do not cover write cancellation, media uploads,
connection pooling, or sustained traffic over a long period.

### Current desktop results

Measured on **2026-09-21**, using Windows loopback, full Anki **26.09.2**, and a
testing profile with **4,547 notes**. Each read requested that collection's
note IDs: `findNotes` through AnkiConnect/the shim, or `GET /v1/notes?select=id&search=` through
the native API, without pagination. Tsunagi reported add-on version **0.2.0**;
its 89 installed Python modules matched this workspace's current source, including
the tested ID-query fix. All implementations ran sequentially, with only one
add-on enabled at a time.

**Both Tsunagi APIs completed every measured request; AnkiConnect refused many
connections in the larger bursts.** At concurrency 256, each Tsunagi API
completed 768 / 768 requests; AnkiConnect completed 145 / 768. All three runs
finished, including the disconnect and stalled-upload tests.

| Simultaneous reads | AnkiConnect: successful / attempted | Shim: successful / attempted | Native: successful / attempted |
| --- | --- | --- | --- |
| 1 | 3 / 3 | 3 / 3 | 3 / 3 |
| 16 | 48 / 48 | 48 / 48 | 48 / 48 |
| 64 | 124 / 192 | 192 / 192 | 192 / 192 |
| 256 | 145 / 768 | 768 / 768 | 768 / 768 |

Successful-response latency, **median / p95**, in milliseconds:

| Simultaneous reads | AnkiConnect | Shim | Native |
| --- | --- | --- | --- |
| 1 | 32.6 / 33.5 | 3.8 / 3.9 | 10.8 / 10.8 |
| 16 | 612.9 / 1,124.9 | 31.3 / 42.8 | 142.6 / 150.8 |
| 64 | 1,186.8 / 2,187.2 | 107.6 / 122.9 | 556.6 / 669.6 |
| 256 | 1,559.1 / 2,525.4 | 316.3 / 465.3 | 1,421.2 / 2,280.3 |

Counts combine the trials at each level; latency uses their successful samples.
Read latency alongside the completion counts: AnkiConnect's larger-burst
percentiles describe only the requests whose connections succeeded. The shim
remains faster than native for this simple lookup; native still performs query
planning and projection. Native ID-only note queries now use the IDs already
returned by Anki's search without loading every matching note. Queries needing
other fields still load those records, and every request reads fresh data.

AnkiConnect's failed burst attempts were **connection refusals before any HTTP
response**, not JSON error replies or timeouts. With a 30-second deadline, it
completed 154 / 768 requests and refused 614; allowing more time did not resolve
the refusals. These counts describe this burst pattern on this Windows session,
not a general maximum number of supported clients.

Both Tsunagi APIs also completed all **768 / 768** reads in the separate
long-deadline case. Across both deadline settings, each completed **1,779 / 1,779**
measured reads, while AnkiConnect completed **474 / 1,779** and refused 1,305
connections.

For each Tsunagi API, all **384** deliberate disconnect attempts reached the
client's send/abort step; the following recovery queries succeeded. Independent
queries during the three stalled uploads completed in **3.8–4.4 ms** for the
shim and **11.8–13.0 ms** for native, below their one-second deadline.
AnkiConnect reached the send/abort step in 286 / 384 attempts; the other 98 were
connection refusals. Its recovery queries succeeded, but each of the three
independent queries during a stalled upload exceeded the one-second deadline.

Raw reports: `dist/benchmarks/live-connections-upstream.json`,
`live-connections-shim-rerun.json` and `live-connections-native-rerun.json`.
`current-live-run-manifest.json` identifies these reports and their hashes.
All three runs
used the same client source and verified the same note IDs. The installed
AnkiConnect web server and utility module matched the pinned reference used in
the processing tests; its main module differed, so the live run is not labeled
with that checkout's commit. `live-upstream-source.json` records the installed
source hashes. The client-only tests also exercise silent closure,
truncated replies, explicit HTTP/API errors and incorrect IDs; those synthetic
outcomes are not findings about either Anki add-on.

## What each workload compares

| Task | AnkiConnect and shim | Native |
| --- | --- | --- |
| Read all cards | `findCards`, then `cardsInfo` | `GET /v1/cards` with equivalent fields selected; omitted `limit` returns everything |
| Create text notes | One `addNotes` action | One `POST /v1/notes` with an array |
| Create notes with media | One `addNotes` action, with attachments | One `POST /v1/media` array, then one `POST /v1/notes` array |
| Duplicate status only | One `canAddNotesWithErrorDetail` action | One `POST /v1/notes:check?include_duplicate_ids=false` |
| Duplicate status and IDs | `canAddNotesWithErrorDetail`, then `findNotes` actions inside one `multi` for duplicate candidates | One `POST /v1/notes:check` |
| Models with field names | `modelNamesAndIds`, then `modelFieldNames` actions inside one `multi` | One model query selecting `id,name,fields[].name` |
| Save a note and get its card IDs | `addNote`, then `findCards` | One `POST /v1/notes?include=cards` returning note and card IDs |

The mixed duplicate fixture contains both existing and new candidates. The
all-duplicate fixture contains distinct saved words. Neither check creates notes.
The save-and-card-ID fixture uses a note type that produces two cards.

The `multi` workloads give AnkiConnect a batched transport comparison. The tool
also accepts `model_fields` and `duplicate_ids` to measure separate follow-up
requests, but those are not the timings in the table above.

Creation fixtures explicitly set `allowDuplicate: false` and contain distinct,
valid notes. They compare successful writes. Error behavior differs: upstream's
`addNotes` removes its successful additions if any input fails; the native batch
keeps successful additions and reports rejected input positions. See
[batch creation](creating_notes.md) for the response format.

For card reads, `--batches 0` requests everything at once. Positive values measure
smaller responses: native follows cursors, while AnkiConnect splits `cardsInfo`
over the discovered IDs. Pagination can bound response size and let clients
process data incrementally, but creates additional requests when all records
are wanted. There is no implicit native page limit.

## What the overhead investigation established

- **Query responses:** standard pages containing JSON values use a small shared
  encoder instead of another recursive Pydantic conversion and a general-purpose
  encoder visit for every scalar. Special values fall back to the original
  whole-page conversion; custom response schemas retain normal validation.
  Aliases, dates, custom model encoders and SQLAlchemy attribute exclusions keep
  their existing behavior. Full-card schema validation still runs.
- **Row export:** ordinary validated models use a shared exporter for full rows,
  flat field selections and nested selections such as `fields[].name`. Custom export methods,
  schema-level include/exclude rules, unusual values and other selection masks
  use Pydantic's original export. Rows still use human-readable field names and
  fresh containers.
  The 10,000-card fixture retains 30,001 validations: 10,000 card models,
  20,000 note-field models and one page envelope. These are separate objects,
  not three validation passes over each card.
- **Note checks:** the adapter uses the already-validated request models directly.
  It resolves each distinct note type and deck once within the request, while
  validating every candidate against the current collection. Disabling duplicate
  IDs skips only the additional ID lookup, not duplicate detection. The adapter
  returns plain result records for FastAPI to validate once against the response
  schema. Invalid output is still rejected and fields outside the schema are
  removed. The 100-candidate profile has 202 validations: 100 input notes,
  100 output results and the two envelopes.
- **Selected fields:** row conversion includes only the requested source
  fields. Common scalar and array selections use direct projection; unusual
  structures retain the existing projection behavior. Model validation still
  runs, including for fields omitted from the response.
- **Model loading:** requesting field metadata still needs Anki's model records.
  The 100-model profile makes 100 model-record loads and one names-list call.
  Its remaining cost includes 401 model-validation calls. Avoiding conversion
  of unused templates does not eliminate validation or those backend loads.
- **Native batch creation:** one collection operation shares model/deck lookup
  results, validates each candidate against the current collection, and returns
  IDs without reloading saved note records. The 1,000-note profile resolves the
  model and deck once, performs 1,000 note writes with no saved-note reloads
  or card-ID lookups, and merges undo entries after each subsequent success.
  Backend note writes dominate this workload. Subscribed events can request
  card-ID details; the headless fixture has no event subscribers.
- **Native media batches:** source decoding and downloads stay on the request
  thread. Storage dispatches contain at most 64 files and target at most 8 MiB
  of decoded data; a larger permitted file is stored alone. The 2,000 small
  base64 uploads in this fixture need 32 collection dispatches, followed by
  one collection operation to create the notes. Every file still goes through
  Anki’s media backend.

Full-card profiles still show substantial Pydantic conversion, validation and
JSON encoding cost. These optimizations keep that behavior intact; they do not
bypass validation, retain collection results between requests, or share mutable
Note instances between cards.

### Filtered card projections

For `GET /v1/cards?select=id,question&where=queue==-1`, the scan now reads only
`id` and `queue` until it knows which rows match. It renders questions for the
matching rows. The earlier explicit-selection path rendered every scanned card.
Omitting `limit` returns all matches in both variants.

| Cards scanned | Matches | Selection | Eager hydration | Deferred hydration |
| --- | ---: | --- | ---: | ---: |
| 100 | 1 | `id,question` | 7.16 ms | 1.18 ms |
| 100 | 1 | `id,queue` | 0.88 ms | 0.88 ms |
| 10,000 | 100 | `id,question` | 603.70 ms | 29.15 ms |
| 10,000 | 100 | `id,queue` | 23.43 ms | 23.63 ms |

Measured on 2026-09-21 with Anki 26.09.2 / Python 3.13.9 and the working-tree
changes after `be6cb46`. The raw report records source hashes. Both variants run
the same current code; the control disables only the resource's declaration
of expensive field groups. It reproduces the previous eager behavior for these
explicit selections, rather than comparing different full runtime versions.

Medians use five repeated requests after a separately recorded first request.
Requests run sequentially on the same disposable collection, reversing variant
order each round. Results match exactly. Separate instrumented requests confirm
that the 10,000-card question query renders 100 cards instead of 10,000; the
cheap-column control renders none and remains a single-phase query. The
measurement includes the headless HTTP client and JSON decoding, with fake Qt
dispatch and no network socket. It is a native before/after comparison, not an
AnkiConnect speed comparison.

### Membership filters

When a query reaches Python filtering, `in [...]` and `not in [...]` prepare
one membership set per clause. Each row still reads its current values. The
same implementation handles notes, cards and other query resources; Anki search
and index routes can bypass this filter entirely.

A native `GET /v1/notes` diagnostic selects note IDs and filters `tags[]` against
a supplied list. These are complete request timings through the headless HTTP
harness, including real Anki reads and response decoding. Only the shared filter
module is swapped for the comparison; all other code is identical.

| Notes scanned | Tags in the filter | Previous filter | Current filter |
| --- | ---: | ---: | ---: |
| 100 | 10 | 2.2 ms | 2.2 ms |
| 100 | 1,000 | 6.1 ms | 5.6 ms |
| 10,000 | 10 | 155.3 ms | 150.9 ms |
| 10,000 | 1,000 | 259.1 ms | 177.4 ms |

Measured on 2026-09-21 with the current working tree after `be6cb46`, using
the filter from `e3a59e8` as the control, on Python 3.13.9 / Anki 26.09.2.
Values are medians of seven repeated requests, with a separate first request.
The largest case returns 5,000 matching IDs and builds one set instead of
10,000. An equality filter without a membership list measured 147.5 ms versus 150.2 ms for 10,000 notes.

Workers run sequentially on copies of the same disposable collection. Each
worker repeats reads on its open collection. Separate checks confirm GET/POST
results, set-construction counts, and that the same query sees a saved tag edit
immediately. These timings exclude real Qt scheduling and network transport.

### Real Qt dispatch

The bulk harness substitutes synchronous Qt dispatch so request-processing
profiles remain reproducible. A separate tool measures Tsunagi's production
operation wrappers with real Qt signals, Anki's task manager, `QueryOp`,
`CollectionOp`, and progress widgets.

Anki/aqt 26.09.2, Python 3.13.9, PyQt6 bindings 6.11.0; medians of five repeated
trials after first use:

| Work arrangement | Total ms | Time outside the operation bodies, ms |
| --- | ---: | ---: |
| 100 individual query operations | 7.527 | 6.966 |
| One query operation containing the same 100 reads | 0.215 | 0.074 |
| 100 individual collection operations | 40.202 | 40.077 |
| One collection operation containing 100 empty change results | 0.424 | 0.413 |

The query body reads an empty collection's note count. Collection bodies return
empty change flags. This isolates dispatch and wrapper costs; it does **not**
measure real writes, full Anki window repainting, undo-menu rendering, socket
latency or interaction with other add-ons. The host uses offscreen Qt and a
minimal main-window substitute. These numbers cannot simply be added to the
bulk timings to predict desktop performance.

Batching can avoid repeated dispatch when the operation's behavior permits it.
It still needs correct validation ordering, undo boundaries, events and access
to current collection data.

### Storage sensitivity

The same media workloads also run with disposable files under `/dev/shm`
(tmpfs), compared with the normal `/tmp` directory on ext4. This is a storage
sensitivity check, not a suggested place to keep an Anki collection.

| Media state on tmpfs | AnkiConnect, seconds | Shim, seconds | Native, seconds |
| --- | ---: | ---: | ---: |
| New files | 0.910 | 1.017 | 0.992 |
| Existing identical files | 0.824 | 0.926 | 0.860 |

With most physical storage cost removed, native media creation is close to the
other implementations. Batching avoids thousands of separate HTTP requests and
collection dispatches, while retaining Anki's storage behavior. The large gap
between new-file timings on ext4 and tmpfs shows that media comparisons are
particularly sensitive to the storage environment and execution order.

All implementations use Anki's media backend and verify the saved bytes and
field references. Storage cost includes work inside Anki's Rust backend, which
Python profiling reports at the backend-call boundary. Wall-clock differences
cannot establish individual filesystem or SQL costs. Repeated samples restore
files, but do not flush the operating system's caches or control disk history.

## Reproduce the measurements

Use Python 3.13.9 and Anki/aqt 26.09.2 to match this snapshot, plus the test
dependencies and a built `lib/shared` directory. The core harness requires
Python 3.12 or newer.
Pass a checkout of the pinned upstream revision. These commands use disposable
collections and do not contact a running Anki instance.

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

Run these sequentially. To repeat the media storage check, add
`--scratch-dir /dev/shm` and use a different output path. For a quick smoke test,
use `--write-sizes 40 --repeats 2`. Stop video transcoding and other heavy
work during timing.

For filtered projections (no AnkiConnect checkout needed):

```sh
python tools/benchmark_filtered_projection.py --sizes 100 10000 --repeats 5 \
  --output dist/benchmarks/current-filtered-projection.json
```

For the native filter comparison (no AnkiConnect checkout needed):

```sh
python tools/benchmark_filtering.py --baseline-ref e3a59e8 \
  --rows 100 10000 --allowed 0 10 1000 --repeats 7 \
  --output dist/benchmarks/current-filtering.json
```

`--allowed 0` adds the equality control. The baseline commit must be available
in the local Git checkout.

For the Qt measurement, use an environment with aqt and PyQt installed:

```sh
python tools/benchmark_dispatch.py --count 100 --repeats 5 \
  --output dist/benchmarks/current-dispatch.json
```

## Read the raw reports

The reports in `dist/benchmarks/current-*.json` contain the current measurements.
`current-run-manifest.json` records the commands, run times and source hashes
across all six benchmark groups, and verifies that the source stayed unchanged.

The main comparison reports record versions, the source commit, source hashes, execution order,
first-use and repeated timings, response sizes, request/action counts, worker
peak RSS, verification fingerprints, and a separate profiled trial. Worker RSS
includes the interpreter and fixture setup; it is not the memory used by one
request. A source-dirty flag also includes documentation edits. The filter
diagnostic records first/repeated timings, membership-set counts and result/live-edit
checks; it does not collect a profile or peak RSS.

Card verification compares complete equivalent records in order. Write checks
verify note/card counts, fields, tags and media content; generated IDs and
timestamps are normalized when comparing separate collections. Model and
duplicate checks compare the IDs and relationships against the collection.
Profiling is separate from timed trials, and its cumulative timings overlap.
API/backend call counts are not SQL-query counts.

Anki's duplicate check is a concrete example of an API boundary adding work:
its [internal check](https://github.com/ankitects/anki/blob/26.08.1/rslib/src/notes/mod.rs#L580)
retrieves candidate note IDs and fields, but reduces matches to a boolean. The
[add-on-facing response](https://github.com/ankitects/anki/blob/26.08.1/proto/anki/notes.proto#L106)
contains only a validation state. Tsunagi therefore uses a second lookup to return
matching IDs. Returning those IDs from Anki's original check could avoid repeated
work; the current Anki API does not expose them in that response.

The headless comparison uses upstream's HTTP wrapper without a listening socket,
and FastAPI's in-process test client for Tsunagi. It includes request decoding,
application work, response encoding and client decoding, but transport wrappers
differ. Full desktop comparisons with other add-ons remain a separate measurement.

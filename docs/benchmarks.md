# API benchmarks

[← Documentation](README.md)

This page reports the current comparison of upstream AnkiConnect, Tsunagi's
AnkiConnect compatibility API, and its native endpoints. It is updated in place.

**These are measurements of request processing in disposable collections, not
end-to-end desktop latency.** Each implementation runs separately. The harness
verifies the resulting data before accepting a sample.

## Current results

Anki **26.8.1**, Python **3.12.12**, Linux/WSL. Core measurements use runtime
`d6e32db`. Media measurements use `e46b946`; those write paths are unchanged.
Upstream is pinned to `de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`.
These medians use five repeated trials after a separately recorded first-use
trial. Every trial starts from a restored collection. All thirteen workloads passed
their equivalence checks. Times are in **milliseconds**; lower is faster.

| Equivalent task | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| 10,000 cards, full equivalent records | 702.9 | 1,103.8 | 1,419.2 |
| 1,000 text notes | 1,538.7 | 1,554.4 | 1,574.3 |
| 10 duplicates: status and note IDs | 4.5 | 4.4 | 2.2 |
| 100 duplicates: status and note IDs | 34.6 | 29.7 | 10.9 |
| 10 mixed candidates: status and note IDs | 3.2 | 3.0 | 1.7 |
| 100 mixed candidates: status and note IDs | 19.7 | 16.3 | 9.1 |
| 10 duplicates: status only | 1.2 | 1.2 | 1.5 |
| 100 duplicates: status only | 5.3 | 4.7 | 7.3 |
| 10 mixed candidates: status only | 1.2 | 1.5 | 1.5 |
| 100 mixed candidates: status only | 4.6 | 4.4 | 6.6 |
| 10 models with their field names | 2.0 | 1.6 | 1.5 |
| 100 models with their field names | 8.0 | 4.1 | 7.5 |
| Save one note and get its two card IDs | 6.3 | 6.8 | 5.8 |

Native batch creation is roughly even with the other implementations for this
text workload. It returns created note IDs and groups successful additions into
one undo step. The duplicate workflows benefit from receiving
status and IDs together. Full-card reads remain faster through upstream, and
loading 100 models with fields is fastest through the shim in this fixture.

The **status plus IDs** rows include each API's work to find matching notes.
The **status only** rows omit those searches on both sides: AnkiConnect and the
shim use one `canAddNotesWithErrorDetail` action; native uses
`POST /v1/notes:check?include_duplicate_ids=false`.

For 100 duplicates, native takes 10.9 ms with IDs and 7.3 ms without them.
Skipping IDs removes 100 duplicate searches, but native validation-only remains
slower than the equivalent AnkiConnect and shim actions in this fixture. The
default native check still returns IDs. See [note checks](creating_notes.md#check-without-saving)
for the response and duplicate policy.

These are different tasks, not a single overall speed score. In particular,
fewer HTTP requests do not guarantee less server processing: native responses
include schema validation, field selection and their response envelope.

### Media writes

Each of 1,000 notes has a unique 16 KiB image and 16 KiB audio attachment. The
existing-media case starts with those exact files already stored. Medians below
use two repeated trials after first use; times are in **seconds**.

| Media state | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| New files | 46.96 | 46.66 | 15.87 |
| Existing identical files | 2.55 | 2.71 | 2.46 |

Treat this disk-backed ranking cautiously. Native's new-file samples were 15.74
and 15.99 seconds, while the shim's were 46.13 and 47.20 seconds. The storage
control below changes the ranking, so this is not evidence of a general native
advantage for media writes.

Native sends all 2,000 attachments in one `POST /v1/media` array, uses the
returned filenames in fields, and submits one `POST /v1/notes` array:
**two requests**. Upstream and the shim accept attachments in one `addNotes`
request. All three still call Anki's media storage backend 2,000 times.

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
- **Note checks:** the adapter uses the already-validated request models directly.
  It resolves each distinct note type and deck once within the request, while
  validating every candidate against the current collection. Disabling duplicate
  IDs skips only the additional ID lookup, not duplicate detection.
- **Selected fields:** Pydantic conversion includes only the requested source
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

### Real Qt dispatch

The bulk harness substitutes synchronous Qt dispatch so request-processing
profiles remain reproducible. A separate tool measures Tsunagi's production
operation wrappers with real Qt signals, Anki's task manager, `QueryOp`,
`CollectionOp`, and progress widgets.

Anki/aqt 26.8.1, Python 3.12.12, PyQt6 bindings 6.11.0; medians of five repeated
trials after first use:

| Work arrangement | Total ms | Time outside the operation bodies, ms |
| --- | ---: | ---: |
| 100 individual query operations | 11.651 | 10.525 |
| One query operation containing the same 100 reads | 0.283 | 0.122 |
| 100 individual collection operations | 46.812 | 46.554 |
| One collection operation containing 100 empty change results | 0.427 | 0.417 |

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
| New files | 0.882 | 1.008 | 0.962 |
| Existing identical files | 0.892 | 0.928 | 0.917 |

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

Use Python 3.12+, the test dependencies, Anki, and a built `lib/shared` directory.
Pass a checkout of the pinned upstream revision. These commands use disposable
collections and do not contact a running Anki instance.

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads read_cards,add_text,duplicate_ids_multi,duplicate_mixed_multi,duplicate_status,duplicate_mixed_status,model_fields_multi,save_card_ids \
  --read-sizes 10000 --write-sizes 1000 --workflow-sizes 10,100 \
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

For the Qt measurement, use an environment with aqt and PyQt installed:

```sh
python tools/benchmark_dispatch.py --count 100 --repeats 5 \
  --output dist/benchmarks/current-dispatch.json
```

## Read the raw reports

Reports record versions, the source commit, source hashes, execution order,
first-use and repeated timings, response sizes, request/action counts, worker
peak RSS, verification fingerprints, and a separate profiled trial. Worker RSS
includes the interpreter and fixture setup; it is not the memory used by one
request. A source-dirty flag also includes documentation edits.

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

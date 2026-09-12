# API benchmarks

[← Documentation](README.md)

This page reports the current comparison of upstream AnkiConnect, Tsunagi's
AnkiConnect compatibility API, and its native endpoints. It is updated in place.

**These are measurements of request processing in disposable collections, not
end-to-end desktop latency.** Each implementation runs separately. The harness
verifies the resulting data before accepting a sample.

## Current results

Anki **26.8.1**, Python **3.12.12**, Linux/WSL. The main comparison uses runtime
`99f1f3e`; native batch-write measurements were refreshed at `416edb4` after
simplifying their responses. The compared upstream and shim paths are unchanged.
Upstream is pinned to `de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`.
These medians use five repeated trials after a separately recorded first-use
trial. Every trial starts from a restored collection. All nine workloads passed
their equivalence checks. Times are in **milliseconds**; lower is faster.

| Equivalent task | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| 10,000 cards, full equivalent records | 738.4 | 1,152.9 | 1,808.4 |
| 1,000 text notes | 1,551.8 | 1,588.4 | 1,528.5 |
| 10 duplicates: status and note IDs | 4.4 | 4.0 | 2.1 |
| 100 duplicates: status and note IDs | 35.2 | 30.6 | 13.2 |
| 10 mixed new/duplicate candidates | 3.4 | 2.9 | 1.9 |
| 100 mixed new/duplicate candidates | 19.4 | 16.4 | 10.8 |
| 10 models with their field names | 2.0 | 1.6 | 1.5 |
| 100 models with their field names | 8.0 | 3.9 | 8.1 |
| Save one note and get its two card IDs | 6.5 | 6.2 | 6.3 |

Native batch creation is roughly even with the other implementations for this
text workload. It returns created note IDs and groups successful additions into one undo step. The duplicate workflows benefit from receiving
status and IDs together. Full-card reads remain faster through upstream, and
loading 100 models with fields is fastest through the shim in this fixture.

The duplicate rows compare **status plus matching IDs**. For the 100-duplicate
fixture, upstream's check-only action takes 5.5 ms, the shim's takes 4.7 ms, and
the native request takes 13.2 ms including IDs. Native currently always retrieves
duplicate IDs; a client needing only yes/no pays for that extra work. The
35.2 ms upstream total includes its follow-up ID searches. Individual action
medians need not add up exactly to the median of the complete workflow.

These are different tasks, not a single overall speed score. In particular,
fewer HTTP requests do not guarantee less server processing: native responses
include schema validation, field selection and their response envelope.

### Media writes

Each of 1,000 notes has a unique 16 KiB image and 16 KiB audio attachment. The
existing-media case starts with those exact files already stored. Medians below
use two repeated trials after first use; times are in **seconds**.

| Media state | AnkiConnect | Tsunagi shim | Native Tsunagi |
| --- | ---: | ---: | ---: |
| New files | 46.09 | 37.28 | 17.86 |
| Existing identical files | 2.70 | 3.06 | 4.61 |

Treat this disk-backed ranking cautiously. For new files, the shim's two repeated
samples were 27.52 and 47.04 seconds. The storage control below changes the
ranking, so this is not evidence of a general native advantage for media writes.

Native uploads the 2,000 attachments through `POST /v1/media`, uses the returned
filenames in fields, and submits one `POST /v1/notes:batch-create`: **2,001 requests**.
Upstream and the shim accept attachments in one `addNotes` request. All three
still call Anki's media storage backend 2,000 times. Native batch creation does
not add an attachment envelope or a bulk-media endpoint.

## What each workload compares

| Task | AnkiConnect and shim | Native |
| --- | --- | --- |
| Read all cards | `findCards`, then `cardsInfo` | `GET /v1/cards` with equivalent fields selected; omitted `limit` returns everything |
| Create text notes | One `addNotes` action | One `POST /v1/notes:batch-create` |
| Create notes with media | One `addNotes` action, with attachments | Upload each file, then create the prepared notes in one batch |
| Duplicate status and IDs | `canAddNotesWithErrorDetail`, then `findNotes` actions inside one `multi` for duplicate candidates | One `POST /v1/notes:check` |
| Models with field names | `modelNamesAndIds`, then `modelFieldNames` actions inside one `multi` | One model query selecting `id,name,fields[].name` |
| Save a note and get its card IDs | `addNote`, then `findCards` | One `POST /v1/notes` returning the note and card IDs |

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

- **Query responses:** the standard native query envelope is validated and
  encoded without FastAPI repeating the same response conversion. Custom response
  schemas retain the normal validation path. JSON values and aliases remain
  consistent with FastAPI's encoder.
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
  or card-ID lookups, and merges undo entries after each subsequent success. Backend note writes
  dominate this workload. Subscribed events can request card-ID details; the
  headless fixture has no event subscribers.

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
| New files | 0.915 | 1.101 | 2.531 |
| Existing identical files | 0.864 | 1.010 | 2.500 |

Removing most physical storage cost makes native's separate upload requests more
visible. They remain slower here despite one final batch-create request. The
large gap between new-file timings on ext4 and tmpfs shows that media comparisons
are particularly sensitive to the storage environment and execution order.

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
  --workloads read_cards,add_text,duplicate_ids_multi,duplicate_mixed_multi,model_fields_multi,save_card_ids \
  --read-sizes 10000 --write-sizes 1000 --workflow-sizes 10,100 \
  --batches 0 --repeats 5 --output dist/benchmarks/current-core.json

python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads add_media_new,add_media_existing --write-sizes 1000 \
  --implementations native,shim,upstream --repeats 2 \
  --output dist/benchmarks/current-media.json
```

Run these sequentially. To repeat the media storage check, add
`--scratch-dir /dev/shm` and use a different output path. For a quick smoke test,
use `--write-sizes 40 --repeats 2`. Keep other heavy work stopped during timing.

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

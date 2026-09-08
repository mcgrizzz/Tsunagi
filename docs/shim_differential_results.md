# Upstream differential test results

2026-09-07. The reference is AnkiConnect commit
[`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`](https://git.sr.ht/~foosoft/anki-connect/commit/de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e).
Both implementations run against **Anki 23.10, Python 3.12.12**, with the same
seed data and IDs in separate disposable SQLite collections.

The initial run had **76 matches and 14 mismatches in 90 differential cases**.
All ten confirmed differences below are now fixed: **90/90 differential cases pass**,
with their expected-failure markers removed. Ten additional regression cases run
without an upstream checkout and pass on the Python 3.10 / Anki 23.10 test environment.

After the fix, the full suite reports **962 passed, 8 skipped, zero expected failures**
on Python 3.12.12 / Anki 23.10. Ruff and whitespace checks pass for the changed files.
The code is synced and reloaded in the installed addon. Read-only live checks on
`[DEV] Yomine` passed for version argument errors, numeric queries, unprefixed search
errors, null/zero card inputs, mixed valid/zero cards, missing note modification times,
missing-card deck fallback, reflection scope omission, and the 122-action inventory.
A 1002-note request confirmed ordering, missing-note placeholders and repeated card
IDs across the 999-ID boundary. Existing nested deck `TestSuite::Shim` reports leaf
name `Shim`. Default currently contains one card, so its empty-deck omission case
remains covered by the isolated upstream comparison rather than this live check.
No collection data was changed during these live checks.

## Mutation and media follow-up

The suite now contains **127 differential cases across 45 action names**: **126 pass**
and one strict expected failure records the local-path gate described below.
Full suite: **1001 passed, 8 skipped, one expected failure** on Python 3.12.12 /
Anki 23.10. Ruff passes for the changed Python files.
Added comparisons cover media collisions, explicit null deletion flags, skip hashes,
invalid base64, local files, a local HTTP download server, data/path precedence,
note updates, duplicate/missing-ID deletion, addNotes rollback, and probe media
side effects on valid, empty and duplicate notes. Media and note field/tag/card state
are compared in addition to responses. Mutation timestamps and undo state still
require separate comparison; the note-state helper does not assert those fields.

Two more mismatches were fixed:

- **D12:** `storeMediaFile(deleteExisting=null)` now preserves the original file
  and lets Anki choose the collision filename, as upstream does.
- **D13:** all four `canAddNote(s)`/error-detail variants now prepare media before
  the empty/duplicate check, including writing files on rejected probes. No probe
  note is inserted. Media work uses a collection operation; downloads/decode remain
  outside that operation. The standalone regression suite includes these effects.

**D11 remains open:** local-path uploads are blocked by Tsunagi's default
`gates.media_allow_local_path=false`; upstream permits them. The enabled-gate case
passes. A strict expected-failure case records the default mismatch, rather than
changing the live user's configuration. The settings/migration todo includes this
policy decision. This is the only expected failure in the current differential suite.

The original 90 cases below remain passing. After reload, the media/probe fixes also
passed live on `[DEV] Yomine`: `deleteExisting=null` retained the original bytes and
stored the replacement under Anki's collision filename. All four probe actions
wrote the expected media bytes for both accepted and rejected empty notes; searching
the unique probe prefix found no inserted notes. All ten temporary media files were
deleted, and the prefix listing was confirmed empty afterward. The active profile
remained `[DEV] Yomine`; no live configuration gates were changed.

## Model and scheduler follow-up

At this checkpoint: **164 passed, one expected failure in 165 differential cases**,
with 63 distinct action handlers observed. Full suite: **1044 passed, 8 skipped,
one expected failure** on Python 3.12.12 / Anki 23.10. The expected failure remains
D11 (default local-path policy). Changed-file Ruff and whitespace checks pass.

Added 38 differential cases covering template/style edits, field rename/order/add/
remove and metadata, template addition/removal, a no-op model replacement, and scheduling
on new and review cards (ease factors, due dates, forget, relearn, suspend/unsuspend).
These compare model cache contents, persisted models after cache invalidation,
note fields/tags, card scheduling columns and review rows as well as RPC responses.
Five standalone regressions run without the reference checkout.

The pass found and fixed five differences:

- D14: native field renaming left stale template references in the working model.
  Use Anki's rename-and-save helper before applying the final property save. The
  native regression verifies rendering, persisted references and simultaneous font
  changes; the shim continues to call the shared native mutation.
- D15: empty/unknown template updates now save the model as upstream does, including
  its sync metadata side effect.
- D16: adding an existing template changes Anki's model cache without saving it.
  Earlier documentation incorrectly described the change as simply discarded.
  This unusual behavior is isolated in a compatibility adapter; ordinary template
  creation still uses the native method.
- D17: a short ease-factor array now retains prior writes and raises the same
  error at the first present card lacking a factor. Missing cards are skipped
  before the factor lookup. The shim still delegates writes to the native method.
- D18: invalid due-date errors expose the original Anki message through the shim;
  native errors retain their additional context.

This is a focused mutation pass, not complete scheduler/model coverage. Remaining
cases include model creation, more malformed inputs and replacement side effects,
answer/partial-answer behavior, repeated suspension, review insertion and undo/Qt
effects.

After the user reloaded the synced addon, targeted live checks passed on Anki
26.08.1 using a disposable model, two notes/cards and a dedicated deck:

- Native field PATCH rewrote template references and preserved rendered content.
- An empty template update succeeded; adding an existing template immediately
  exposed its changed front through the model-template reader.
- A short ease-factor array returned `list index out of range` and retained only
  the first card's factor change, verified through `getEaseFactors`.
- Invalid due dates returned Anki's exact `invalid` error.

The notes, model, leaf deck and empty parent deck were deleted and cleanup verified.
Cache-versus-disk persistence and model sync metadata remain covered by the isolated
comparisons, not by these live HTTP checks. No additional production changes or
reload were needed after this verification.

## Creation, replacement and partial-answer follow-up

Current result: **195 passed, one expected failure in 196 differential cases**,
with 65 distinct action handlers observed. Full suite: **1083 passed, 8 skipped,
one expected failure** on Python 3.12.12 / Anki 23.10. D11 remains the sole expected
failure (default local-path policy). Ruff and whitespace checks pass.

Commit `06f9566` adds 31 differential cases: 13 model-creation cases, seven literal
replacement cases, eight answer sequences and three backend undo/redo cases. Eight
additional regressions run without an upstream checkout.

- D19: `createModel` now requires both template sides and returns Anki's model
  validation errors instead of a generic failure. Successful normal/cloze models,
  default/empty/custom CSS, duplicate names, missing sides, empty names and invalid
  templates are compared. Failed creation must leave no model behind.
- D20: `findAndReplaceInModels` now saves every targeted model, including nonmatches,
  and exposes Anki template-validation errors. The shared native method provides
  an explicit `save_unmatched` option; its default still saves only matches. Tests
  compare both template changes and sync metadata, including all-model calls.
- D21: `answerCards` now applies valid entries before a missing key. An invalid
  ease earlier in the sequence takes precedence over a later missing key. Writes
  still use the native scheduler method. Tests compare response errors, card
  state and review rows, including missing cards and duplicate IDs.

Backend undo/redo restores the matching collection state after a successful answer,
a missing-ease failure and an invalid-ease failure. This proves backend behavior
for those cases; real Qt refresh and grouping require separate live checks.

After reload, the installed addon passed the following checks on Anki 26.08.1:

- Missing `Front`/`Back` and an invalid field reference produced the expected
  creation errors, with no failed model left behind.
- An unmatched replacement returned zero; a literal replacement changed the
  template as expected. Sync-metadata equality remains an isolated-test assertion.
- Both missing-ease and invalid-ease failures retained the first valid answer.
  The card review counts were `[1, 0]` after each partial failure, then `[0, 0]`
  after calling the real `/v1/gui:undo` endpoint.
- The two temporary notes, deck and model were removed and their absence verified.

This live pass checks GUI undo through its endpoint, not menu labels, focus or
grouping of longer answer batches. No production edits or further reload were
needed after verification.

## Method and limits

[upstream_reference.py](../tools/upstream_reference.py) verifies the checkout's HEAD
and rejects tracked plugin modifications. It loads upstream's original action class,
utility functions and RPC response formatters without starting its server or UI.
Collection access, edit notifications, logging and addon configuration are supplied
by the harness. API settings use upstream defaults. No action implementation is
rewritten or copied into a hand-maintained mock.

[test_upstream_differential.py](../tests/test_upstream_differential.py) compares the
RPC dispatchers' JSON-compatible output, including list order, duplicate IDs,
response keys and exact errors. It also checks persisted tag/queue changes and
media file contents/deletion. Native Anki collection methods use the real Rust
backend. Each case starts from freshly seeded and cloned collections. No live user
collection is opened by this suite.

These are dispatcher and collection comparisons, not HTTP transport, browser
permission or real Qt tests. The fake main window and suppressed edit notifications
cannot prove GUI undo, refresh, focus or dialog behavior. Backend undo/redo has
separate comparisons described above. This run does not establish
complete compatibility on Anki 26.08.1; the live smoke checks above cover a subset.
The initial collection is cloned so requests address identical IDs. RPC responses
are compared without normalization except successful model creation: independently
allocated model/field/template IDs and model modification timestamps are normalized,
with the returned schema and other values retained. Answer tests hold measured
review time at zero in both implementations. Model/scheduler state comparisons exclude
model modification timestamps and field/template IDs allocated independently by
Anki; new cards are matched by note ID and template ordinal. Sync metadata is
retained. Existing note/card/media comparisons keep their original strict checks.

## Fixed differences

These were the ten differences observed before the fix. The shim now matches the
upstream column for every listed trigger. Compatibility-specific collection reads
live in `tsunagi/adapters/anki/compat.py`; native search validation and deck statistics
keep their existing contract. Broader argument binding/coercion across other actions
remains a separate coverage task; D06 specifically verifies `version`.

| ID | Trigger | Shim | Upstream |
| --- | --- | --- | --- |
| D01 | `getDeckStats` for an empty Default deck alongside a populated child deck | Includes Default's statistics | Omits Default |
| D02 | `findCards` / `findNotes` with `(` or `prop:ivl=nope` | Prefixes the Anki error with `Invalid Anki search: ` | Returns Anki's error without that prefix |
| D03 | `notesModTime` with a missing note ID, including zero | `{"noteId": id, "mod": null}` | `{}` |
| D04 | `cardsInfo` list containing card ID zero | Entire request returns `Action failed` | Returns valid cards and `{}` for zero |
| D05 | `notesInfo` with the same note repeated across the 999-ID batch boundary | One card ID in each note's `cards` list | Repeats that card ID once per relevant batch |
| D06 | `version` with an unexpected argument | Ignores the argument and returns 6 | Python unexpected-keyword error |
| D07 | `findCards` with numeric `query: 123` | Coerces to text and returns an empty result | Rejects the non-string query |
| D08 | `cardsInfo` with `cards: null` | Pydantic validation error | `'NoneType' object is not iterable` |
| D09 | `getDecks` with a missing card ID | Empty map | Groups the ID under Default |
| D10 | `getDeckStats` for `Parity::日本語` | Name is `Parity::日本語` | Name is `日本語` |

D05 reproduces an upstream batching quirk; it is still a visible response difference.
D04 is specifically triggered by zero: a separate 1002-entry `cardsInfo` case with
a positive missing ID matches upstream. D03 also reproduces with a positive missing
ID. Passing large-list tests that omit these combinations would miss these gaps.

## Matching cases

The matching cases include the corrected `apiReflect` responses/errors; API versions
1, 4, 5 and 6; model metadata; ordinary card/note reads; tag additions/removals;
suspension and unsuspension; and base64 media storage, retrieval, listing and deletion
with actual file checks. Search cases include Unicode deck names, hierarchical tags,
negation, nested AND/OR, field regex, queue/property filters and review/date filters.

The initial requests exercised 37 existing action names, with multiple calls in the media and
suspension cases. This is a first differential suite, not proof that those 37 actions
are complete or that all 122 actions match. Error-only equality also does not establish
a successful path. Further media failures/options, advanced scheduler state, mutating model/note
operations, GUI, lifecycle, transport and other supported Anki versions remain in the
[full coverage plan](shim_behavioral_coverage.md).

## Reproduction

Use Python 3.12 or newer because the pinned upstream source uses Python 3.12 f-string
syntax. Install the project's test dependencies with `anki==23.10` and `httpx<0.28`.
The repository's vendored runtime dependencies must already be built.

```sh
TSUNAGI_ANKICONNECT_CHECKOUT=/tmp/tsunagi-anki-connect-audit \
  python -m pytest -q tests/test_upstream_differential.py
```

One strict expected-failure marker remains for D11; use `--runxfail` to reproduce
the default local-path mismatch as an ordinary test failure.
Omit the environment variable to skip these optional comparisons;
the ordinary test suite does not require an upstream checkout. The complete run's
JUnit artifact for the mutation/media follow-up is `/tmp/tsunagi-mutation-media-full.xml`.

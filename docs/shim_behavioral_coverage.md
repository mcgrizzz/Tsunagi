# Full AnkiConnect shim: behavioral coverage

Target: a client can switch from AnkiConnect to Tsunagi's compatibility endpoint
and retain the same observable behavior. Rare actions remain in scope. Native
`/v1` routes have their own contract; passing native filter tests does not establish
AnkiConnect search or RPC parity.

Reference revision: [`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`](https://git.sr.ht/~foosoft/anki-connect/commit/de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e).
The [history audit](parity_history_audit.md) records source and commit-history findings.
The [action inventory](ankiconnect_parity.md) records implementations and known deviations;
“implemented” does not mean behaviorally equivalent.

## Measured coverage, 2026-09-08

An opt-in pytest recorder now measures calls reaching the compatibility registry.
The initial full run observed **97 of 120 registered handlers**. `multi` and
`requestPermission` bypass that registry and have separate protocol tests.

That run found 23 handlers with no observed calls, and `modelTemplateRemove` had
only raised errors. New tests exercise `apiReflect`, `deckNameFromId`, and successful
template removal. The reflection tests exposed and fixed omitted-scope behavior,
an extra response key, and parameter-validation error differences. The updated
[122-action matrix](shim_coverage_matrix.md) provides per-action evidence and links
to test files. It includes uncommon and undocumented actions.

Latest run: **99/120 registered handlers observed; 2067 tests passed, 10 skipped,
one expected failure** on the Anki 23.10 test environment, including 1089 passing
upstream comparisons and the default local-path gate mismatch. Differential
behavioral calls reach 69 registered handlers. Argument-name rejection checks
separately cover all 122 action names, without executing their bodies; these do
not expand the registry execution count or prove GUI/lifecycle parity.
The full Anki 26.08.1 run has **2073 passed, 4 skipped, 1 expected failure**;
the remaining skips assert 23.10-only behavior. The old environment also skips
the two optional real-Qt lifecycle tests. Permission acceptance, ignore,
close, repeated-request and persistence comparisons add 79 cases with simulated
Qt choices, plus 13 standalone regressions. After reload, two sequential live
empty-origin denials returned before timeout; the user confirmed closing the
first dialog with No and Ignore selected. Timeout cleanup has headless Qt coverage.
Media failures add 57 differential cases and nine standalone regressions covering
statuses, redirects, invalid URLs, disconnected downloads, nested error escaping,
existing-file preservation and configured size limits. The live HTTP 404 error and
existing-file preservation check passed after reload; its disposable file was removed.
Replacement option values add 84 differential cases and ten standalone regressions:
the shim preserves Python truthiness and checks hashes before deletion. Live option
checks passed after reload and disposable media were removed; no note was added.
Field-selection and storage-error handling add 52 differential cases and nine
standalone regressions, covering exact errors, note fields and partial media writes.
Live field-selection checks passed after reload; no note was added and disposable
media were removed. Raw media values and malformed attachments add 79 differential
cases and six standalone regressions, covering input coercion, filename error order
and partial writes. Their live checks await reload confirmation.
The raw HTTP-body batch adds 90 differential cases and 11 standalone regressions:
empty-body discovery, exact JSON/UTF-8 errors and origin rejection now match the
tested upstream boundaries. After reload, all 26 read-only live checks passed,
without fixtures, permission prompts or setting changes. Full CORS/header,
preflight, fragmented-request and concurrency equivalence remain unverified.
The original model/scheduler pass added 38 differential cases and five
standalone regressions, including a native field-rename rendering check. Ruff passes
for the changed Python files. After reload, read-only live checks passed for the
corrected errors, missing IDs, mixed card lists, 1002-note batching and nested deck
names. See the [results](shim_differential_results.md) for the scope and remaining limits.

Execution evidence is a lower bound, not semantic coverage. Tests may mock adapters;
a handler can return false or an embedded error; assertions may cover only part of
the result. Direct adapter tests and earlier manual tests are not counted here.
An optional argument having appeared once does not cover its values or interactions.

Reproduce with the project's test environment:

```sh
python -m pytest -q -p tools.shim_coverage --shim-coverage=/tmp/tsunagi-shim-coverage.json
python -m tools.shim_coverage /tmp/tsunagi-shim-coverage.json docs/shim_coverage_matrix.md
```

The JSON includes individual test IDs, test outcomes, parameter names/types and call
outcomes. It excludes request values. Use a single pytest process. The plugin is
inactive unless explicitly enabled and restores its wrapper when pytest finishes.

## Remaining handlers without observed calls

After adding reflection and deck-name tests, these 21 handlers still need tests
through the compatibility endpoint:

| Group | Actions | Required evidence |
| --- | --- | --- |
| Add/edit dialogs | `guiAddCards`, `guiAddNoteSetData`, `guiEditNote` | Correct dialog, deck/model selection, field/tag replacement and append, media, saving, canceling, focus and dialog reuse. |
| Reviewer | `guiAnswerCard`, `guiCurrentCard`, `guiDeckReview`, `guiPlayAudio`, `guiReviewActive`, `guiShowAnswer`, `guiShowQuestion`, `guiStartCardTimer`, `guiUndo` | Inactive/question/answer states, scheduling and undo effects, timer/audio behavior, identical result/error shapes. |
| Navigation/selection | `guiDeckBrowser`, `guiDeckOverview`, `guiSelectedNotes` | Screen transitions, selection ordering, empty selection, invalid deck and note IDs. |
| Collection/UI lifecycle | `getProfiles`, `loadProfile`, `sync`, `guiCheckDatabase`, `guiImportFile`, `guiExitAnki` | Completion timing, busy/unavailable collection, user cancellation, profile switch/reload, sync authentication/full-sync/error branches, package import and shutdown. |

`guiBrowse`, `guiSelectCard`, and `guiSelectNote` have calls in the test suite but
still need live UI equivalence checks. Mocked forwarding does not prove selection
or focus. Existing manual results should be attached as evidence for individual
cases, not used to mark an entire GUI family complete.

## Known differences to close

These are compatibility debt under the full-shim target, including differences
previously described as intentional improvements. Resolve them only in the
compatibility layer so native methods and routes keep their documented behavior.
Reuse native operations without adding parity switches to their contracts. Confirm
upstream behavior on the same Anki version before reproducing an obsolete quirk.

| Priority | Surface | Difference / missing comparison |
| --- | --- | --- |
| 1 | RPC argument values and errors | Missing/extra names, outer HTTP schema, malformed-child aborts, nested parameter containers, raw child versions and permission binding have comparisons. Permission acceptance/ignore persistence, empty/non-string nested origins, duplicate writes and repeated requests now have simulated-dialog comparisons. Mapping errors omit the installation-specific module prefix, with the remaining text compared exactly. Broader action-value/Pydantic coercion, generic internal errors and real dialog interaction remain to compare. |
| 1 | `guiEditNote` | Browser navigation currently substitutes for upstream's standalone editor. This is a user-visible gap, not an acceptable UI equivalence claim. |
| 1 | `answerCards`, `addNotes`, `insertReviews` | Answer prefixes and tested backend/live GUI undo now match. Review duplicate/malformed-row failures are atomic in both implementations; the earlier partial-write claim was incorrect. Extend undo/grouping, malformed value types and rollback sequences. Review SQL-expression values remain outside the scalar-only fallback and are still a contract gap. |
| 1 | Media and note probes | Probe media writes now match tested valid/empty/duplicate cases, and null deleteExisting behavior is fixed. Comparisons also cover local URL downloads, base64, scalar/list media, missing fields, skip hashes, collisions and appended decode errors. The default local-path gate remains different (D11); extend failed-download and nested-option coverage. Native media tests alone do not cover shim mapping. |
| 2 | Deck lookup edge cases | `getDeckStats`, `cardReviews`, `getLatestReviewID` now create missing decks through a shim-only resolver; native reads still create nothing. Comparisons cover nested, blank/padded names, null errors and string iteration. `getDecks` matches the missing-card fallback. Extend invalid-name sequences/partial effects and compare `deckNameFromId` missing-ID fallback. |
| 2 | Scheduling edge cases | Empty-history errors and suspension list iteration now match, with comparisons for duplicate/missing IDs, mixed new/review/learning queues, buried/suspended cards and negative learning intervals. Extend filtered-deck, FSRS, day-learning/relearning, boundary and legacy-state coverage. |
| 2 | Model mutation | Existing-template cache-only edits, empty template-update saves, field-rename rendering, unmatched replacement saves and creation errors now match tested cases. Extend modification-time, card generation/deletion, field/template ordinal, creation/cloze edge cases and model-conversion comparisons. |
| 2 | GUI transitions and collection lifecycle | `guiDeckReview` avoids upstream's overview transition; `sync` omits an obsolete `mw.onSync()` call. Compare observable behavior on supported Anki versions, including focus, completion timing and errors. |
| 3 | Transport and browser permission | Raw-body comparisons now cover status, decoded JSON/exact errors, empty 403 bytes and JSON Content-Type for empty/malformed/valid bodies across absent, allowed, denied and empty origins. Extend all CORS/transport headers, preflights, fragmented requests, UTF-8 byte lengths, permission persistence and concurrent requests; the reference wrapper runs without a socket. |

Priorities order the work; none removes an action from scope. Exact errors and
side effects belong to the compatibility contract even when the behavior is rare.

## Required cases for every action

Each action needs a case ledger with the request, upstream revision, Anki version,
initial fixture state, expected response, expected side effects and test evidence:

1. Minimal valid request; each optional parameter omitted and explicitly supplied;
   relevant combinations of flags and nested note/media options.
2. Empty, missing, duplicate, unknown and out-of-order IDs; exact output ordering,
   map keys, null/false/empty distinctions and omitted versus present response keys.
3. Malformed values and extra/missing arguments; exact RPC envelope and error text;
   failure before, during and after a multi-item mutation.
4. Persisted state, media files, modification times, undo entries and UI state after
   success and failure. No response-only assertion can establish these effects.
5. Large inputs crossing SQL batch boundaries (including 999/1000), repeated IDs
   across boundaries, and Unicode names, tags, HTML and filenames.

For `findCards`/`findNotes`, compare real Anki search expressions: quoted deck/tag/field
names, escaped characters, parentheses, AND/OR/negation, regex, property/date/review
filters and invalid queries. Check note-versus-card result semantics and ordering.
The six native query families already exercised use a separate filter grammar.

The runtime inventory also found no explicitly supplied `back` argument for
`findAndReplaceInModels` and no `path`/`url` arguments for shim `storeMediaFile`.
Those are concrete missing cases even though both handlers are exercised elsewhere.

## Reference comparison and completion gate

The first differential runner now executes the pinned upstream implementation
against isolated, equivalent collections on the **same Anki version**. See the
[comparison results](shim_differential_results.md): 127 cases cover 45 action names;
126 pass and one records the default local-path gate mismatch. The original ten
differences and the subsequent null-flag/probe-media differences are fixed. Extend this runner
to the remaining cases; these results do not establish complete action coverage.
Run each mutating case on a fresh copy for each implementation. Compare responses
and state changes; normalize only nondeterministic IDs/times with documented rules.
Do not normalize away ordering, missing keys, false/null, errors or side effects.
Do not run either mutating reference against the user's normal collection.

GUI cases need a real Qt window and equivalent disposable profiles. A fake `mw` is
useful for branch tests but cannot establish the standalone-editor experience,
reviewer behavior, import dialogs, audio, shutdown or profile-switch timing.

Completion requires all 122 actions to have reviewed cases and upstream comparison
evidence, all known user-visible differences resolved (or explicitly accepted by
the user), and the collection/GUI cases verified on supported Anki versions. Keep
the pinned reference and history inventory in sync as upstream changes. The current
suite and matrix do **not** yet meet that gate.

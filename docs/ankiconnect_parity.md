# AnkiConnect parity

Tsunagi's compatibility shim at `POST /` implements AnkiConnect's protocol.
This file tracks every action AnkiConnect exposes and where Tsunagi stands.

**Source of truth:** `git.sr.ht/~foosoft/anki-connect` at commit `de6e6e1b`
(2025-12-03) — the *sourcehut* repository. The `FooSoft/anki-connect` mirror on
GitHub is stale (2023) and disagrees with it. Counts here come from the
`@util.api()` decorators in `plugin/__init__.py`, not from the README.

| | |
| --- | --- |
| Actions upstream | **122** |
| Implemented | **122** |
| Planned (M6) | **0** |
| Out of scope | **0** |

`GET /actions` returns the live list. `tests/test_parity_doc.py` checks this
file against the registry in both directions, so an action that is registered
but undocumented — or documented but unregistered — fails CI.

The 2026-09-07 [history-based audit](parity_history_audit.md) found and fixed
optional-argument and deprecated-alias mismatches despite the 122/122 count.
Action inventory is not proof of complete behavioral parity.

The [coverage plan](shim_behavioral_coverage.md) and
[execution matrix](shim_coverage_matrix.md) record the historical audit work.
The broad upstream comparisons and their shared fixtures are archived in Git at
`eea649e` (the `tests/test_upstream_*.py` files and `tests/upstream_support.py`).
References to those tests in audit documents refer to that revision. Focused
Tsunagi regressions and action-inventory checks remain in the maintained suite.
Windows manual checks confirmed Browser/Add Cards restoration and field focus.
When another app is active, Windows can leave them behind it and flash the
taskbar. The import picker came forward, and cancellation left no lingering
topmost behavior. These observations apply to the tested Windows setup;
offscreen Qt results alone do not establish foreground behavior.

## Two discrepancies in upstream's own documentation

**Six actions are undocumented.** `canAddNote`, `canAddNoteWithErrorDetail`,
`deckNameFromId`, `modelNameFromId`, `guiReviewActive` and `guiSelectNote` are
decorated with `@util.api()` and answer over the wire, but appear under no
README heading. They are marked below.

**`removeEmptyNotes` does not do what its name says.** The README promises
"Removes all the empty notes for the current user", but the implementation
removes note *types* that no note uses (`models.use_count(m) == 0 →
models.remove(...)`). The most likely reading is that "empty note" is loose
wording for "empty note type" rather than a bug, so Tsunagi reproduces the
implemented behaviour. It destroys no content either way: `use_count == 0`
means there are no notes to lose.

## Status meanings

- **implemented** — answers over `POST /`, with parity tests for supported
  behavior. This does not certify every optional argument, error string,
  runtime version, or GUI state; manually verified actions are marked below.
- **M6** — planned for the next milestone.
- **out-of-scope** — deliberately not implemented; the reason is in the row.

Known action-specific differences are listed below. The shim preserves raw
argument and error behavior where covered by the compatibility regressions;
native API validation has its own contract. Local-file access is disabled by
default, and raw review inserts accept scalar values rather than SQL expressions.
Action inventory and historical test results do not promise every untested input
or GUI state matches upstream.

### Card Actions

| Action | Status | Notes |
| --- | --- | --- |
| `answerCards` | implemented | Uses the native scheduler answer method. Missing keys and invalid ease preserve preceding answers; earlier invalid ease takes precedence over later missing keys. Responses, review rows and backend undo/redo are compared. |
| `areDue` | implemented | Batched native reader with strict history enabled by the shim. Matches upstream's error for non-new/missing cards without review history. |
| `areSuspended` | implemented |  |
| `cardsInfo` | implemented |  |
| `cardsModTime` | implemented |  |
| `cardsToNotes` | implemented |  |
| `findCards` | implemented |  |
| `forgetCards` | implemented |  |
| `getEaseFactors` | implemented |  |
| `getIntervals` | implemented | Batched. Missing last intervals raise the upstream error; complete=true still returns empty histories. Native fallback defaults remain unchanged. |
| `relearnCards` | implemented | Uses a raw UPDATE, wrapped in a CollectionOp. |
| `setDueDate` | implemented | Uses the native scheduler mutation; exposes Anki's unprefixed invalid-input message. |
| `setEaseFactors` | implemented | Uses the native factor writer. Short arrays keep earlier writes, skip missing cards and fail at the first present card without a factor. |
| `setSpecificValueOfCard` | implemented | Quirk-for-quirk, including the bare `false` for every input problem, `[true]` on success, `[[false, "err"]]` on failure, and the `warning_check is False` guard that a JSON `null` slips past. Native: POST /v1/cards:set-values. |
| `suspend` | implemented | Supports suspend=false and reproduces upstream's list-removal iteration, including repeated-state return values and skipped missing-ID validation. State reads stay batched; writes use native methods. |
| `suspended` | implemented |  |
| `unsuspend` | implemented | Returns null, matching canonical. |

### Deck Actions

| Action | Status | Notes |
| --- | --- | --- |
| `changeDeck` | implemented | Creates the target deck, matching canonical; POST /v1/cards:change-deck refuses instead. |
| `cloneDeckConfigId` | implemented |  |
| `createDeck` | implemented |  |
| `deckNameFromId` | implemented | Not in the upstream README. |
| `deckNames` | implemented |  |
| `deckNamesAndIds` | implemented |  |
| `deleteDecks` | implemented |  |
| `getDeckConfig` | implemented |  |
| `getDeckStats` | implemented | The shim creates missing decks before reading stats, including normalized blank/padded and nested names. Native stats reads create nothing. |
| `getDecks` | implemented | Preserves order/duplicates and groups missing card IDs through Anki's default-deck fallback, matching upstream. |
| `removeDeckConfigId` | implemented |  |
| `saveDeckConfig` | implemented |  |
| `setDeckConfigId` | implemented |  |

### Model Actions

| Action | Status | Notes |
| --- | --- | --- |
| `createModel` | implemented | Requires both template sides and preserves Anki validation errors. Standard/cloze creation and failure side effects have differential coverage. |
| `findAndReplaceInModels` | implemented | Calls the native replacement method with explicit saving of unmatched targets, matching upstream's sync metadata side effects. Native default remains save-matches-only. |
| `findModelsById` | implemented |  |
| `findModelsByName` | implemented |  |
| `modelFieldAdd` | implemented |  |
| `modelFieldDescriptions` | implemented |  |
| `modelFieldFonts` | implemented |  |
| `modelFieldNames` | implemented |  |
| `modelFieldRemove` | implemented |  |
| `modelFieldRename` | implemented | Uses the native field mutation, fixed to preserve rewritten template references and rendering. |
| `modelFieldReposition` | implemented |  |
| `modelFieldSetDescription` | implemented |  |
| `modelFieldSetFont` | implemented |  |
| `modelFieldSetFontSize` | implemented |  |
| `modelFieldsOnTemplates` | implemented |  |
| `modelNameFromId` | implemented | Not in the upstream README. |
| `modelNames` | implemented |  |
| `modelNamesAndIds` | implemented |  |
| `modelStyling` | implemented |  |
| `modelTemplateAdd` | implemented | Existing-template updates match canonical's unsaved model-cache edit; new templates use the native creation method. Cache and persisted state are compared separately. |
| `modelTemplateRemove` | implemented |  |
| `modelTemplateRename` | implemented |  |
| `modelTemplateReposition` | implemented |  |
| `modelTemplates` | implemented |  |
| `updateModelStyling` | implemented |  |
| `updateModelTemplates` | implemented | Empty/unknown template updates still save the model, matching canonical's sync metadata side effect. |

### Note Actions

| Action | Status | Notes |
| --- | --- | --- |
| `addNote` | implemented |  |
| `addNotes` | implemented |  |
| `addTags` | implemented | Supports upstream's undocumented `add=false` argument to remove tags. |
| `canAddNote` | implemented | Not in the upstream README. |
| `canAddNoteWithErrorDetail` | implemented | Not in the upstream README. |
| `canAddNotes` | implemented | Matches upstream media writes during probes, including rejected duplicate/empty notes; no note is inserted. |
| `canAddNotesWithErrorDetail` | implemented | Same media side effects as upstream; errors remain per-note. |
| `clearUnusedTags` | implemented |  |
| `deleteNotes` | implemented |  |
| `findNotes` | implemented |  |
| `getNoteTags` | implemented |  |
| `getTags` | implemented |  |
| `notesInfo` | implemented |  |
| `notesModTime` | implemented |  |
| `removeEmptyNotes` | implemented | Removes note TYPES nothing uses, despite the name - see the note below. |
| `removeTags` | implemented |  |
| `replaceTags` | implemented | Exact-tag match, so 'verb' leaves 'verb::transitive' alone. |
| `replaceTagsInAllNotes` | implemented | Exact-tag match, as above. |
| `updateNote` | implemented |  |
| `updateNoteFields` | implemented |  |
| `updateNoteModel` | implemented |  |
| `updateNoteTags` | implemented |  |

### Media Actions

| Action | Status | Notes |
| --- | --- | --- |
| `deleteMediaFile` | implemented |  |
| `getMediaDirPath` | implemented |  |
| `getMediaFilesNames` | implemented |  |
| `retrieveMediaFile` | implemented |  |
| `storeMediaFile` | implemented |  |

### Miscellaneous Actions

| Action | Status | Notes |
| --- | --- | --- |
| `apiReflect` | implemented | Exact scope omission, validation errors, requested order and duplicate-action behavior covered by `test_shim_coverage_gaps.py`. |
| `exportPackage` | implemented | Uses Anki's current export API, feature-detected - the signature changed between 23.10 and now. |
| `getActiveProfile` | implemented | Manual verification only (needs a live main window). |
| `getProfiles` | implemented | Manual verification only (needs a live main window). |
| `importPackage` | implemented | Package import follows saved Anki import choices. The native API also accepts explicit choices. |
| `loadProfile` | implemented | Manual verification only. The collection is unavailable mid-switch; requests get a 503. |
| `multi` | implemented |  |
| `reloadCollection` | implemented | Collection reload dispatch is covered by the retained tests. |
| `requestPermission` | implemented |  |
| `sync` | implemented | Manual verification only. Deviation: canonical then calls `mw.onSync()`, which no longer exists. |
| `version` | implemented |  |

### Graphical Actions

| Action | Status | Notes |
| --- | --- | --- |
| `guiAddCards` | implemented | Manual verification only (needs a live main window). |
| `guiAddNoteSetData` | implemented | Manual verification only (needs a live main window). |
| `guiAnswerCard` | implemented | Manual verification only (needs a live main window). |
| `guiBrowse` | implemented |  |
| `guiCheckDatabase` | implemented | Native equivalent is `POST /v1/collection:check-database`. |
| `guiCurrentCard` | implemented | Native `GET /v1/gui/current-card` reports null when no review is active; this raises, as canonical does. |
| `guiDeckBrowser` | implemented | Manual verification only (needs a live main window). |
| `guiDeckOverview` | implemented | Manual verification only (needs a live main window). |
| `guiDeckReview` | implemented | Goes straight to the reviewer. Canonical routes through the overview first, which races the reviewer and can leave you on the deck page. |
| `guiEditNote` | implemented | Opens a reusable standalone Anki editor with save-before-switch/close, history, Browser search and card preview. HTTP routing and Qt lifecycle are tested; a disposable Anki 26.08.1 app smoke check also passed editor open, preview and save/close. Complete visual equivalence remains unverified. The native edit-note route still opens the Browser. |
| `guiExitAnki` | implemented | Manual verification only (needs a live main window). |
| `guiImportFile` | implemented | Waits for Anki's initial GUI call, not confirmed import completion. Dispatch has an operation timeout; accepted dialog interaction does not. Client HTTP timeouts still apply. |
| `guiPlayAudio` | implemented | Manual verification only (needs a live main window). |
| `guiReviewActive` | implemented | Manual verification only (needs a live main window). |
| `guiSelectCard` | implemented | Manual verification only (needs a live main window). |
| `guiSelectNote` | implemented | Deprecated alias: accepts `note` containing a **card ID**; `guiSelectCard` accepts `card`. Fixed by the 2026-09-07 history audit. |
| `guiSelectedNotes` | implemented | Manual verification only (needs a live main window). |
| `guiShowAnswer` | implemented | Manual verification only (needs a live main window). |
| `guiShowQuestion` | implemented | Manual verification only (needs a live main window). |
| `guiStartCardTimer` | implemented | Manual verification only (needs a live main window). |
| `guiUndo` | implemented | Manual verification only (needs a live main window). |

### Statistic Actions

| Action | Status | Notes |
| --- | --- | --- |
| `cardReviews` | implemented | Arrays in revlog column order. The shim creates a missing deck and returns no rows. Both `deck` and `startID` are required. The cutoff is bound unchanged through Anki’s database API; strings are values, never SQL expressions. Native reads create nothing. |
| `getCollectionStatsHTML` | implemented | Anki's own stats report. |
| `getLatestReviewID` | implemented | The shim creates a missing deck and returns 0; native reads create nothing. |
| `getNumCardsReviewedByDay` | implemented | Grouped by local study day, using the scheduler's rollover hour. |
| `getNumCardsReviewedToday` | implemented | Counted from the scheduler's day cutoff. |
| `getReviewsOfCards` | implemented | Map of card id to reviews; every requested card gets an entry. |
| `insertReviews` | implemented | Ordinary integer rows use the native writer; a scalar-only compatibility path preserves tested SQLite coercion/errors. Duplicate/malformed-row failures are atomic upstream too. SQL-expression values remain outside the scalar contract. Native: POST /v1/reviews. |

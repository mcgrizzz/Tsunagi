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
| Implemented | **119** |
| Planned (M6) | **0** |
| Out of scope | **3** |

`GET /actions` returns the live list. `tests/test_parity_doc.py` checks this
file against the registry in both directions, so an action that is registered
but undocumented — or documented but unregistered — fails CI.

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

- **implemented** — answers over `POST /`, with a wire-shape test pinning its
  exact JSON, including error strings.
- **M6** — planned for the next milestone.
- **out-of-scope** — deliberately not implemented; the reason is in the row.

Where Tsunagi deviates from canonical behaviour, the row says so. Every
deviation is one of two kinds: a read that refuses to mutate the collection, or
a canonical bug whose faithful reproduction would only destroy the caller's
work.

### Card Actions

| Action | Status | Notes |
| --- | --- | --- |
| `answerCards` | out-of-scope | Drives the reviewer. Use POST /v1/cards:set-due-date or :forget to reschedule. |
| `areDue` | implemented |  |
| `areSuspended` | implemented |  |
| `cardsInfo` | implemented |  |
| `cardsModTime` | implemented |  |
| `cardsToNotes` | implemented |  |
| `findCards` | implemented |  |
| `forgetCards` | implemented |  |
| `getEaseFactors` | implemented |  |
| `getIntervals` | implemented |  |
| `relearnCards` | implemented | The one action with no Anki API; a raw UPDATE, wrapped in a CollectionOp. |
| `setDueDate` | implemented |  |
| `setEaseFactors` | implemented |  |
| `setSpecificValueOfCard` | out-of-scope | Raw column writes with no validation; canonical guards it behind a warning flag. |
| `suspend` | implemented | Returns false when every card is already in the target state. |
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
| `getDeckStats` | implemented | Deviation: unknown deck names are skipped, not created. |
| `getDecks` | implemented | Deviation: unknown card ids are dropped, not filed under Default. |
| `removeDeckConfigId` | implemented |  |
| `saveDeckConfig` | implemented |  |
| `setDeckConfigId` | implemented |  |

### Model Actions

| Action | Status | Notes |
| --- | --- | --- |
| `createModel` | implemented |  |
| `findAndReplaceInModels` | implemented | Deviation: saves only models that matched, where canonical re-saves all of them. |
| `findModelsById` | implemented |  |
| `findModelsByName` | implemented |  |
| `modelFieldAdd` | implemented |  |
| `modelFieldDescriptions` | implemented |  |
| `modelFieldFonts` | implemented |  |
| `modelFieldNames` | implemented |  |
| `modelFieldRemove` | implemented |  |
| `modelFieldRename` | implemented |  |
| `modelFieldReposition` | implemented |  |
| `modelFieldSetDescription` | implemented |  |
| `modelFieldSetFont` | implemented |  |
| `modelFieldSetFontSize` | implemented |  |
| `modelFieldsOnTemplates` | implemented |  |
| `modelNameFromId` | implemented | Not in the upstream README. |
| `modelNames` | implemented |  |
| `modelNamesAndIds` | implemented |  |
| `modelStyling` | implemented |  |
| `modelTemplateAdd` | implemented | Deviation: persists an update to an existing template, where canonical discards it. |
| `modelTemplateRemove` | implemented |  |
| `modelTemplateRename` | implemented |  |
| `modelTemplateReposition` | implemented |  |
| `modelTemplates` | implemented |  |
| `updateModelStyling` | implemented |  |
| `updateModelTemplates` | implemented |  |

### Note Actions

| Action | Status | Notes |
| --- | --- | --- |
| `addNote` | implemented |  |
| `addNotes` | implemented |  |
| `addTags` | implemented |  |
| `canAddNote` | implemented | Not in the upstream README. |
| `canAddNoteWithErrorDetail` | implemented | Not in the upstream README. |
| `canAddNotes` | implemented | Deviation: does not write media during a read-only probe. |
| `canAddNotesWithErrorDetail` | implemented | Deviation: does not write media during a read-only probe. |
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
| `apiReflect` | implemented |  |
| `exportPackage` | implemented | Uses Anki's current export API, feature-detected - the signature changed between 23.10 and now. |
| `getActiveProfile` | implemented | Manual verification only (needs a live main window). |
| `getProfiles` | implemented | Manual verification only (needs a live main window). |
| `importPackage` | implemented | M6 - profile and collection lifecycle. |
| `loadProfile` | implemented | Manual verification only. The collection is unavailable mid-switch; requests get a 503. |
| `multi` | implemented |  |
| `reloadCollection` | implemented | M6 - profile and collection lifecycle. |
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
| `guiEditNote` | implemented | Deviation: opens the Browser focused on the note. Canonical ships its own standalone editor dialog, which is its UX rather than its protocol. |
| `guiExitAnki` | implemented | Manual verification only (needs a live main window). |
| `guiImportFile` | implemented | Manual verification only (needs a live main window). |
| `guiPlayAudio` | implemented | Manual verification only (needs a live main window). |
| `guiReviewActive` | implemented | Manual verification only (needs a live main window). |
| `guiSelectCard` | implemented | Manual verification only (needs a live main window). |
| `guiSelectNote` | implemented | Compat-only: canonical's own deprecated alias for `guiSelectCard` (it selects a card despite the name). |
| `guiSelectedNotes` | implemented | Manual verification only (needs a live main window). |
| `guiShowAnswer` | implemented | Manual verification only (needs a live main window). |
| `guiShowQuestion` | implemented | Manual verification only (needs a live main window). |
| `guiStartCardTimer` | implemented | Manual verification only (needs a live main window). |
| `guiUndo` | implemented | Manual verification only (needs a live main window). |

### Statistic Actions

| Action | Status | Notes |
| --- | --- | --- |
| `cardReviews` | implemented | Arrays in revlog column order. Deviation: canonical resolves the deck with `decks.id()`, which creates a missing deck; we resolve by name and report nothing. |
| `getCollectionStatsHTML` | implemented | Anki's own stats report. |
| `getLatestReviewID` | implemented | Same by-name deck resolution as `cardReviews`; 0 when the deck does not exist. |
| `getNumCardsReviewedByDay` | implemented | Grouped by local study day, using the scheduler's rollover hour. |
| `getNumCardsReviewedToday` | implemented | Counted from the scheduler's day cutoff. |
| `getReviewsOfCards` | implemented | Map of card id to reviews; every requested card gets an entry. |
| `insertReviews` | out-of-scope | Writes revlog rows straight to the database, bypassing the scheduler. |

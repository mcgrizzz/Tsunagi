# AnkiConnect compatibility

Tsunagi answers AnkiConnect's protocol at `POST /`, so tools built for
AnkiConnect, such as Yomitan and asbplayer, should generally work without
changes beyond pointing them at Tsunagi's port (or importing AnkiConnect's
settings so Tsunagi takes over its port). The
[differences](#differences-you-might-notice) mostly concern less common
actions and settings. This page lists every AnkiConnect action and how
Tsunagi handles it.

| | |
| --- | --- |
| Actions upstream | **122** |
| Implemented | **122** |
| Planned (M6) | **0** |
| Out of scope | **0** |

## Differences you might notice

- **Permissions.** Each action needs a permission from the caller's role
  ([configuration](../config.md#roles)). Keyless requests from this computer
  get the Default role, which allows everything AnkiConnect does except one
  thing: **reading local files**. A media `path` (in `storeMediaFile`, or in
  the media of `addNote`/`addNotes`) needs the `local_files` permission, which
  only the Everything role has by default. AnkiConnect always allows it.
- A key is checked for each action, including inside `multi`. A refused action
  returns the usual `{"result": null, "error": "..."}` naming the app, its role
  and what's missing.
- **Every action but `requestPermission` needs a key** when keyless requests
  get No access, `version` included, as in AnkiConnect. `version` and
  `apiReflect` answer any app's key, whatever the app is allowed to do, so an
  answer doesn't show access; `GET /v1/health` names the app and its role.
- **`requireApikey`** in the `requestPermission` answer is `true` when the
  caller must send a key: requests without one, from where the caller is, get
  No access.
- **Anki's own pages.** Card templates and other add-ons' pages inside Anki
  are refused unless you turn on **Allow card templates and add-on pages**.
  AnkiConnect lets any card template use it.
- **Raw review inserts** accept plain values, not SQL expressions.

Arguments and error messages match AnkiConnect wherever the compatibility
tests cover them. Inputs or window states they don't cover may still differ.

## How this list is checked

- **Source:** AnkiConnect's *sourcehut* repository
  (`git.sr.ht/~foosoft/anki-connect`) at commit `de6e6e1b` (2025-12-03). The
  `FooSoft/anki-connect` mirror on GitHub is stale (2023) and disagrees with
  it. Counts come from the `@util.api()` decorators in `plugin/__init__.py`,
  not the README.
- `GET /actions` returns the live list, and `tests/test_parity_doc.py` fails CI
  if an action is registered but not listed here, or listed but not
  registered.
- A full count isn't proof of identical behaviour: a
  [history-based audit](archive/parity_history_audit.md) (2026-09-07) still
  found and fixed optional-argument and deprecated-alias mismatches.
- Older audit work: the [coverage plan](archive/shim_behavioral_coverage.md)
  and [execution matrix](archive/shim_coverage_matrix.md). The broad upstream
  comparison tests are archived in Git at `3c8e2dd`
  (`tests/test_upstream_*.py`, `tests/upstream_support.py`).

## Where AnkiConnect is broken or mislabeled

Things AnkiConnect gets wrong, or documents differently from what it does,
read from its source at the commit above. Tsunagi fixes the ones a client
can't be relying on, and keeps the rest so existing clients behave the same.

**Fixed in Tsunagi:**

- **`guiExitAnki` doesn't close Anki.** AnkiConnect answers success, then
  starts a timer it keeps no reference to (`plugin/__init__.py:2121`); inside
  Anki that timer never fires, so Anki stays open (seen on Anki 26.09.2,
  2026-10-03). Tsunagi closes Anki a second after answering.
- **Edits wipe Anki's undo history.** `updateNoteFields`, `updateNote`,
  `updateNoteModel`, `replaceTags`, `replaceTagsInAllNotes`, `setEaseFactors`,
  `setSpecificValueOfCard`, `relearnCards` and `changeDeck` write without an
  undo step, or with raw SQL, and either one clears everything you could undo
  in Anki. In Tsunagi each of them is one step in **Edit → Undo**.
- **Card IDs go straight into SQL.** `relearnCards`, `cardsToNotes` and
  `changeDeck` paste the IDs they're given into a query, so a crafted "ID"
  can relearn every card or read every note's text. Tsunagi refuses anything
  that isn't a number.
- **`getMediaFilesNames` looks outside the media folder.** A pattern such as
  `../*` or an absolute path lists files elsewhere on the computer. Tsunagi
  only matches names in the media folder.
- **`deckNameFromId` answers `"Default"` for a deck that doesn't exist.** Its
  "deck was not found" error can never happen, because Anki's lookup falls
  back to the Default deck. Tsunagi returns the error.
- **`guiDeckReview` can leave you on the deck page.** It opens the deck
  overview and then the reviewer, and the overview can repaint over the
  reviewer. Tsunagi goes straight to the reviewer.
- **`sync` syncs twice.** It syncs the collection, then starts a second sync
  through Anki's sync button. Tsunagi runs one sync and waits for it.
- **`insertReviews` runs values as SQL.** Each value is pasted into the
  insert, so a value can be any SQL expression. Tsunagi accepts plain values
  only.

**Kept as AnkiConnect does it:**

- **`removeEmptyNotes` removes note types, not notes.** The README promises
  "Removes all the empty notes for the current user", but the code removes
  note *types* that no note uses. No notes are lost, but each removed note
  type's fields, templates and styling are.
- **Return values that differ from the README:**
  - `unsuspend` returns `null`, not `true`/`false`.
  - `suspend` can return `true` when every card was already suspended: it
    removes items from the list it's looping over, so it skips some.
  - `setEaseFactors` returns a list, not `true`/`false`.
  - `setSpecificValueOfCard` returns at most a one-item list; the README's
    example (`[true, true]`) can't happen.
  - `requestPermission` answers `requireApikey`, not the README's
    `requireApiKey`.
  - `getDeckStats` names each deck by its last part (`JLPT N5`), not its full
    name (`Japanese::JLPT N5`).
  - `reloadCollection` does nothing on supported Anki versions.
- **Reads that change things:**
  - `getDeckStats`, `cardReviews` and `getLatestReviewID` create a deck they're
    asked about if it doesn't exist.
  - `canAddNote`, `canAddNotes` and their `WithErrorDetail` forms store the
    note's media files before checking whether the note can be added.
  - `modelTemplateAdd` with an existing template's name changes the cached
    template without saving it.
- **Other quirks:**
  - `getDecks` lists unknown card IDs under `Default`.
  - `notesInfo` repeats a note's card IDs once for each batch of 999 note IDs
    it was found in.
  - `areDue` and `getIntervals` fail with "list index out of range" for a
    card with no review history or an ID that doesn't exist.
  - `guiSelectNote` takes a card ID, despite its name.
  - `addTags` takes an undocumented `add` argument.
- **Six actions are undocumented:** `canAddNote`, `canAddNoteWithErrorDetail`,
  `deckNameFromId`, `modelNameFromId`, `guiReviewActive` and `guiSelectNote`
  answer over the wire but appear under no README heading. They are marked
  below.

## Status

Every action is **implemented**: it answers over `POST /`, with tests for
supported behaviour. Actions checked by hand only are marked.

### Card Actions

| Action | Status | Notes |
| --- | --- | --- |
| `answerCards` | implemented | Uses the Tsunagi API's scheduler answer method. Missing keys and invalid ease preserve preceding answers; earlier invalid ease takes precedence over later missing keys. Responses, review rows and backend undo/redo are compared. |
| `areDue` | implemented | Batched Tsunagi API reader, with strict history enabled by the AnkiConnect Shim. Matches upstream's error for non-new/missing cards without review history. |
| `areSuspended` | implemented |  |
| `cardsInfo` | implemented |  |
| `cardsModTime` | implemented |  |
| `cardsToNotes` | implemented |  |
| `findCards` | implemented |  |
| `forgetCards` | implemented |  |
| `getEaseFactors` | implemented |  |
| `getIntervals` | implemented | Batched. Missing last intervals raise the upstream error; complete=true still returns empty histories. The Tsunagi API's fallback defaults remain unchanged. |
| `relearnCards` | implemented | Sets the same type and queue as upstream's raw UPDATE, through Anki's card update. Unlike upstream, it can be undone: a raw UPDATE wipes Anki's whole undo history. |
| `setDueDate` | implemented | Uses the Tsunagi API's scheduler mutation; exposes Anki's unprefixed invalid-input message. |
| `setEaseFactors` | implemented | Uses the Tsunagi API's factor writer. Short arrays keep earlier writes, skip missing cards and fail at the first present card without a factor. Unlike upstream, the writes can be undone, as one step: upstream skips undo entries, which wipes Anki's whole undo history. |
| `setSpecificValueOfCard` | implemented | Quirk-for-quirk, including the bare `false` for every input problem, `[true]` on success, `[[false, "err"]]` on failure, and the `warning_check is False` guard that a JSON `null` slips past. Unlike upstream, it can be undone: upstream skips the undo entry, which wipes Anki's whole undo history. Tsunagi API: POST /v1/cards:set-values. |
| `suspend` | implemented | Supports suspend=false and reproduces upstream's list-removal iteration, including repeated-state return values and skipped missing-ID validation. State reads stay batched; writes use the Tsunagi API's methods. |
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
| `getDeckStats` | implemented | The AnkiConnect Shim creates missing decks before reading stats, including normalized blank/padded and nested names. Tsunagi API stats reads create nothing. |
| `getDecks` | implemented | Preserves order/duplicates and groups missing card IDs through Anki's default-deck fallback, matching upstream. |
| `removeDeckConfigId` | implemented |  |
| `saveDeckConfig` | implemented |  |
| `setDeckConfigId` | implemented |  |

### Model Actions

| Action | Status | Notes |
| --- | --- | --- |
| `createModel` | implemented | Requires both template sides and preserves Anki validation errors. Standard/cloze creation and failure side effects have differential coverage. |
| `findAndReplaceInModels` | implemented | Calls the Tsunagi API's replacement method with explicit saving of unmatched targets, matching upstream's sync metadata side effects. The Tsunagi API's default remains save-matches-only. |
| `findModelsById` | implemented |  |
| `findModelsByName` | implemented |  |
| `modelFieldAdd` | implemented |  |
| `modelFieldDescriptions` | implemented |  |
| `modelFieldFonts` | implemented |  |
| `modelFieldNames` | implemented |  |
| `modelFieldRemove` | implemented |  |
| `modelFieldRename` | implemented | Uses the Tsunagi API's field mutation, fixed to preserve rewritten template references and rendering. |
| `modelFieldReposition` | implemented |  |
| `modelFieldSetDescription` | implemented |  |
| `modelFieldSetFont` | implemented |  |
| `modelFieldSetFontSize` | implemented |  |
| `modelFieldsOnTemplates` | implemented |  |
| `modelNameFromId` | implemented | Not in the upstream README. |
| `modelNames` | implemented |  |
| `modelNamesAndIds` | implemented |  |
| `modelStyling` | implemented |  |
| `modelTemplateAdd` | implemented | Existing-template updates match canonical's unsaved model-cache edit; new templates use the Tsunagi API's creation method. Cache and persisted state are compared separately. |
| `modelTemplateRemove` | implemented |  |
| `modelTemplateRename` | implemented |  |
| `modelTemplateReposition` | implemented |  |
| `modelTemplates` | implemented |  |
| `updateModelStyling` | implemented |  |
| `updateModelTemplates` | implemented | Empty/unknown template updates still save the model, matching canonical's sync metadata side effect. |

### Note Actions

| Action | Status | Notes |
| --- | --- | --- |
| `addNote` | implemented | Deviation: media entries with `path` need the `local_files` permission (see `storeMediaFile`). |
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
| `replaceTags` | implemented | Exact-tag match, so 'verb' leaves 'verb::transitive' alone. Unlike upstream, the writes can be undone, as one step: upstream skips undo entries, which wipes Anki's whole undo history. |
| `replaceTagsInAllNotes` | implemented | Exact-tag match and one undo step, as above. |
| `updateNote` | implemented | Field updates can be undone, as for `updateNoteFields`. |
| `updateNoteFields` | implemented | Unlike upstream, it can be undone: upstream skips the undo entry, which wipes Anki's whole undo history. |
| `updateNoteModel` | implemented | Unlike upstream, it can be undone: upstream skips the undo entry, which wipes Anki's whole undo history. |
| `updateNoteTags` | implemented |  |

Plain-note batches sent to `canAddNotes` or `canAddNotesWithErrorDetail` share
note-type and deck lookups within bounded groups of 64 candidates. Every
candidate still gets its own validation and result; no lookup cache survives
that operation. Requests containing media keep the individual validation path
and its existing media side effects.

### Media Actions

| Action | Status | Notes |
| --- | --- | --- |
| `deleteMediaFile` | implemented |  |
| `getMediaDirPath` | implemented |  |
| `getMediaFilesNames` | implemented |  |
| `retrieveMediaFile` | implemented |  |
| `storeMediaFile` | implemented | Deviation: `path` (a file on this computer) needs the `local_files` permission, which only the Everything role has by default. |

### Miscellaneous Actions

| Action | Status | Notes |
| --- | --- | --- |
| `apiReflect` | implemented | Exact scope omission, validation errors, requested order and duplicate-action behavior covered by `test_shim_coverage_gaps.py`. |
| `exportPackage` | implemented | Preserves AnkiConnect's legacy package format, media inclusion and `includeSched` behavior. Bypasses deprecated wrappers on newer Anki; retains the original exporter on older versions. |
| `getActiveProfile` | implemented | Manual verification only (needs a live main window). |
| `getProfiles` | implemented | Manual verification only (needs a live main window). |
| `importPackage` | implemented | Preserves AnkiConnect's import behavior, including scheduling. On newer Anki, calls the backend directly with the wrapper's fixed options. Tsunagi API imports separately follow saved Anki choices and accept explicit overrides. |
| `loadProfile` | implemented | Manual verification only. The collection is unavailable mid-switch; requests get a 503. |
| `multi` | implemented |  |
| `reloadCollection` | implemented | Returns `null` with an open collection. This is a no-op on supported Anki versions: it leaves caches and undo history intact. The Tsunagi API's reload endpoint is deprecated for the same reason. |
| `requestPermission` | implemented | Deviation: Anki's own pages (card templates, add-on pages) are denied without a dialog and cannot use either API unless `gates.anki_page_scripts` is on. |
| `sync` | implemented | Runs Anki's sync path (hooks, media, refresh) without its dialogs and waits for the end; `tests/test_sync.py` with stand-ins, live AnkiWeb by hand. Deviation: canonical then starts a second sync through Anki's sync button (`mw.onSync()`); a full sync required is an error instead of Anki's prompt. |
| `version` | implemented |  |

### Graphical Actions

| Action | Status | Notes |
| --- | --- | --- |
| `guiAddCards` | implemented | Uses the legacy Add editor. Returns an explicit unsupported-editor error if Anki’s experimental Add window is open, preserving that draft. |
| `guiAddNoteSetData` | implemented | Uses the legacy Add editor. Returns an explicit unsupported-editor error if Anki’s experimental Add window is open, preserving that draft. |
| `guiAnswerCard` | implemented | Manual verification only (needs a live main window). |
| `guiBrowse` | implemented |  |
| `guiCheckDatabase` | implemented | Tsunagi API equivalent: `POST /v1/collection:check-database`. |
| `guiCurrentCard` | implemented | The Tsunagi API's `GET /v1/gui/current-card` reports null when no review is active; this raises, as canonical does. |
| `guiDeckBrowser` | implemented | Manual verification only (needs a live main window). |
| `guiDeckOverview` | implemented | Manual verification only (needs a live main window). |
| `guiDeckReview` | implemented | Goes straight to the reviewer. Canonical routes through the overview first, which races the reviewer and can leave you on the deck page. |
| `guiEditNote` | implemented | Opens a reusable standalone Anki editor with save-before-switch/close, history, Browser search and card preview. HTTP routing and Qt lifecycle are tested; a disposable Anki 26.08.1 app smoke check also passed editor open, preview and save/close. Complete visual equivalence remains unverified. The Tsunagi API's edit-note route still opens the Browser. |
| `guiExitAnki` | implemented | Closes Anki, where upstream answers success and leaves it open ([above](#where-ankiconnect-is-broken-or-mislabeled)). Checked by hand (needs a live main window). |
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
| `cardReviews` | implemented | Arrays in revlog column order. The AnkiConnect Shim creates a missing deck and returns no rows. Both `deck` and `startID` are required. The cutoff is bound unchanged through Anki’s database API; strings are values, never SQL expressions. Tsunagi API reads create nothing. |
| `getCollectionStatsHTML` | implemented | Anki's own stats report. |
| `getLatestReviewID` | implemented | The AnkiConnect Shim creates a missing deck and returns 0; Tsunagi API reads create nothing. |
| `getNumCardsReviewedByDay` | implemented | Grouped by local study day, using the scheduler's rollover hour. |
| `getNumCardsReviewedToday` | implemented | Counted from the scheduler's day cutoff. |
| `getReviewsOfCards` | implemented | Map of card id to reviews; every requested card gets an entry. |
| `insertReviews` | implemented | Ordinary integer rows use the Tsunagi API's writer; a scalar-only compatibility path preserves tested SQLite coercion/errors. Duplicate/malformed-row failures are atomic upstream too. SQL-expression values remain outside the scalar contract. Tsunagi API: POST /v1/reviews. |

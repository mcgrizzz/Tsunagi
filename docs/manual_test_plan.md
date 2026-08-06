# Tsunagi — full manual test plan

Every surface a user can reach: 100 native routes, 122 AnkiConnect actions,
the settings dialog, the event stream, and the server lifecycle. Work through
it at your leisure; each item is a checkbox with a command and an expected
result. Automated tests already pin wire shapes and call counts — this plan
is for the things only a real Anki can prove: visible UI effects, undo,
timing on a real collection, and drop-in behaviour with real clients.

## 0. Setup and conventions

- **Use a throwaway profile** (File → Switch Profile → Add). Several suites
  create, mutate and DELETE decks/models/notes, and suite 13 imports/exports
  and switches profiles. Do the perf spot checks (suite 17) on your real
  collection afterwards — they are read-only.
- Install `dist/tsunagi-0.0.1.ankiaddon` (Tools → Add-ons → Install from
  file), **fully restart Anki**, and keep the debug console visible when a
  step says "console".
- Commands are for **PowerShell** using `curl.exe` (not the `curl` alias).
  Set up once:

  ```powershell
  $T = "http://127.0.0.1:7777"
  # after suite 2 sets a key:
  $H = @("-H", "X-Api-Key: test-key-123")
  ```

  While no key is set, omit `@H` from the commands (or leave `$H = @()`).
- "Envelope" = `{items, next_cursor, stats}` for lists, `{result, error}`
  for `POST /`.
- Known-cosmetic (expected, don't fail the run): deck browser may repaint
  only on window focus after some GUI actions; `gui:exit` with the Add Cards
  window open logs a traceback while quitting.

Sign-off grid — initial each suite as you finish:

| Suite | Result | Suite | Result |
|---|---|---|---|
| 1 Boot & lifecycle | | 10 Media | |
| 2 Auth & CORS | | 11 FSRS & jobs | |
| 3 Discovery | | 12 GUI routes | |
| 4 Decks & configs | | 13 Collection & profiles | |
| 5 Models | | 14 Event stream | |
| 6 Notes | | 15 Shim: protocol | |
| 7 Cards: reads | | 16 Shim: real clients | |
| 8 Cards: writes | | 17 Performance | |
| 9 Reviews & tags | | 18 Errors & busy | |

---

## 1. Boot, settings dialog, server lifecycle

- [ ] Fresh start: console shows no `[tsunagi]` errors; no vendored-module
  conflict warning (or if one appears, note which addon it names — that's
  the diagnostic doing its job, not a failure).
- [ ] `curl.exe -s $T/v1/health` → 200.
- [ ] Tools → **Tsunagi Settings…** opens the dialog (not the raw JSON
  editor). Every field populated; gates section lists the toggles.
- [ ] Change **port** to 7778, OK → tooltip confirms; old port dead, new
  port answers `/v1/health`. Change back.
- [ ] Uncheck **enabled**, OK → server stops (connection refused). Re-check,
  OK → server back. No Anki restart at any point.
- [ ] Restore Defaults button repopulates the form but writes nothing until
  OK.
- [ ] Tools → Add-ons → Tsunagi → Config opens the same dialog (fallback to
  the JSON editor only if the dialog errors).
- [ ] Switch profile away and back → server stops and restarts cleanly; no
  "thread did not stop" in the console; port rebinds.
- [ ] Debug console (Ctrl+Shift+;): `import tsunagi; tsunagi.reload_addon()`
  → reports modules purged + listening URL.

## 2. Auth & CORS

- [ ] With no key configured: bare request works.
- [ ] Set `api_key` to `test-key-123` in the dialog, OK.
- [ ] Bare request → **401**. With `X-Api-Key` → 200. With
  `-H "Authorization: Bearer test-key-123"` → 200. Wrong key → 401.
- [ ] `curl.exe -s "$T/v1/events?api_key=test-key-123&timeout=2"` → streams
  (query key accepted on events only); the same query param on
  `/v1/decks` → 401.
- [ ] CORS: from a browser page on an *unlisted* origin,
  `fetch("http://127.0.0.1:7777/", {method:"POST", ...})` is blocked; add
  the origin in the dialog's allowlist → allowed. `requestPermission` via
  `POST /` answers even without the key (that's how clients ask for access).

## 3. Discovery surfaces

- [ ] `curl.exe -s $T/actions` → JSON list of **122** actions.
- [ ] `$T/docs` renders Swagger UI; `$T/redoc` renders; spot-open a few
  routes and check the descriptions read sensibly.
- [ ] `curl.exe -s $T/openapi.json | curl.exe`-free sanity: loads, has tags
  Cards/Notes/Decks/Models/Reviews/Events/Collection/Media/FSRS/GUI/Tags.
- [ ] `curl.exe -s $T/` (GET) → the AnkiConnect identification probe
  responds (what Yomitan pings).

## 4. Decks & deck-configs

```powershell
curl.exe -s @H -X POST $T/v1/decks -d '{"name":"TestSuite::Sub"}'
```

- [ ] Create → 201/200 with id; `TestSuite` parent auto-created; visible in
  Anki's deck list **immediately** (repaint check).
- [ ] `GET $T/v1/decks` → list incl. due counts; `GET
  "$T/v1/decks?select=id,name&shape=object"` → just those fields, faster
  `stats.duration_ms` (no due-tree pass).
- [ ] PATCH rename: `-X PATCH $T/v1/decks/<id> -d '{"name":"TestSuite::Renamed"}'`
  → deck list updates. PATCH `desc`, and `desired_retention` (set 0.85,
  read back ≈0.85; null clears).
- [ ] DELETE the subdeck → gone from Anki; deleting deck id 1 → 400.
- [ ] Deck-configs: `GET /v1/deck-configs`; POST create (clone), PATCH a
  value (e.g. new per day), verify in Anki's deck options; DELETE it;
  DELETE the default config id → 400.

## 5. Models (+ fields/templates)

```powershell
curl.exe -s @H -X POST $T/v1/models -d '{"name":"TSModel","fields":[{"name":"F"},{"name":"B"}],"templates":[{"name":"Card 1","qfmt":"{{F}}","afmt":"{{B}}"}]}'
```

- [ ] Create; appears in Anki's notetype manager. Duplicate name → 400.
- [ ] `GET /v1/models` full rows; `?select=id,name` fast path.
- [ ] PATCH name/css/sort_field → visible in Anki.
- [ ] Fields: POST a field, PATCH (rename + font), DELETE it, PUT
  `fields:order` reorder — after each, check Anki's field editor agrees.
  Deleting the last field → 400.
- [ ] Templates: same cycle on `templates`; deleting the last template → 400.
- [ ] `POST /v1/models:find-replace` on qfmt text → template changed.
- [ ] DELETE the model (with no notes) → gone.

## 6. Notes

```powershell
curl.exe -s @H -X POST $T/v1/notes -d '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"犬","Back":"dog"},"tags":["ts"]}'
```

- [ ] Create → id returned; **Browser open while doing it** — the new note
  appears without clicking (repaint check). Duplicate without
  `allow_duplicate` → 409/400 with duplicate ids; with it → created.
- [ ] Empty first field → 400; cloze model without `{{c1::}}` → 400.
- [ ] `GET /v1/notes` (bare page), `?search=tag:ts`, `?where=id==<id>`;
  each note row carries its `cards` ids.
- [ ] PATCH fields; PATCH tags (`tags` replace, `add_tags`, `remove_tags`;
  combining both forms → 400). Browser shows the edit live.
- [ ] Change notetype via PATCH with `model_name` + `fields` → retyped;
  without `fields` → 400 (would blank the note).
- [ ] `POST /v1/notes:check` with a good, a duplicate, and an empty-field
  candidate → per-candidate verdicts, nothing created.
- [ ] DELETE a note → its cards vanish from the browser immediately.

## 7. Cards — reads

Seed: a handful of notes in `TestSuite`, review two in Anki first.

- [ ] `GET /v1/cards?limit=5` → page + cursor; walk the cursor to the end.
- [ ] `?search=deck:TestSuite is:due` (Anki syntax) filters.
- [ ] `?where=queue==-1` after suspending one card → only it.
- [ ] `?select=id,due,queue&shape=object` → narrow rows, small
  duration_ms; full rows include `question`/`answer` HTML, `next_reviews`,
  FSRS fields (`memory_state` non-null on the reviewed cards with FSRS on),
  `retrievability`.
- [ ] `?where=note_id==<nid>` → that note's cards (index tier).
- [ ] `POST /v1/cards/query` with the same params in the body → identical
  result (GET/POST parity).

## 8. Cards — writes

- [ ] Each verb, watching the **Browser stay in sync without clicking**:
  `:suspend` / `:unsuspend` (affected counts only what changed),
  `:bury` / `:unbury`, `:set-flag` (colour appears), `:set-due-date`
  (`"5"` and `"5-7"`; garbage → 400), `:forget` (back to new),
  `:reposition`, `:change-deck` (unknown deck → 400/404, deck NOT
  created), `:set-ease`.
- [ ] `:answer` with ease 3 on a due card → card advances, revlog row
  appears in `GET /v1/reviews?where=card_id==<id>`; answering a suspended
  card unsuspends it; ease 5 → 422.
- [ ] `:set-values` — plain column (`factor`) works; `reps` without
  `force` → 400; with `force:true` → written.
- [ ] `:set-memory-state` → 400 until you enable the gate in the settings
  dialog; after enabling (no restart) → works.
- [ ] **Batch**:

  ```powershell
  curl.exe -s @H -X POST $T/v1/cards:batch -d '{"operations":[{"op":"suspend","card_ids":[ID1]},{"op":"set-due-date","card_ids":[ID2],"days":"3"},{"op":"set-flag","card_ids":[ID3],"flag":2}]}'
  ```

  → per-op results; Anki's Edit menu shows **one** entry "Undo Card
  Batch"; **one Ctrl+Z reverts all three**; unknown op or bad deck in the
  list → 400 and *nothing* applied.

## 9. Reviews & tags

- [ ] `GET /v1/reviews` newest-last, real rows from your reviews; `?search=
  deck:TestSuite`; `?where=ease==3`; cursor walk.
- [ ] `POST /v1/reviews` two rows (unique epoch-ms ids) → inserted; visible
  in `cardReviews` and (after stats refresh) Anki's stats; **undo history
  is cleared** — expected, raw revlog write. Duplicate id → error, neither
  row of that batch lands.
- [ ] Tags: `GET /v1/tags` (+`?prefix=`), `:bulk-add` / `:bulk-remove` on
  note ids, PATCH `/v1/tags/ts` `{"name":"ts2"}` renames incl. children,
  DELETE removes, `:clear-unused` after deleting tagged notes.

## 10. Media

- [ ] POST base64 (`{"filename":"ts.txt","data":"aGVsbG8="}`) → stored name
  returned; collision on re-upload → renamed name returned, `renamed:true`.
- [ ] POST `{"url": "..."}` from a reachable URL → fetched and stored.
- [ ] POST `{"path": "C:\\...\\file.png"}` → 400 while
  `gates.media_allow_local_path` is off; enable in dialog → works.
- [ ] `GET /v1/media?prefix=ts` lists; `GET /v1/media/ts.txt` streams with
  a real Content-Type; DELETE removes; GET again → 404.
- [ ] Filename traversal attempt (`..%2Fx`) → 400, nothing written.

## 11. FSRS & jobs

- [ ] `POST /v1/fsrs:compute-params` (deck with your review history) →
  **202 + job id**; `GET /v1/jobs/<id>` shows `queued/running` with
  progress, then `done` with params.
- [ ] Start another and `POST /v1/jobs/<id>:abort` → job ends `aborted`.
- [ ] `:evaluate-params`, `:simulate`, `:simulate-workload`,
  `:optimal-retention` each return plausible numbers (spot-check against
  Anki's own FSRS optimizer output for the same deck).
- [ ] Two compute jobs at once → second rejected/queued per the one-job
  rule, not interleaved garbage.

## 12. GUI routes

Each should produce the visible effect, and return cleanly:

- [ ] `gui:browse` `{"query":"deck:TestSuite"}` → Browser opens filtered.
- [ ] `gui:select-card`, `gui:selected-notes` (select rows first),
  `gui:edit-note`.
- [ ] `gui:add-cards` (opens dialog) and `gui:set-add-note-data`
  (pre-fills it).
- [ ] `gui:deck-browser`, `gui:deck-overview`, `gui:deck-review` → straight
  into the reviewer.
- [ ] Reviewer flow by API only: `gui/current-card` → `gui:show-answer` →
  `gui:answer-card` `{"ease":3}` → next card appears; `gui:show-question`,
  `gui:start-card-timer`, `gui:play-audio` on a card with sound.
- [ ] `gui:undo` undoes the last op (pair with an API mutation).
- [ ] `gui:import-file` with an .apkg path → Anki's import dialog/flow.
- [ ] LAST, if you want: `gui:exit` quits Anki (known-cosmetic traceback if
  Add Cards is open).

## 13. Collection & profiles (destructive-ish — do late)

- [ ] `POST /v1/collection:export` `{"deck":"TestSuite","path":"...apkg"}`
  → file exists on the Anki machine.
- [ ] `POST /v1/collection:import` of that file → notes appear (dupes
  skipped per Anki rules).
- [ ] `:check-database` → runs, Anki stays healthy; `:reload` → collection
  reopens.
- [ ] `:sync` with AnkiWeb configured (optional) → sync runs; watch suite
  14's `sync started/finished` + `reset` events while it does.
- [ ] `GET /v1/profiles` lists profiles, marks the open one;
  `POST /v1/profiles:load` to the throwaway → Anki switches; requests
  during the switch → 503, not corruption; switch back.

## 14. Event stream

Terminal A: `curl.exe -N "$T/v1/events?api_key=test-key-123"`.

- [ ] Connect: `retry:` preamble + `: connected`; `: ping` ~every 15s.
- [ ] Review a card in Anki → `review {card_id, ease}` then
  `op {origin:"ui", changes:[card, study_queues...]}` with a label.
- [ ] Edit a note in Anki's editor → one `op` per keystroke, label
  "Update Note" (this is Anki's own granularity — client debounces).
- [ ] API write (suite 8 verb) → `op {origin:"api", card_ids:[...],
  label:...}`; note patch → `note_ids`; deck patch → `deck_ids`;
  `cards:batch` → ONE op, label "Card Batch", union of card ids.
- [ ] `answerCards` via shim → `op {origin:"api", card_ids}` and **no**
  `review` event (that hook is reviewer-only).
- [ ] Sync → `sync started`, `sync finished`, then `reset`.
- [ ] Change the API key in the dialog mid-stream → stream ends with
  `close {"reason":"auth"}`.
- [ ] `tsunagi.reload_addon()` (or profile switch) with the stream open →
  `close {"reason":"shutdown"}`, port rebinds, reconnect works, and events
  arrive exactly once (no duplicate hooks).
- [ ] Browser `new EventSource(".../v1/events?api_key=...")` from an
  allowlisted origin → events in DevTools.
- [ ] `?timeout=2` and `?max_events=1` close with their reasons (script
  ergonomics).

## 15. AnkiConnect shim — protocol

All via `POST $T/ -d '{"action":...,"version":6,...}'` (+ key as `"key"`
param if set — and confirm a wrong `"key"` is rejected the AnkiConnect way).

- [ ] Envelope: version 6 → `{result, error}`; version 4 → bare result;
  malformed JSON body → error envelope, **never** a 422.
- [ ] `version`, `deckNames`, `modelNames`, `findNotes`, `findCards`,
  `notesInfo` (by ids and by `query` — try a broad query; slow is fine,
  503 is not), `cardsInfo`, `getEaseFactors`, `areDue`, `getIntervals`
  (+`complete:true`).
- [ ] Writes: `addNote` (+ duplicate → canonical error string), `addNotes`,
  `updateNoteFields`, `deleteNotes`, `createDeck`, `changeDeck`,
  `suspend`/`unsuspend` (True/False/null quirks), `forgetCards`,
  `relearnCards`, `setDueDate`, `setEaseFactors`.
- [ ] The three newest: `answerCards` → `[true,false]` mix, `"invalid
  ease"` verbatim on ease 9; `setSpecificValueOfCard` quirk ladder — card
  as list → bare `false`; risky key without `warning_check` → bare
  `false`; with it → `[true]`; missing card → `[[false, "..."]]`;
  `insertReviews` → `null`, rows land.
- [ ] `multi` with 3 mixed sub-actions → per-action results in order; one
  failing sub-action doesn't poison the others.
- [ ] `guiBrowse`, `guiCurrentCard`, `guiAnswerCard`, `guiDeckReview` — the
  compat GUI set behaves like suite 12.
- [ ] `sync`, `getProfiles`, `loadProfile`, `exportPackage`,
  `importPackage`, `getMediaFilesNames`, `storeMediaFile`,
  `retrieveMediaFile`, `deleteMediaFile`.
- [ ] `apiReflect` and unknown action → `"unsupported action"` error.

## 16. Shim — real clients (the drop-in proof)

- [ ] **Yomitan** pointed at Tsunagi's port: card creation from a lookup
  works end-to-end incl. audio/media; duplicate detection behaves.
- [ ] **Asbplayer**: mining a card and updating the last card's media.
- [ ] **Yomine** (your pipeline): add note via Tsunagi → Asbplayer patches
  media by note id → Yomine sees `op {origin:"api", note_ids:[...]}` on
  the stream and matches it. No client config changed except the port.
- [ ] AnkiConnect (the real addon) DISABLED throughout — nothing missed it.

## 17. Performance spot checks (real collection, read-only)

Compare `stats.duration_ms` in each response:

- [ ] `GET /v1/cards?limit=100` and page 2 via cursor → low single-digit ms
  for ids + hydration cost only (was: whole-collection scan per page).
- [ ] `GET /v1/notes?limit=100` same shape.
- [ ] `GET /v1/reviews?limit=100` → ~1ms-class; page through a few cursors.
- [ ] `GET /v1/cards?where=queue==-1&limit=50` on the full collection →
  returns quickly despite scanning (two-phase: no renders for rejects).
- [ ] `GET /v1/cards?select=id,due&limit=200` vs full rows → visible gap
  (renders/scheduling skipped).
- [ ] A 10-op `cards:batch` on real cards → one round trip, one undo.
- [ ] `deckNamesAndIds` and `deckNameFromId` via shim → instant (no
  due-tree).

## 18. Errors & busy behaviour

- [ ] Unknown ids: `GET /v1/notes?where=id==1` → empty 200; DELETE
  `/v1/decks/999999` → 404; PATCH a missing note → 404.
- [ ] Malformed: `?search="unbalanced` → 400 with Anki's message;
  `?where=nonsense` → 400 with the DSL help text; bad JSON on a native
  POST → 422 (native may 422; only `POST /` never does).
- [ ] **Busy**: open a modal dialog in Anki (e.g. deck options), then make
  an API write → 503 within ~15s (`AnkiBusyError`), not a hang; close the
  dialog → same request succeeds.
- [ ] Kill/restart Anki mid-stream with a client polling → clients get
  connection errors, then clean service after boot; no port squatting.

---

When every suite is initialled: `git push` is the only thing left.

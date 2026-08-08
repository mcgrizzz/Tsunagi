# Tsunagi — full manual test plan

Every surface a user can reach: 100 native routes, 122 AnkiConnect actions,
the settings dialog, the event stream, and the server lifecycle. Each item is
a checkbox with an exact copy-paste command and an expected result. Automated
tests already pin wire shapes and call counts — this plan is for the things
only a real Anki can prove: visible UI effects, undo, timing on a real
collection, and drop-in behaviour with real clients.

> **Rebuild note:** the suite‑1/2 findings (reload_addon crash, vendor-warning
> noise) are fixed in the current build. Re-sync the addon (dev_sync or
> reinstall `dist/tsunagi-0.0.1.ankiaddon`) and restart Anki before
> continuing, then re-run the two suite‑1 items marked ⟳.

## 0. Setup and conventions

- **Use a throwaway profile** (File → Switch Profile → Add). Suites 4–6, 8–10
  and 13 create, mutate and DELETE decks/models/notes, and suite 13
  imports/exports and switches profiles. The perf spot checks (suite 17) are
  read-only — run those against your real collection.
- Install `dist/tsunagi-0.0.1.ankiaddon` (Tools → Add-ons → Install from
  file), **fully restart Anki**, and keep the console visible when a step
  says "console".
- Run the suites **in order in one PowerShell window** — later suites reuse
  variables (`$nid`, `$cid1`, …) captured in earlier ones. Each capture line
  is marked so you can re-run just it if you restart the shell.
- Paste this once (the `Api` helper prints the HTTP status and returns the
  parsed body, including for expected 4xx/5xx — works on PowerShell 5.1
  and 7+):

  ```powershell
  $T = "http://127.0.0.1:7777"
  $H = @{}    # suite 2 changes this to @{ "X-Api-Key" = "test-key-123" }
  $K = @()    # curl.exe form of the same header, also set in suite 2

  function Api {
    param([string]$Method = 'GET', [string]$Path = '/', [string]$Body = $null, [hashtable]$Extra = @{})
    $hdrs = @{} + $H; foreach ($k in $Extra.Keys) { $hdrs[$k] = $Extra[$k] }
    $p = @{ Uri = "$T$Path"; Method = $Method; Headers = $hdrs; UseBasicParsing = $true }
    if ($null -ne $Body) { $p.Body = $Body; $p.ContentType = 'application/json' }
    if ($PSVersionTable.PSVersion.Major -ge 7) { $p.SkipHttpErrorCheck = $true }
    try { $r = Invoke-WebRequest @p; $code = [int]$r.StatusCode; $text = $r.Content }
    catch {
      $resp = $_.Exception.Response
      if ($null -eq $resp) { throw }
      $code = [int]$resp.StatusCode
      $text = $_.ErrorDetails.Message
      if (-not $text) { try { $text = (New-Object System.IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch {} }
    }
    Write-Host "HTTP $code" -ForegroundColor $(if ($code -lt 400) { 'Green' } else { 'Yellow' })
    if ($text) { try { $text | ConvertFrom-Json } catch { $text } }
  }
  ```

  Usage: `Api GET /v1/health`, `Api POST /v1/decks '{"name":"X"}'`. Pipe
  through `| ConvertTo-Json -Depth 6` any time you want the full body.
  Bodies that embed a captured variable are built with hashtables +
  `ConvertTo-Json` — that sidesteps every PowerShell quoting difference.
  `curl.exe` (not the `curl` alias) is used only where streaming or raw
  headers matter.
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

- [x] Fresh start: console shows no `[tsunagi]` errors.
- [x] `Api GET /v1/health` → HTTP 200, `ok: true`, `port: 7777`.
- [x] Tools → **Tsunagi Settings…** opens the dialog (not the raw JSON
  editor). Every field populated; gates section lists the toggles.
- [x] Change **port** to 7778, OK → tooltip confirms; old port dead, new
  port answers `/v1/health`. Change back.
- [x] Uncheck **enabled**, OK → server stops (connection refused). Re-check,
  OK → server back. No Anki restart at any point.
- [x] Restore Defaults button repopulates the form but writes nothing until
  OK.
- [x] Tools → Add-ons → Tsunagi → Config opens the same dialog.
- [ ] ⟳ Switch profile away and back → server stops and restarts cleanly; no
  "thread did not stop" in the console; port rebinds. **No
  vendored-module warning for Anki's own `app_packages`** (attr, click,
  idna, …) — that's expected environment now, filtered out. A warning
  naming a path under `addons21\<other-addon>` is still real and worth
  noting.
- [ ] ⟳ Debug console (Ctrl+Shift+;):

  ```python
  import tsunagi; tsunagi.reload_addon()
  ```

  → `reloaded N modules; listening on http://127.0.0.1:7777` (the uvicorn
  `isatty` crash is fixed — the server no longer touches Python's logging
  config).

## 2. Auth & CORS

Auth model, so the checks below aren't surprising: when an API key is set,
**every route requires it except** `/` (GET redirect + the AnkiConnect RPC,
which uses the body `"key"` field instead), `/docs`, `/redoc`,
`/openapi.json`, `/docs/oauth2-redirect`, and `/v1/health`. The docs trio is
open by design: browsers can't attach headers to a page load, the schema
describes a public open-source API (structure, never data), and cross-origin
browsers are stopped by CORS anyway. `/v1/health` is a liveness probe.

- [x] With no key configured: `Api GET /v1/decks` → HTTP 200.
- [x] Set `api_key` to `test-key-123` in the dialog, OK. Then update the
  shell:

  ```powershell
  $H = @{ "X-Api-Key" = "test-key-123" }
  $K = @("-H", "X-Api-Key: test-key-123")
  ```

- [x] Header forms (curl sends *no* key / the *wrong* key / Bearer):

  ```powershell
  curl.exe -s -o NUL -w "%{http_code}`n" $T/actions
  curl.exe -s -o NUL -w "%{http_code}`n" $T/actions -H "X-Api-Key: wrong"
  curl.exe -s -o NUL -w "%{http_code}`n" $T/actions -H "Authorization: Bearer test-key-123"
  Api GET /actions
  ```

  → `401`, `401`, `200`, `HTTP 200`.
- [x] Exempt paths answer without a key (by design, see above):

  ```powershell
  curl.exe -s -o NUL -w "%{http_code}`n" $T/openapi.json
  curl.exe -s -o NUL -w "%{http_code}`n" $T/v1/health
  ```

  → `200`, `200`.
- [x] Query-param key works on the event stream only:

  ```powershell
  curl.exe -sN "$T/v1/events?api_key=test-key-123&timeout=2"
  curl.exe -s -o NUL -w "%{http_code}`n" "$T/v1/decks?api_key=test-key-123"
  ```

  → first streams for ~2s then closes; second → `401`.
- [ ] CORS — the default allowlist entry `http://localhost` also covers
  `127.0.0.1` origins and browser extensions (AnkiConnect's exact
  semantics; it's why Yomitan needs zero setup). So test with an origin
  that is genuinely unlisted:

  ```powershell
  curl.exe -si $T/v1/decks @K -H "Origin: https://evil.example" | Select-Object -First 1
  curl.exe -si $T/v1/decks @K -H "Origin: http://localhost" | Select-String "HTTP|Access-Control"
  ```

  → first: `403` (body "Disallowed CORS origin"); second: `200` with
  `Access-Control-Allow-Origin: http://localhost`.
- [ ] Preflight:

  ```powershell
  curl.exe -si -X OPTIONS $T/v1/decks -H "Origin: https://evil.example" -H "Access-Control-Request-Method: GET" | Select-Object -First 1
  curl.exe -si -X OPTIONS $T/v1/decks -H "Origin: http://localhost" -H "Access-Control-Request-Method: GET" | Select-Object -First 1
  ```

  → `403`, then `200`.
- [ ] `POST /` stays reachable from any origin so clients can *ask* for
  access, but actions other than `requestPermission` are refused:

  ```powershell
  Api POST / '{"action":"version","version":6}' -Extra @{ Origin = "https://evil.example" }
  Api POST / '{"action":"requestPermission","version":6}' -Extra @{ Origin = "https://evil.example" }
  ```

  → first: HTTP 403, empty body. Second: **a Yes/No dialog appears in
  Anki**. Click No → `{"permission": "denied"}`. Run it again, click Yes →
  `{"permission": "granted", "requireApikey": true, "version": 6}`, the
  origin appears in the settings dialog's allowlist, and the `version`
  probe above now answers.
- [ ] `requestPermission` with no Origin header (a local script) → granted
  without any dialog:

  ```powershell
  Api POST / '{"action":"requestPermission","version":6}'
  ```

  → `{"result": {"permission": "granted", "requireApikey": true, "version": 6}, "error": null}`.

## 3. Discovery surfaces

- [ ] `(Api GET /actions).actions.Count` → **122**.
- [ ] `curl.exe -si $T/ | Select-Object -First 5` → a redirect
  (`307`) with `location: /docs`.
- [ ] Open `http://127.0.0.1:7777/docs` in a browser → Swagger UI renders;
  spot-open a few routes and check the descriptions read sensibly.
  `http://127.0.0.1:7777/redoc` renders too.
- [ ] OpenAPI sanity — 96 operations (the 100 live routes minus the four
  docs/schema routes, which FastAPI serves outside the schema):

  ```powershell
  $spec = Api GET /openapi.json
  ($spec.paths.PSObject.Properties | ForEach-Object { $_.Value.PSObject.Properties.Name }).Count
  ```

  → `96`.

## 4. Decks & deck-configs

- [ ] Create (capture the id) — parent `TestSuite` auto-created; both decks
  visible in Anki's deck list **immediately**, no click needed:

  ```powershell
  $deck = Api POST /v1/decks '{"name":"TestSuite::Sub"}'   # CAPTURE
  $sub = $deck.result.id
  ```

  → HTTP 201, `$sub` is a numeric id.
- [ ] List, then the narrow fast path (compare `stats.duration_ms` — the
  narrow one skips the scheduler's due-tree pass):

  ```powershell
  (Api GET /v1/decks).items | Select-Object name, new_count, review_count
  (Api GET "/v1/decks?select=id,name&shape=object").stats
  ```

- [ ] Rename + describe — deck list updates live:

  ```powershell
  Api PATCH /v1/decks/$sub '{"name":"TestSuite::Renamed","description":"manual test deck"}'
  ```

- [ ] FSRS retention override (26.08 supports it): set, read back, clear:

  ```powershell
  Api PATCH /v1/decks/$sub '{"desired_retention":0.85}'
  (Api GET /v1/decks).items | Where-Object { $_.id -eq $sub } | Select-Object name, desired_retention
  Api PATCH /v1/decks/$sub '{"desired_retention":null}'
  ```

  → reads back `0.85`, then null after clearing.
- [ ] Delete the subdeck; the default deck refuses:

  ```powershell
  Api DELETE /v1/decks/$sub
  Api DELETE /v1/decks/1
  ```

  → `success: true` then HTTP 400.
- [ ] Deck-configs — clone the default, patch a value, verify in Anki's
  deck options UI, delete; default config refuses:

  ```powershell
  $cfg = Api POST /v1/deck-configs '{"name":"TSConfig","clone_from_id":1}'   # CAPTURE
  $cfgId = $cfg.result.id
  Api PATCH /v1/deck-configs/$cfgId '{"new":{"perDay":7}}'
  ```

  → in Anki: any deck's Options → preset "TSConfig" exists with New
  cards/day = 7. Then:

  ```powershell
  Api DELETE /v1/deck-configs/$cfgId
  Api DELETE /v1/deck-configs/1
  ```

  → `success: true` then HTTP 400.

## 5. Models (+ fields/templates)

- [ ] Create; appears in Tools → Manage Note Types. Re-running the same
  create → HTTP 400 (duplicate name):

  ```powershell
  $model = Api POST /v1/models '{"name":"TSModel","fields":[{"name":"F"},{"name":"B"}],"templates":[{"name":"Card 1","qfmt":"{{F}}","afmt":"{{F}}<hr>{{B}}"}]}'   # CAPTURE
  $mid = $model.result.id
  Api POST /v1/models '{"name":"TSModel","fields":[{"name":"F"}],"templates":[{"name":"Card 1","qfmt":"{{F}}","afmt":"{{F}}"}]}'
  ```

- [ ] Cloze model (`type: 1` — needed by suite 6):

  ```powershell
  $cloze = Api POST /v1/models '{"name":"TSCloze","type":1,"fields":[{"name":"Text"}],"templates":[{"name":"Cloze","qfmt":"{{cloze:Text}}","afmt":"{{cloze:Text}}"}]}'   # CAPTURE
  ```

- [ ] `(Api GET /v1/models).items.Count` (full rows) and
  `Api GET "/v1/models?select=id,name"` (fast path) both list TSModel.
- [ ] `Api PATCH /v1/models/$mid '{"css":".card { color: navy; }"}'` →
  visible in the card template editor's Styling tab.
- [ ] Fields — full cycle, checking Anki's Fields… editor after each
  (fields are addressed **by name** in the path):

  ```powershell
  Api POST /v1/models/$mid/fields '{"name":"Extra"}'
  Api PATCH /v1/models/$mid/fields/Extra '{"name":"Extra2","font":"Consolas"}'
  Api PUT /v1/models/$mid/fields:order '{"order":["B","F","Extra2"]}'
  Api DELETE /v1/models/$mid/fields/Extra2
  ```

  Then the last-field guard, on TSCloze (single field):

  ```powershell
  Api DELETE "/v1/models/$($cloze.result.id)/fields/Text"
  ```

  → HTTP 400 "Cannot delete last field…".
- [ ] Templates — same cycle:

  ```powershell
  Api POST /v1/models/$mid/templates '{"name":"Card 2","qfmt":"{{B}}","afmt":"{{F}}"}'
  Api PATCH "/v1/models/$mid/templates/Card 2" '{"qfmt":"{{B}}?"}'
  Api PUT /v1/models/$mid/templates:order '{"order":["Card 2","Card 1"]}'
  Api DELETE "/v1/models/$mid/templates/Card 2"
  Api DELETE "/v1/models/$mid/templates/Card 1"
  ```

  → all 200 until the last delete → HTTP 400 (last template).
- [ ] Find-replace in templates:

  ```powershell
  Api POST /v1/models:find-replace '{"find":"<hr>","replace":"<hr id=answer>","modelName":"TSModel"}'
  ```

  → `affected: 1`; the template's back side changed in the editor.
- [ ] `Api DELETE /v1/models/$mid` (no notes on it) → gone from the manage
  list. **Keep TSCloze** — suite 6 uses it.

## 6. Notes

- [ ] Create — with Anki's **Browser open**, the new note appears without
  clicking:

  ```powershell
  $n1 = Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"dog"},"tags":["ts"]}'   # CAPTURE
  $nid = $n1.result.id
  ```

  → HTTP 201; `$n1.result.cards` holds the generated card id(s).
- [ ] Duplicate handling — same Front again:

  ```powershell
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"x"}}'
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"x"},"allowDuplicate":true}'
  ```

  → HTTP 409 naming the duplicate note id(s); then HTTP 201. Delete the
  duplicate: `Api DELETE /v1/notes/<its id>`.
- [ ] Validation: empty first field, and a cloze note with no `{{c1::}}`:

  ```powershell
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"","Back":"x"}}'
  Api POST /v1/notes '{"modelName":"TSCloze","deckName":"TestSuite","fields":{"Text":"no cloze here"}}'
  ```

  → both HTTP 400.
- [ ] Reads:

  ```powershell
  Api GET "/v1/notes?limit=5"
  Api GET "/v1/notes?search=tag:ts"
  Api GET "/v1/notes?where=id==$nid"
  ```

  → each row carries its `cards` ids; the search/where forms return
  exactly the seeded note.
- [ ] Patch fields and tags — Browser shows each edit live:

  ```powershell
  Api PATCH /v1/notes/$nid '{"fields":{"Back":"DOG"}}'
  Api PATCH /v1/notes/$nid '{"addTags":["ts-added"]}'
  Api PATCH /v1/notes/$nid '{"removeTags":["ts-added"]}'
  Api PATCH /v1/notes/$nid '{"tags":["x"],"addTags":["y"]}'
  ```

  → first three 200; the combined form → HTTP 400.
- [ ] Retype (scratch note, since retyping is destructive to fields):

  ```powershell
  $n2 = Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"retype-me","Back":"z"}}'   # CAPTURE
  Api PATCH "/v1/notes/$($n2.result.id)" '{"modelName":"TSCloze"}'
  Api PATCH "/v1/notes/$($n2.result.id)" '{"modelName":"TSCloze","fields":{"Text":"{{c1::tsunagi}}"}}'
  ```

  → without `fields` HTTP 400 (would blank the note); with them, 200 and
  the Browser shows it as a TSCloze note.
- [ ] `notes:check` — verdicts only, nothing created (note count in the
  Browser unchanged):

  ```powershell
  Api POST /v1/notes:check '{"notes":[{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"brand-new","Back":"1"}},{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"dup"}},{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"","Back":""}}]}'
  ```

  → `results` states: `normal`, `duplicate` (with `duplicate_note_ids`),
  `empty`.
- [ ] `Api DELETE "/v1/notes/$($n2.result.id)"` → its cards vanish from the
  Browser immediately.

## 7. Cards — reads

- [ ] Seed six more notes, then capture three card ids: `# CAPTURE`

  ```powershell
  1..6 | ForEach-Object { Api POST /v1/notes ('{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"card-seed-' + $_ + '","Back":"b"},"tags":["seed"]}') | Out-Null }
  $cards = (Api GET "/v1/cards?search=deck:TestSuite&select=id&shape=object&limit=100").items
  $cid1 = $cards[0].id; $cid2 = $cards[1].id; $cid3 = $cards[2].id
  ```

- [ ] Cursor walk:

  ```powershell
  $p1 = Api GET "/v1/cards?limit=5"
  $p2 = Api GET "/v1/cards?limit=5&cursor=$($p1.next_cursor)"
  ```

  → 5 items each, no overlap in ids; keep following `next_cursor` until it
  is null — total equals your card count.
- [ ] Anki search syntax: `Api GET "/v1/cards?search=deck:TestSuite%20is:new"`
  → the seeded cards.
- [ ] Where DSL (suspend one card first so the filter has a hit):

  ```powershell
  Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  (Api GET "/v1/cards?where=queue==-1").items | Select-Object id, queue
  Api POST /v1/cards:unsuspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  ```

  → exactly the suspended card, `queue: -1`.
- [ ] Narrow vs full rows (compare `stats.duration_ms`):

  ```powershell
  (Api GET "/v1/cards?select=id,due,queue&shape=object&limit=50").stats
  (Api GET "/v1/cards?limit=50").stats
  ```

  → full rows include `question`/`answer` HTML, `next_reviews`, and (on a
  reviewed card with FSRS on) `memory_state`/`retrievability`; the narrow
  read is visibly faster.
- [ ] Index tier: `Api GET "/v1/cards?where=note_id==$nid"` → that note's
  card(s).
- [ ] GET/POST parity:

  ```powershell
  Api POST /v1/cards/query '{"select":"id,due","shape":"object","limit":5}'
  ```

  → same shape as the GET equivalent.

## 8. Cards — writes

Keep the Browser open on `deck:TestSuite` the whole suite — every verb
should repaint it **without clicking**.

- [ ] Verbs, one at a time (each → HTTP 200 with an `affected` count):

  ```powershell
  Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)      # again -> affected: 0 (already suspended)
  Api POST /v1/cards:unsuspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  Api POST /v1/cards:bury (@{cardIds=@($cid1)} | ConvertTo-Json)
  Api POST /v1/cards:unbury (@{cardIds=@($cid1)} | ConvertTo-Json)
  Api POST /v1/cards:set-flag (@{cardIds=@($cid1); flag=2} | ConvertTo-Json)   # orange flag appears
  Api POST /v1/cards:set-due-date (@{cardIds=@($cid1); days="5"} | ConvertTo-Json)
  Api POST /v1/cards:set-due-date (@{cardIds=@($cid1); days="5-7"} | ConvertTo-Json)
  Api POST /v1/cards:set-due-date (@{cardIds=@($cid1); days="garbage"} | ConvertTo-Json)   # -> HTTP 400
  Api POST /v1/cards:forget (@{cardIds=@($cid1)} | ConvertTo-Json)       # back to new
  Api POST /v1/cards:reposition (@{cardIds=@($cid1); startingFrom=0} | ConvertTo-Json)
  Api POST /v1/cards:change-deck (@{cardIds=@($cid1); deckName="NoSuchDeck"} | ConvertTo-Json)   # -> HTTP 400/404, deck NOT created
  Api POST /v1/cards:change-deck (@{cardIds=@($cid1); deckName="TestSuite"} | ConvertTo-Json)
  Api POST /v1/cards:set-ease (@{cards=@(@{id=$cid1; factor=2600})} | ConvertTo-Json -Depth 3)
  ```

- [ ] Answer — the card advances, a revlog row appears; a suspended card is
  unsuspended by answering; ease 5 fails validation:

  ```powershell
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid2; ease=3})} | ConvertTo-Json -Depth 3)
  Api GET "/v1/reviews?where=card_id==$cid2"
  Api POST /v1/cards:suspend (@{cardIds=@($cid3)} | ConvertTo-Json)
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid3; ease=3})} | ConvertTo-Json -Depth 3)
  (Api GET "/v1/cards?where=id==$cid3").items[0].suspended
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid2; ease=5})} | ConvertTo-Json -Depth 3)
  ```

  → review row present; `suspended` → `False`; last call → HTTP 422.
- [ ] Raw column writes — plain column fine, scheduling column needs
  `force`:

  ```powershell
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{factor=2700}} | ConvertTo-Json)
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{reps=99}} | ConvertTo-Json)
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{reps=99}; force=$true} | ConvertTo-Json)
  ```

  → 200, then HTTP 400 naming the risky column, then 200.
- [ ] Gate check — `:set-memory-state` → HTTP 400 until you enable its gate
  in the settings dialog; after enabling (no restart) it works:

  ```powershell
  Api POST /v1/cards:set-memory-state (@{cards=@(@{id=$cid2; memory_state=@{stability=5.0; difficulty=3.2}})} | ConvertTo-Json -Depth 4)
  ```

- [ ] **Batch** — one op, ONE undo entry:

  ```powershell
  Api POST /v1/cards:batch (@{operations=@(
    @{op="suspend";      cardIds=@($cid1)},
    @{op="set-due-date"; cardIds=@($cid2); days="3"},
    @{op="set-flag";     cardIds=@($cid3); flag=4}
  )} | ConvertTo-Json -Depth 4)
  ```

  → `results` has three entries with per-op `affected`; Anki's Edit menu
  shows a single **Undo Card Batch**; **one Ctrl+Z reverts all three**.
  Then the all-or-nothing check:

  ```powershell
  Api POST /v1/cards:batch '{"operations":[{"op":"suspennd","cardIds":[1]}]}'
  ```

  → HTTP 400 listing the valid op names, and nothing was applied.

## 9. Reviews & tags

- [ ] Reads:

  ```powershell
  Api GET "/v1/reviews?limit=5"
  Api GET "/v1/reviews?search=deck:TestSuite"
  Api GET "/v1/reviews?where=ease==3"
  ```

  → rows in review order (`id` is the review's epoch-ms timestamp); the
  search form returns only reviews of TestSuite cards.
- [ ] Insert (history import) — both rows land atomically, and the **undo
  history is cleared** (expected: raw revlog write, Anki's own dbproxy
  behaviour):

  ```powershell
  $now = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()   # CAPTURE
  Api POST /v1/reviews (@{reviews=@(
    @{id=$now;     card_id=$cid2; ease=3; interval=1; last_interval=0; factor=2500; time_ms=4000; type=0},
    @{id=($now+1); card_id=$cid2; ease=4; interval=3; last_interval=1; factor=2500; time_ms=2500; type=1}
  )} | ConvertTo-Json -Depth 3)
  Api GET "/v1/reviews?where=card_id==$cid2"
  ```

  → `inserted: 2`; both rows in the read. Re-running the same insert (same
  ids) → an error response and **neither** row duplicated — the
  transaction rolls back, `inserted` is never partial.
- [ ] Tags:

  ```powershell
  Api GET /v1/tags
  Api GET "/v1/tags?prefix=ts"
  Api POST /v1/tags:bulk-add (@{noteIds=@($nid); tags="ts-bulk"} | ConvertTo-Json)
  Api PATCH /v1/tags/ts-bulk '{"name":"ts-bulk2"}'
  Api POST /v1/tags:bulk-remove (@{noteIds=@($nid); tags="ts-bulk2"} | ConvertTo-Json)
  Api POST /v1/tags:clear-unused
  ```

  → each `affected` ≥ 1 except the final clear-unused (whatever was left);
  the Browser's tag sidebar tracks every step.

## 10. Media

- [ ] Base64 upload, then the same name again → stored under a new name:

  ```powershell
  Api POST /v1/media '{"filename":"ts.txt","data":"aGVsbG8gdHN1bmFnaQ=="}'
  Api POST /v1/media '{"filename":"ts.txt","data":"b3RoZXIgY29udGVudA=="}'
  ```

  → first `{filename: "ts.txt", renamed: false}`; second `renamed: true`
  with a different stored `filename` (delete that one after checking).
- [ ] URL fetch:

  ```powershell
  Api POST /v1/media '{"url":"https://raw.githubusercontent.com/mcgrizzz/Tsunagi/main/README.md","filename":"ts-readme.md"}'
  ```

  → 201 with `size` > 0.
- [ ] Local-path gate:

  ```powershell
  Set-Content C:\Users\Public\ts-local.txt "hello from disk"
  Api POST /v1/media '{"path":"C:\\Users\\Public\\ts-local.txt"}'
  ```

  → HTTP 400 while `media_allow_local_path` is off; enable it in the
  settings dialog (no restart) → re-run → 201.
- [ ] List, download (real Content-Type), delete, confirm gone:

  ```powershell
  Api GET "/v1/media?prefix=ts"
  curl.exe -si @K "$T/v1/media/ts.txt" | Select-String "HTTP|Content-Type"
  Api DELETE /v1/media/ts.txt
  curl.exe -s -o NUL -w "%{http_code}`n" @K "$T/v1/media/ts.txt"
  ```

  → list shows the uploads; download `200` + `text/plain`; delete
  `success: true`; final GET `404`.
- [ ] Traversal refused, nothing written:

  ```powershell
  curl.exe -s -o NUL -w "%{http_code}`n" @K "$T/v1/media/..%2Fcollection.anki2"
  ```

  → `400`.

## 11. FSRS & jobs

FSRS optimization needs review history — on the throwaway profile expect a
clean "not enough reviews" job error, which is itself a pass. For real
numbers, re-run this suite against your real collection: compute/evaluate
only *return* parameters, they write nothing.

- [ ] Submit → poll:

  ```powershell
  $job = Api POST /v1/fsrs:compute-params '{"search":"deck:TestSuite"}'   # CAPTURE
  Api GET "/v1/jobs/$($job.job_id)"
  ```

  → HTTP 202 with `job_id`; polls show `queued`/`running` (with progress),
  then `done` with `result.params` — or `error` with Anki's
  not-enough-reviews message on a thin collection.
- [ ] Abort:

  ```powershell
  $job2 = Api POST /v1/fsrs:compute-params '{}'
  Api POST "/v1/jobs/$($job2.job_id):abort"
  ```

  → status ends `aborted` (poll once more if it was mid-transition).
- [ ] One-job rule: submit two computes back-to-back → the second is
  rejected or queued per the rule, never interleaved garbage.
- [ ] Synchronous endpoints (defaults are fine; on a real collection
  compare against Anki's own FSRS optimizer output):

  ```powershell
  Api POST /v1/fsrs:simulate '{"days_to_simulate":30}'
  Api POST /v1/fsrs:simulate-workload '{"days_to_simulate":30}'
  Api POST /v1/fsrs:optimal-retention '{"days_to_simulate":30}'
  ```

  → arrays of 30 daily values / workload maps / a retention in (0, 1).
- [ ] Evaluate with the computed params (real collection):

  ```powershell
  $done = Api GET "/v1/jobs/$($job.job_id)"
  Api POST /v1/fsrs:evaluate-params (@{params=$done.result.params} | ConvertTo-Json -Depth 3)
  ```

  → 202 + a job that finishes with log-loss/RMSE numbers.

## 12. GUI routes

Each produces its visible effect and returns cleanly.

- [ ] `Api POST /v1/gui:browse '{"query":"deck:TestSuite"}'` → Browser opens
  filtered; response carries the matching `card_ids`.
- [ ] `Api POST /v1/gui:select-card (@{card_id=$cid2} | ConvertTo-Json)` →
  the row highlights. Select a few rows by hand, then
  `Api GET /v1/gui/selected-notes` → their note ids.
- [ ] `Api POST /v1/gui:edit-note (@{note_id=$nid} | ConvertTo-Json)` → the
  edit dialog opens on that note.
- [ ] Add Cards dialog:

  ```powershell
  Api POST /v1/gui:add-cards '{"deckName":"TestSuite","modelName":"Basic","fields":{"Front":"from gui:add-cards","Back":"x"}}'
  Api POST /v1/gui:set-add-note-data '{"fields":{"Back":"appended"},"append":true}'
  ```

  → dialog opens pre-filled; the second call updates the open dialog's
  fields.
- [ ] Navigation: `Api POST /v1/gui:deck-browser`, then
  `Api POST /v1/gui:deck-overview '{"name":"TestSuite"}'`, then
  `Api POST /v1/gui:deck-review '{"name":"TestSuite"}'` → lands **directly
  in the reviewer** (make sure TestSuite has due/new cards; suite 8's
  forget left some new).
- [ ] Reviewer flow by API only:

  ```powershell
  Api GET /v1/gui/current-card
  Api POST /v1/gui:show-answer
  Api POST /v1/gui:answer-card '{"ease":3}'
  Api GET /v1/gui/current-card
  ```

  → question shown → answer shown → next card is a different id.
  Also: `Api POST /v1/gui:show-question`, `Api POST /v1/gui:start-card-timer`,
  and `Api POST /v1/gui:play-audio` on a card with `[sound:...]`.
- [ ] `Api POST /v1/gui:undo` → undoes the reviewer answer (Anki shows its
  undo toast).
- [ ] `Api POST /v1/gui:import-file '{"path":"C:\\Users\\Public\\ts-export.apkg"}'`
  → Anki's import flow opens (run after suite 13 creates the file).
- [ ] LAST, if you want: `Api POST /v1/gui:exit` quits Anki
  (known-cosmetic traceback if Add Cards is open).

## 13. Collection & profiles (destructive-ish — do late)

- [ ] Export → file exists → import it back (dupes skipped per Anki rules):

  ```powershell
  Api POST /v1/collection:export '{"deck":"TestSuite","path":"C:\\Users\\Public\\ts-export.apkg"}'
  Test-Path C:\Users\Public\ts-export.apkg
  Api POST /v1/collection:import '{"path":"C:\\Users\\Public\\ts-export.apkg"}'
  ```

  → `success: true`; `True`; import reports counts and Anki shows its
  import summary.
- [ ] `Api POST /v1/collection:check-database` → `success: true`, Anki
  stays healthy. `Api POST /v1/collection:reload` → collection reopens
  (deck list flickers/refreshes).
- [ ] Optional, with AnkiWeb configured: `Api POST /v1/collection:sync` →
  sync runs; watch suite 14's `sync started/finished` + `reset` events
  while it does.
- [ ] Profiles — list, switch away and back; requests during the switch →
  503, never corruption:

  ```powershell
  $profs = Api GET /v1/profiles   # CAPTURE
  $other = $profs.items | Where-Object { $_ -ne $profs.active } | Select-Object -First 1
  Api POST /v1/profiles:load (@{name=$other} | ConvertTo-Json)
  ```

  → Anki switches profiles (server restarts with it — re-run the load with
  your original profile's name to come back).

## 14. Event stream

Terminal A (leave running): 

```powershell
curl.exe -N "$T/v1/events?api_key=test-key-123"
```

Trigger from terminal B / the Anki UI:

- [ ] Connect: `retry:` preamble + `: connected`; `: ping` about every 15s.
- [ ] Review a card in Anki's reviewer → `review {card_id, ease}` then
  `op {origin:"ui", changes:[...card, study_queues...]}` with a label.
- [ ] Type in Anki's note editor → one `op` per keystroke, label
  "Update Note" (Anki's own granularity — clients debounce).
- [ ] API write: `Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)`
  → `op {origin:"api", card_ids:[...], label:"Suspend"}`. A note patch
  carries `note_ids`; a deck patch carries `deck_ids`.
- [ ] `cards:batch` (suite 8's three-op body) → **one** `op`, label
  "Card Batch", the union of the card ids.
- [ ] Shim write: `Api POST / (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid2; ease=3})}} | ConvertTo-Json -Depth 4)`
  → `op {origin:"api", card_ids}` and **no** `review` event (that hook is
  reviewer-only).
- [ ] Sync (if configured) → `sync started`, `sync finished`, then `reset`.
- [ ] Change the API key in the settings dialog mid-stream → stream ends
  with `close {"reason":"auth"}`. (Change it back, restart terminal A.)
- [ ] `tsunagi.reload_addon()` in the debug console (or a profile switch)
  with the stream open → `close {"reason":"shutdown"}`, port rebinds,
  reconnect works, and events arrive **exactly once** (no duplicate
  hooks).
- [ ] Script ergonomics — both close themselves with their reason:

  ```powershell
  curl.exe -N "$T/v1/events?api_key=test-key-123&timeout=2"
  curl.exe -N "$T/v1/events?api_key=test-key-123&max_events=1"
  ```

- [ ] Browser check: from a page on an allowlisted origin,
  `new EventSource("http://127.0.0.1:7777/v1/events?api_key=test-key-123")`
  → events visible in DevTools' Network → EventStream tab.

## 15. AnkiConnect shim — protocol

All through `POST /`. With a key set, the shim takes it as the body `"key"`
field (headers also accepted — the middleware runs first).

- [ ] Envelope + key handling:

  ```powershell
  Api POST / '{"action":"version","version":6,"key":"test-key-123"}'
  Api POST / '{"action":"version","version":6,"key":"wrong"}'
  Api POST / '{"action":"deckNames","version":4,"key":"test-key-123"}'
  curl.exe -s -X POST $T/ @K -d "not json"
  ```

  → `{"result":6,"error":null}`; `{"result":null,"error":"valid api key
  must be provided"}`; a **bare** name array (version ≤ 4 has no
  envelope); an error envelope — **never** a 422 body.

  The remaining commands omit `"key"` for brevity — the `X-Api-Key` header
  in `$H` covers them.
- [ ] Reads:

  ```powershell
  Api POST / '{"action":"deckNames","version":6}'
  Api POST / '{"action":"modelNames","version":6}'
  Api POST / '{"action":"findNotes","version":6,"params":{"query":"deck:TestSuite"}}'
  Api POST / '{"action":"findCards","version":6,"params":{"query":"deck:TestSuite"}}'
  Api POST / (@{action="notesInfo";      version=6; params=@{notes=@($nid)}}  | ConvertTo-Json -Depth 3)
  Api POST / '{"action":"notesInfo","version":6,"params":{"query":"deck:*"}}'
  Api POST / (@{action="cardsInfo";      version=6; params=@{cards=@($cid1,$cid2)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="getEaseFactors"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="areDue";         version=6; params=@{cards=@($cid1,$cid2)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="getIntervals";   version=6; params=@{cards=@($cid2); complete=$true}} | ConvertTo-Json -Depth 3)
  ```

  → all answer; the broad `notesInfo` by query may be slow but must not
  503.
- [ ] Writes:

  ```powershell
  Api POST / '{"action":"createDeck","version":6,"params":{"deck":"TestSuite::Shim"}}'
  Api POST / '{"action":"addNote","version":6,"params":{"note":{"deckName":"TestSuite::Shim","modelName":"Basic","fields":{"Front":"shim-note","Back":"1"},"options":{"allowDuplicate":false},"tags":["shim"]}}}'
  Api POST / '{"action":"addNote","version":6,"params":{"note":{"deckName":"TestSuite::Shim","modelName":"Basic","fields":{"Front":"shim-note","Back":"2"},"options":{"allowDuplicate":false}}}}'
  Api POST / (@{action="updateNoteFields"; version=6; params=@{note=@{id=$nid; fields=@{Back="shim-edited"}}}} | ConvertTo-Json -Depth 4)
  Api POST / (@{action="suspend";   version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="suspend";   version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)   # again -> result: false
  Api POST / (@{action="unsuspend"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)   # -> result: null (canonical quirk)
  Api POST / (@{action="forgetCards";  version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="relearnCards"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="setDueDate";   version=6; params=@{cards=@($cid1); days="2"}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="setEaseFactors"; version=6; params=@{cards=@($cid1); easeFactors=@(2400)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="changeDeck";   version=6; params=@{cards=@($cid1); deck="TestSuite"}} | ConvertTo-Json -Depth 3)
  ```

  → second `addNote` errors with canonical's duplicate message; the rest
  match the annotated expectations.
- [ ] The three newest actions, quirks verbatim:

  ```powershell
  Api POST / (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid1; ease=3},@{cardId=123; ease=3})}} | ConvertTo-Json -Depth 4)
  Api POST / (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid1; ease=9})}} | ConvertTo-Json -Depth 4)
  Api POST / '{"action":"setSpecificValueOfCard","version":6,"params":{"card":[1,2],"keys":["factor"],"newValues":[2600]}}'
  Api POST / (@{action="setSpecificValueOfCard"; version=6; params=@{card=$cid1; keys=@("due"); newValues=@(0)}} | ConvertTo-Json -Depth 3)
  Api POST / (@{action="setSpecificValueOfCard"; version=6; params=@{card=$cid1; keys=@("due"); newValues=@(0); warning_check=$true}} | ConvertTo-Json -Depth 3)
  Api POST / '{"action":"setSpecificValueOfCard","version":6,"params":{"card":123,"keys":["factor"],"newValues":[2600],"warning_check":true}}'
  $now2 = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
  Api POST / (@{action="insertReviews"; version=6; params=@{reviews=@(,@($now2, $cid1, -1, 3, 1, 0, 2500, 3000, 0))}} | ConvertTo-Json -Depth 4)
  ```

  → `[true, false]`; error `"invalid ease"` (the true answer before it
  kept); bare `false`; bare `false` (risky key, no warning_check);
  `[true]`; `[[false, "..."]]`; `null` with the row landed
  (`Api GET "/v1/reviews?where=id==$now2"`).
- [ ] `multi` — per-action results in order, one failure isolated:

  ```powershell
  Api POST / '{"action":"multi","version":6,"params":{"actions":[{"action":"version"},{"action":"bogusAction"},{"action":"deckNames"}]}}'
  ```

  → `result` is a 3-array: `6`, an `"unsupported action"` entry, the deck
  names.
- [ ] Compat GUI set behaves like suite 12:

  ```powershell
  Api POST / '{"action":"guiBrowse","version":6,"params":{"query":"deck:TestSuite"}}'
  Api POST / '{"action":"guiDeckReview","version":6,"params":{"name":"TestSuite"}}'
  Api POST / '{"action":"guiCurrentCard","version":6}'
  Api POST / '{"action":"guiShowAnswer","version":6}'
  Api POST / '{"action":"guiAnswerCard","version":6,"params":{"ease":3}}'
  ```

- [ ] Collection/media compat:

  ```powershell
  Api POST / '{"action":"getProfiles","version":6}'
  Api POST / '{"action":"exportPackage","version":6,"params":{"deck":"TestSuite","path":"C:\\Users\\Public\\ts-shim-export.apkg"}}'
  Api POST / '{"action":"importPackage","version":6,"params":{"path":"C:\\Users\\Public\\ts-shim-export.apkg"}}'
  Api POST / '{"action":"storeMediaFile","version":6,"params":{"filename":"shim.txt","data":"c2hpbQ=="}}'
  Api POST / '{"action":"getMediaFilesNames","version":6,"params":{"pattern":"shim*"}}'
  Api POST / '{"action":"retrieveMediaFile","version":6,"params":{"filename":"shim.txt"}}'
  Api POST / '{"action":"deleteMediaFile","version":6,"params":{"filename":"shim.txt"}}'
  Api POST / '{"action":"sync","version":6}'
  ```

  → each in canonical shape (`retrieveMediaFile` → the base64,
  `deleteMediaFile` → null; `sync` only with AnkiWeb configured).
- [ ] Reflection + unknown action:

  ```powershell
  Api POST / '{"action":"apiReflect","version":6,"params":{"scopes":["actions"]}}'
  Api POST / '{"action":"noSuchAction","version":6}'
  ```

  → action list; `{"result":null,"error":"unsupported action"}`.

## 16. Shim — real clients (the drop-in proof)

AnkiConnect (the real addon) **disabled** throughout.

- [ ] **Yomitan** pointed at Tsunagi's port: card creation from a lookup
  works end-to-end incl. audio/media; duplicate detection behaves.
- [ ] **Asbplayer**: mining a card and updating the last card's media.
- [ ] **Yomine** (your pipeline): add note via Tsunagi → Asbplayer patches
  media by note id → Yomine sees `op {origin:"api", note_ids:[...]}` on
  the stream and matches it. No client config changed except the port.

## 17. Performance spot checks (real collection, read-only)

Switch to your real profile. Compare `stats.duration_ms`:

- [ ] Keyset listings — low single-digit ms for the id walk (was: a
  whole-collection scan per page):

  ```powershell
  $p1 = Api GET "/v1/cards?limit=100";  $p1.stats
  (Api GET "/v1/cards?limit=100&cursor=$($p1.next_cursor)").stats
  (Api GET "/v1/notes?limit=100").stats
  (Api GET "/v1/reviews?limit=100").stats
  ```

- [ ] Two-phase filtered scan — quick despite touching every row (no
  renders for rejected rows):

  ```powershell
  (Api GET "/v1/cards?where=queue==-1&limit=50").stats
  ```

- [ ] Narrow vs full hydration — visible gap (renders/scheduling skipped):

  ```powershell
  (Api GET "/v1/cards?select=id,due&limit=200").stats
  (Api GET "/v1/cards?limit=200").stats
  ```

- [ ] A 10-op `cards:batch` on real cards (suspend/unsuspend pairs are
  safe) → one round trip, one undo entry.
- [ ] Shim deck lookups — instant, no due-tree pass:

  ```powershell
  Api POST / '{"action":"deckNamesAndIds","version":6}'
  Api POST / '{"action":"deckNameFromId","version":6,"params":{"deckId":1}}'
  ```

## 18. Errors & busy behaviour

- [ ] Unknown ids:

  ```powershell
  Api GET "/v1/notes?where=id==1"
  Api DELETE /v1/decks/999999999
  Api PATCH /v1/notes/999999999 '{"fields":{"Front":"x"}}'
  ```

  → empty 200 list; HTTP 404; HTTP 404.
- [ ] Malformed inputs:

  ```powershell
  Api GET "/v1/cards?search=%22unbalanced"
  Api GET "/v1/cards?where=nonsense"
  curl.exe -s -o NUL -w "%{http_code}`n" @K -X POST $T/v1/decks -H "Content-Type: application/json" -d "nope"
  ```

  → HTTP 400 with Anki's search error; HTTP 400 with the where-DSL help;
  `422` (native routes may 422 — only `POST /` never does).
- [ ] **Busy**: open a modal dialog in Anki (e.g. any deck's Options), then:

  ```powershell
  Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  ```

  → HTTP 503 within the op timeout (~15s), not a hang; close the dialog →
  the same command succeeds.
- [ ] Kill Anki with the event stream open and a client polling → clients
  get connection errors, then clean service after a normal restart; no
  port squatting.

---

When every suite is initialled: `git push` is the only thing left.

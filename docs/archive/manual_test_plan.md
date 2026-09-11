# Tsunagi — full manual test plan

> [!NOTE]
> Historical record from the initial compatibility and routing audits. Counts,
> commands, screenshots and API details describe that checkpoint, not the current
> release. Start with the [current documentation](../README.md).

Every surface a user can reach: 101 native routes, 122 AnkiConnect actions,
the settings dialog, the event stream, and the server lifecycle. Each item is
a checkbox with an exact copy-paste command and an expected result. Automated
tests already pin wire shapes and call counts — this plan is for the things
only a real Anki can prove: visible UI effects, undo, timing on a real
collection, and drop-in behaviour with real clients.

> **Status:** suites 1–6 signed off (the suite‑3/4 findings — redoc bundle,
> `GET /v1/collection` — are fixed and re-verified; the suite‑6 Browser
> observation is stock Anki, see known-cosmetics). Suites 7+ commands now
> bake in output formatting — paste the `J` filter from suite 7 (or the
> setup block) before continuing. No re-sync needed; the installed build
> is current.

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

  filter J { $_ | ConvertTo-Json -Depth 8 }
  ```

  Usage: `Api GET /v1/health`, `Api POST /v1/decks '{"name":"X"}'`.
  PowerShell's default table view truncates wide objects at `…`, so the
  commands bake in the right display: `Api ... | J` prints the full JSON
  body, `(...).items | Select-Object <fields> | Format-Table` shows just
  the columns a check verifies, and `(...).items | Format-List *` prints
  every field of every row without truncation. Bodies that embed a
  captured variable are built with hashtables + `ConvertTo-Json` — that
  sidesteps every PowerShell quoting difference. `curl.exe` (not the
  `curl` alias) is used only where streaming or raw headers matter.
- "Envelope" = `{items, next_cursor, stats}` for lists, `{result, error}`
  for `POST /`.
- Known-cosmetic (expected, don't fail the run): deck browser may repaint
  only on window focus after some GUI actions; `gui:exit` with the Add Cards
  window open logs a traceback while quitting; a **created** note doesn't
  appear in an open Browser until its search re-runs (stock Anki — the row
  list is never re-searched on an op; edits/deletes of *existing* rows
  repaint instantly).

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
- [x] Switch profile away and back → server stops and restarts cleanly; no
  "thread did not stop" in the console; port rebinds. **No
  vendored-module warning for Anki's own `app_packages`** (attr, click,
  idna, …) — that's expected environment now, filtered out. A warning
  naming a path under `addons21\<other-addon>` is still real and worth
  noting.
- [x] Debug console (Ctrl+Shift+;):

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
- [x] CORS — the default allowlist entry `http://localhost` also covers
  `127.0.0.1` origins and browser extensions (AnkiConnect's exact
  semantics; it's why Yomitan needs zero setup). So test with an origin
  that is genuinely unlisted:

  ```powershell
  curl.exe -si $T/v1/decks @K -H "Origin: https://evil.example" | Select-Object -First 1
  curl.exe -si $T/v1/decks @K -H "Origin: http://localhost" | Select-String "HTTP|Access-Control"
  ```

  → first: `403` (body "Disallowed CORS origin"); second: `200` with
  `Access-Control-Allow-Origin: http://localhost`.
- [x] Preflight:

  ```powershell
  curl.exe -si -X OPTIONS $T/v1/decks -H "Origin: https://evil.example" -H "Access-Control-Request-Method: GET" | Select-Object -First 1
  curl.exe -si -X OPTIONS $T/v1/decks -H "Origin: http://localhost" -H "Access-Control-Request-Method: GET" | Select-Object -First 1
  ```

  → `403`, then `200`.
- [x] `POST /` stays reachable from any origin so clients can *ask* for
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
- [x] `requestPermission` with no Origin header (a local script) → granted
  without any dialog:

  ```powershell
  Api POST / '{"action":"requestPermission","version":6}'
  ```

  → `{"result": {"permission": "granted", "requireApikey": true, "version": 6}, "error": null}`.

## 3. Discovery surfaces

- [x] `(Api GET /actions).actions.Count` → **122**.
- [x] `curl.exe -si $T/ | Select-Object -First 5` → a redirect
  (`307`) with `location: /docs`.
- [x] Open `http://127.0.0.1:7777/docs` in a browser → Swagger UI renders;
  spot-open a few routes and check the descriptions read sensibly.
- [x] `http://127.0.0.1:7777/redoc` renders. (Was broken: FastAPI's default
  page loads `redoc@next` from jsdelivr, which now serves the restructured
  redoc 3 alpha and gets MIME-blocked. Fixed by pinning the page to
  `redoc@2` — re-check after re-syncing the addon.)
- [x] ⟳ OpenAPI sanity — **97** operations after the `GET /v1/collection`
  addition (the 101 live routes minus the four docs/schema routes, which
  FastAPI serves outside the schema):

  ```powershell
  $spec = Api GET /openapi.json
  ($spec.paths.PSObject.Properties | ForEach-Object { $_.Value.PSObject.Properties.Name }).Count
  ```

  → `97`.

## 4. Decks & deck-configs

- [x] Create (capture the id) — parent `TestSuite` auto-created; both decks
  visible in Anki's deck list **immediately**, no click needed:

  ```powershell
  $deck = Api POST /v1/decks '{"name":"TestSuite::Sub"}'   # CAPTURE
  $sub = $deck.result.id
  ```

  → HTTP 201, `$sub` is a numeric id.
- [x] List, then the narrow fast path (compare `stats.duration_ms` — the
  narrow one skips the scheduler's due-tree pass):

  ```powershell
  (Api GET /v1/decks).items | Select-Object name, new_count, review_count
  (Api GET "/v1/decks?select=id,name&shape=object").stats
  ```

- [x] Rename + describe — deck list updates live:

  ```powershell
  Api PATCH /v1/decks/$sub '{"name":"TestSuite::Renamed","description":"manual test deck"}'
  ```

- [x] FSRS retention override (26.08 supports it): set, read back, clear:

  ```powershell
  Api PATCH /v1/decks/$sub '{"desired_retention":0.85}'
  (Api GET /v1/decks).items | Where-Object { $_.id -eq $sub } | Select-Object name, desired_retention
  Api PATCH /v1/decks/$sub '{"desired_retention":null}'
  ```

  → reads back `0.85`, then null after clearing.
- [x] Delete the subdeck; the default deck refuses:

  ```powershell
  Api DELETE /v1/decks/$sub
  Api DELETE /v1/decks/1
  ```

  → `success: true` then HTTP 400.
- [x] Deck-configs — clone the default, patch a value, verify in Anki's
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

  > **Answered (was: "how do we test if a deck is using FSRS?"):** FSRS
  > on/off is neither per-deck nor per-preset — it's one collection-wide
  > switch (Anki's deck-options screen hosts the toggle, but it flips the
  > scheduler for the whole collection). That's why `desired_retention`
  > reads back a value with FSRS off: the retention numbers are stored
  > either way, the scheduler just ignores them until the switch is on.
  > The flag is now exposed at `GET /v1/collection` — checked below.
- [x] Collection meta — the FSRS switch and Anki version:

  ```powershell
  Api GET /v1/collection
  ```

  → `{fsrs: false, anki_version: "26.8", ...}` on a fresh profile; toggle
  FSRS on in any deck's Options → re-run → `fsrs: true` (and suite 7's
  full card rows will start showing `memory_state`/`retrievability` once
  cards are reviewed under it).

## 5. Models (+ fields/templates)

- [x] Create; appears in Tools → Manage Note Types. Re-running the same
  create → HTTP 400 (duplicate name):

  ```powershell
  $model = Api POST /v1/models '{"name":"TSModel","fields":[{"name":"F"},{"name":"B"}],"templates":[{"name":"Card 1","qfmt":"{{F}}","afmt":"{{F}}<hr>{{B}}"}]}'   # CAPTURE
  $mid = $model.result.id
  Api POST /v1/models '{"name":"TSModel","fields":[{"name":"F"}],"templates":[{"name":"Card 1","qfmt":"{{F}}","afmt":"{{F}}"}]}'
  ```

- [x] Cloze model (`type: 1` — needed by suite 6):

  ```powershell
  $cloze = Api POST /v1/models '{"name":"TSCloze","type":1,"fields":[{"name":"Text"}],"templates":[{"name":"Cloze","qfmt":"{{cloze:Text}}","afmt":"{{cloze:Text}}"}]}'   # CAPTURE
  ```

- [x] `(Api GET /v1/models).items.Count` (full rows) and
  `Api GET "/v1/models?select=id,name"` (fast path) both list TSModel.
- [x] `Api PATCH /v1/models/$mid '{"css":".card { color: navy; }"}'` →
  visible in the card template editor's Styling tab.
- [x] Fields — full cycle, checking Anki's Fields… editor after each
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
- [x] Templates — same cycle:

  ```powershell
  Api POST /v1/models/$mid/templates '{"name":"Card 2","qfmt":"{{B}}","afmt":"{{F}}"}'
  Api PATCH "/v1/models/$mid/templates/Card 2" '{"qfmt":"{{B}}?"}'
  Api PUT /v1/models/$mid/templates:order '{"order":["Card 2","Card 1"]}'
  Api DELETE "/v1/models/$mid/templates/Card 2"
  Api DELETE "/v1/models/$mid/templates/Card 1"
  ```

  → all 200 until the last delete → HTTP 400 (last template).
- [x] Find-replace in templates:

  ```powershell
  Api POST /v1/models:find-replace '{"find":"<hr>","replace":"<hr id=answer>","modelName":"TSModel"}'
  ```

  → `affected: 1`; the template's back side changed in the editor.
- [x] `Api DELETE /v1/models/$mid` (no notes on it) → gone from the manage
  list. **Keep TSCloze** — suite 6 uses it.

## 6. Notes

- [x] Create — with Anki's **Browser open**:

  ```powershell
  $n1 = Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"dog"},"tags":["ts"]}'   # CAPTURE
  $nid = $n1.result.id
  ```

  > **Observed: new note needs a reclick to appear — that's stock Anki.**
  > The Browser's row list is the result of the last search and is never
  > re-run on an operation; `op_executed` (aqt table.py) only redraws
  > *existing* rows. So edits/deletes repaint instantly (their rows exist)
  > but a created note is invisible until the search re-runs — exactly the
  > same as adding via Anki's own Add dialog with the Browser open.

  → HTTP 201; `$n1.result.cards` holds the generated card id(s).
- [x] Duplicate handling — same Front again:

  ```powershell
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"x"}}'
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"x"},"allowDuplicate":true}'
  ```

  → HTTP 409 naming the duplicate note id(s); then HTTP 201. Delete the
  duplicate: `Api DELETE /v1/notes/<its id>`.

  ** Counter point to above, delete will immediately show in UI **
- [x] Validation: empty first field, and a cloze note with no `{{c1::}}`:

  ```powershell
  Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"","Back":"x"}}'
  Api POST /v1/notes '{"modelName":"TSCloze","deckName":"TestSuite","fields":{"Text":"no cloze here"}}'
  ```

  → both HTTP 400.
- [x] Reads:

  ```powershell
  Api GET "/v1/notes?limit=5"
  Api GET "/v1/notes?search=tag:ts"
  Api GET "/v1/notes?where=id==$nid"
  ```
	PS H:\Documents\Dev\Anki Addons\Tsunagi> Api GET "/v1/notes?limit=5"
HTTP 200

items
-----
{@{id=1634251759190; guid=AiRwDGzkZJ; model_id=1714404065052; model_name=Kaishi 1.5k; mod=1714404138…

PS H:\Documents\Dev\Anki Addons\Tsunagi> Api GET "/v1/notes?search=tag:ts"
HTTP 200

items
-----
{@{id=1786223679020; guid=HSqr?gdp`c; model_id=1783565347129; model_name=Basic; mod=1786223679; usn=…

PS H:\Documents\Dev\Anki Addons\Tsunagi> Api GET "/v1/notes?where=id==$nid"
HTTP 200

items
-----
{@{id=1786223679020; guid=HSqr?gdp`c; model_id=1783565347129; model_name=Basic; mod=1786223679; usn=…

  → each row carries its `cards` ids; the search/where forms return
  exactly the seeded note.
- [x] Patch fields and tags — Browser shows each edit live:

  ```powershell
  Api PATCH /v1/notes/$nid '{"fields":{"Back":"DOG"}}'
  Api PATCH /v1/notes/$nid '{"addTags":["ts-added"]}'
  Api PATCH /v1/notes/$nid '{"removeTags":["ts-added"]}'
  Api PATCH /v1/notes/$nid '{"tags":["x"],"addTags":["y"]}'
  ```

	** all worked and instant in the UI **
  → first three 200; the combined form → HTTP 400.
- [x] Retype (scratch note, since retyping is destructive to fields):

  ```powershell
  $n2 = Api POST /v1/notes '{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"retype-me","Back":"z"}}'   # CAPTURE
  Api PATCH "/v1/notes/$($n2.result.id)" '{"modelName":"TSCloze"}'
  Api PATCH "/v1/notes/$($n2.result.id)" '{"modelName":"TSCloze","fields":{"Text":"{{c1::tsunagi}}"}}'
  ```

  → without `fields` HTTP 400 (would blank the note); with them, 200 and
  the Browser shows it as a TSCloze note.
- [x] `notes:check` — verdicts only, nothing created (note count in the
  Browser unchanged):

  ```powershell
  Api POST /v1/notes:check '{"notes":[{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"brand-new","Back":"1"}},{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"tsunagi-front-1","Back":"dup"}},{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"","Back":""}}]}'
  ```

  → `results` states: `normal`, `duplicate` (with `duplicate_note_ids`),
  `empty`.
- [x] `Api DELETE "/v1/notes/$($n2.result.id)"` → its cards vanish from the
  Browser immediately.

## 7. Cards — reads

Paste this display helper first — `J` prints a full, never-truncated JSON
body (PowerShell's default table view cuts wide objects off at `…`):

```powershell
filter J { $_ | ConvertTo-Json -Depth 8 }
```

Pattern for the rest of the run: `Api ... | J` for a whole body,
`(...).items | Select-Object <fields> | Format-Table` when only a few
columns matter, `(...).items | Format-List *` for every field of every row.

- [x] Seed six more notes, then capture three card ids: `# CAPTURE`

  ```powershell
  1..6 | ForEach-Object { Api POST /v1/notes ('{"modelName":"Basic","deckName":"TestSuite","fields":{"Front":"card-seed-' + $_ + '","Back":"b"},"tags":["seed"]}') | Out-Null }
  $cards = (Api GET "/v1/cards?search=deck:TestSuite&select=id&shape=object&limit=100").items
  $cid1 = $cards[0].id; $cid2 = $cards[1].id; $cid3 = $cards[2].id
  "cid1=$cid1  cid2=$cid2  cid3=$cid3"
  ```

  → three numeric ids print.
- [x] Cursor walk — ids per page, then the cursor itself:

  ```powershell
  $p1 = Api GET "/v1/cards?limit=5"
  $p2 = Api GET "/v1/cards?limit=5&cursor=$($p1.next_cursor)"
  $p1.items.id
  $p2.items.id
  $p1.next_cursor
  ```

  → two blocks of 5 ids with no overlap; keep following `next_cursor`
  until it comes back empty — the total equals your card count.
- [x] Anki search syntax:

  ```powershell
  (Api GET "/v1/cards?search=deck:TestSuite%20is:new").items | Select-Object id, deck_name, type, queue | Format-Table
  ```

  → only the seeded TestSuite cards, `type: 0` (new).
- [x] Where DSL (suspend one card first so the filter has a hit):

  Re-verified 2026-09-06 on `[DEV] Yomine`: scope the query to TestSuite.
  The seven other suspended cards belong to Kaishi 1.5k and Mining, so
  the original collection-wide result of eight was correct. The scoped
  query returned only card `1786223679020` with `queue: -1` and
  `suspended: true`; unsuspending affected one card and the scoped query
  then returned no items. Browser updated on window focus, accepted for
  this run. Original observation retained below for context.

  ```powershell
  Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  (Api GET "/v1/cards?search=deck:TestSuite&where=queue==-1").items | Select-Object id, queue, suspended | Format-Table
  Api POST /v1/cards:unsuspend (@{cardIds=@($cid1)} | ConvertTo-Json)
  ```
	PS H:\Documents\Dev\Anki Addons\Tsunagi> (Api GET "/v1/cards?where=queue==-1").items | Select-Object id, queue, suspended | Format-Table
HTTP 200

           id queue suspended
           -- ----- ---------
1711551717546    -1      True
1724856098432    -1      True
1730312496931    -1      True
1733860184510    -1      True
1737603559746    -1      True
1740625635027    -1      True
1765158806210    -1      True
1786223679020    -1      True

All came back suspended? But in UI I can see the only 1 is suspended
  → exactly the suspended card: `queue: -1`, `suspended: True`.

- [x] Narrow vs full rows — compare the durations, then inspect one full
  row:

  ```powershell
  (Api GET "/v1/cards?select=id,due,queue&shape=object&limit=50").stats | J
  (Api GET "/v1/cards?limit=50").stats | J
  (Api GET "/v1/cards?where=id==$cid2").items[0] | J
  ```

  → the narrow read is visibly faster; the full row shows
  `question`/`answer` HTML, `next_reviews`, and (on a reviewed card with
  FSRS on) `memory_state`/`retrievability`.
- [x] Index tier:

  ```powershell
  (Api GET "/v1/cards?where=note_id==$nid").items | Select-Object id, note_id, ord, deck_name | Format-Table
  ```

  → that note's card(s), `note_id` matching `$nid`.
- [x] GET/POST parity — the two `items` blocks print identically:

  ```powershell
  Api POST /v1/cards/query '{"select":"id,due","shape":"object","limit":5}' | J
  Api GET "/v1/cards?select=id,due&shape=object&limit=5" | J
  ```

## 8. Cards — writes

Keep the Browser open on `deck:TestSuite` the whole suite — every verb
should repaint it **without clicking**. Verb responses are small
(`{affected, stats}`) — the default view already shows `affected`; add
`| J` any time you want the full body.

- [x] Verbs, one at a time (each → HTTP 200 with an `affected` count):

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

- [x] Answer — the card advances, a revlog row appears; a suspended card is
  unsuspended by answering; ease 5 fails validation:

  Verified 2026-09-06 on `[DEV] Yomine`: card `1786225501336` moved from
  new to learning, reps 0 to 1, with one ease-3 review entry. User confirmed
  the Browser Due value updated immediately without a click. Card
  `1786225501352` was verified suspended, then answering with ease 3
  cleared suspension and moved it to learning. Ease 5 returned HTTP 422;
  the first card's scheduling values and single review entry were unchanged.

  ```powershell
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid2; ease=3})} | ConvertTo-Json -Depth 3)
  (Api GET "/v1/reviews?where=card_id==$cid2").items | Select-Object id, card_id, ease, interval, type | Format-Table
  Api POST /v1/cards:suspend (@{cardIds=@($cid3)} | ConvertTo-Json)
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid3; ease=3})} | ConvertTo-Json -Depth 3)
  (Api GET "/v1/cards?where=id==$cid3").items[0].suspended
  Api POST /v1/cards:answer (@{answers=@(@{cardId=$cid2; ease=5})} | ConvertTo-Json -Depth 3) | J
  ```

  → a review row with `ease: 3`; then `suspended` prints `False`; the
  ease-5 call → HTTP 422 with the validation detail.
- [x] Raw column writes — plain column fine, scheduling column needs
  `force`:

  Verified 2026-09-06 on `[DEV] Yomine`, card `1786225501336`:
  factor 2700 returned HTTP 200 and persisted; reps 99 without force
  returned HTTP 400 naming reps and left reps at 1; with force it returned
  HTTP 200 and persisted reps 99. Restored and read back the original
  factor 0 and reps 1 after the check.

  ```powershell
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{factor=2700}} | ConvertTo-Json)
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{reps=99}} | ConvertTo-Json) | J
  Api POST /v1/cards:set-values (@{cardId=$cid2; values=@{reps=99}; force=$true} | ConvertTo-Json)
  ```

  → 200, then HTTP 400 naming the risky column (full message via `J`),
  then 200.
- [x] Gate check — `:set-memory-state` → HTTP 400 until you enable its gate
  in the settings dialog; after enabling (no restart) it works:

  Verified 2026-09-06 on `[DEV] Yomine`, card `1786225501336`: disabled
  gate returned HTTP 400 naming `gates.cards_set_memory_state`, with
  memory state unchanged. After enabling in Settings without restarting,
  the same request returned HTTP 200, affected 1; readback showed stability
  5.0 and difficulty 3.200000047683716 (float storage rounding). Restored
  and verified original stability 2.30649995803833 and difficulty
  2.118000030517578. User confirmed the gate was disabled again afterward.

  ```powershell
  Api POST /v1/cards:set-memory-state (@{cards=@(@{id=$cid2; memory_state=@{stability=5.0; difficulty=3.2}})} | ConvertTo-Json -Depth 4) | J
  ```

- [x] **Batch** — one op, ONE undo entry (`J` shows the per-op `results`
  array the default view hides):

  Verified 2026-09-06 on `[DEV] Yomine`: HTTP 200, affected 3, with
  three per-op results each affected 1. User invoked Undo once and saw
  the blue flag disappear. API comparison against pre-batch snapshots
  confirmed all three cards' scheduling, suspension, flags and memory
  state restored. In particular, `1786223679020` returned to queue 0,
  unsuspended, retaining its pre-existing orange flag; `1786225501336`
  returned to learning with due 1788729171; `1786225501352` returned to
  flag 0. Invalid-only `suspennd` request returned HTTP 400 listing valid
  operations, with the target card still unsuspended. This invalid-only
  check does not establish rollback of a partially executed mixed batch.

  ```powershell
  Api POST /v1/cards:batch (@{operations=@(
    @{op="suspend";      cardIds=@($cid1)},
    @{op="set-due-date"; cardIds=@($cid2); days="3"},
    @{op="set-flag";     cardIds=@($cid3); flag=4}
  )} | ConvertTo-Json -Depth 4) | J
  ```

  → `results` has three entries with per-op `affected`; Anki's Edit menu
  shows a single **Undo Card Batch**; **one Ctrl+Z reverts all three**.
  Then the all-or-nothing check:

  ```powershell
  Api POST /v1/cards:batch '{"operations":[{"op":"suspennd","cardIds":[1]}]}' | J
  ```

  → HTTP 400 listing the valid op names, and nothing was applied.

## 9. Reviews & tags

- [x] Reads — the review columns, not a truncated blob:

  Verified 2026-09-06 on `[DEV] Yomine`: first five reviews returned
  expected columns in ascending id order; all seven TestSuite reviews
  belonged to card ids independently fetched from TestSuite. First 100
  rows of the ease-3 filter all had ease 3 and ascending ids (further
  pages not checked).

  ```powershell
  (Api GET "/v1/reviews?limit=5").items | Select-Object id, card_id, ease, interval, factor, type | Format-Table
  (Api GET "/v1/reviews?search=deck:TestSuite").items | Select-Object id, card_id, ease | Format-Table
  (Api GET "/v1/reviews?where=ease==3").items | Select-Object id, card_id, ease | Format-Table
  ```

  → rows in review order (`id` is the review's epoch-ms timestamp); the
  search form returns only reviews of TestSuite cards; the where form
  only `ease: 3` rows.
- [x] Insert (history import) — both rows land atomically, and the **undo
  history is cleared** (expected: raw revlog write, Anki's own dbproxy
  behaviour):

  Verified 2026-09-06 on `[DEV] Yomine`: inserted review ids
  1788729794335 and 1788729794336 for card 1786225501336; HTTP 200,
  inserted 2, with both rows read back. Repeating the same payload returned
  HTTP 500, "Insert reviews failed", and the three existing rows remained
  unchanged with no duplicates. User confirmed "Undo Edit Card" became
  disabled. This duplicate-only check does not prove rollback when a new
  row precedes a conflicting row in the same request.

  ```powershell
  $now = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()   # CAPTURE
  Api POST /v1/reviews (@{reviews=@(
    @{id=$now;     card_id=$cid2; ease=3; interval=1; last_interval=0; factor=2500; time_ms=4000; type=0},
    @{id=($now+1); card_id=$cid2; ease=4; interval=3; last_interval=1; factor=2500; time_ms=2500; type=1}
  )} | ConvertTo-Json -Depth 3)
  (Api GET "/v1/reviews?where=card_id==$cid2").items | Select-Object id, card_id, ease, interval | Format-Table
  ```

  → `inserted: 2`; both new rows (ids `$now` and `$now+1`) in the table.
  Re-running the same insert (same ids) → an error response and
  **neither** row duplicated — the transaction rolls back, `inserted` is
  never partial.
- [x] Tags:

  Verified 2026-09-06 on `[DEV] Yomine`, note 1786223679020:
  bulk-add returned HTTP 200, affected 1; note and prefix list included
  ts-bulk, and user confirmed it appeared in the sidebar. Rename returned
  HTTP 200, affected 1; note and prefix list replaced ts-bulk with
  ts-bulk2. User confirmed sidebar rename appeared on window focus.
  Bulk-remove returned HTTP 200, affected 1; note tags restored to [ts].
  User confirmed the note's Tags field showed only ts. Clear-unused
  returned HTTP 200, affected 2; prefix list now contains only ts, with
  ts-added and ts-bulk2 removed. Note still has [ts]. User confirmed
  both unused tags disappeared from the Browser sidebar.

  ```powershell
  (Api GET /v1/tags).items
  (Api GET "/v1/tags?prefix=ts").items
  Api POST /v1/tags:bulk-add (@{noteIds=@($nid); tags="ts-bulk"} | ConvertTo-Json)
  Api PATCH /v1/tags/ts-bulk '{"name":"ts-bulk2"}'
  Api POST /v1/tags:bulk-remove (@{noteIds=@($nid); tags="ts-bulk2"} | ConvertTo-Json)
  Api POST /v1/tags:clear-unused
  ```

  → tag names print as plain lists; each write's `affected` ≥ 1 except
  the final clear-unused (whatever was left); the Browser's tag sidebar
  tracks every step.

## 10. Media

- [x] Base64 upload, then the same name again → stored under a new name:

  Verified 2026-09-06 on `[DEV] Yomine`: both uploads returned HTTP 201,
  size 13. First stored ts.txt with renamed false; second stored
  ts-fc436fef492fd917ec8ffae16c74013d8181af95.txt with renamed true.
  Downloads returned text/plain and preserved distinct contents:
  "hello tsunagi" and "other content". Deleted the renamed file and
  confirmed HTTP 404; ts.txt retained for the later list/delete check.

  ```powershell
  Api POST /v1/media '{"filename":"ts.txt","data":"aGVsbG8gdHN1bmFnaQ=="}' | J
  Api POST /v1/media '{"filename":"ts.txt","data":"b3RoZXIgY29udGVudA=="}' | J
  ```

  → first `{filename: "ts.txt", renamed: false}`; second `renamed: true`
  with a different stored `filename` (delete that one after checking).
- [x] URL fetch:

  Verified 2026-09-06 on `[DEV] Yomine`: checklist URL imported as
  ts-readme.md, HTTP 201, renamed false, size 7966. Download returned
  HTTP 200 with a nonempty body and Content-Length 7966. Retained for
  the later media listing and cleanup check.

  ```powershell
  Api POST /v1/media '{"url":"https://raw.githubusercontent.com/mcgrizzz/Tsunagi/main/README.md","filename":"ts-readme.md"}' | J
  ```

  → 201 with `size` > 0.
- [x] Local-path gate:

  Verified 2026-09-06 on `[DEV] Yomine` using a uniquely named text file
  in Windows Temp (tsunagi-local-3363f97ec6474410a172d4b1cdf6365a.txt).
  Disabled gate returned HTTP 400 naming gates.media_allow_local_path;
  media listing confirmed no file created. After user enabled and saved
  without restarting, the identical import returned HTTP 201, size 15.
  Download returned HTTP 200, text/plain, exact content "hello from disk".
  Gate reset verified by repeating the import and receiving the disabled-
  gate HTTP 400. Imported file deleted and confirmed HTTP 404; temporary
  source file removed from Windows Temp.

  ```powershell
  Set-Content C:\Users\Public\ts-local.txt "hello from disk"
  Api POST /v1/media '{"path":"C:\\Users\\Public\\ts-local.txt"}' | J
  ```

  → HTTP 400 while `media_allow_local_path` is off; enable it in the
  settings dialog (no restart) → re-run → 201.
- [x] List, download (real Content-Type), delete, confirm gone:

  Verified 2026-09-06 on `[DEV] Yomine`: prefix listing included all
  three uploads with filename, size and mtime. ts.txt download previously
  returned HTTP 200, text/plain, exact content "hello tsunagi". Deleted
  ts.txt, ts-readme.md and the uniquely named local-path upload; each
  returned HTTP 200, success true, followed by HTTP 404 on download.

  ```powershell
  (Api GET "/v1/media?prefix=ts").items | Format-Table
  curl.exe -si @K "$T/v1/media/ts.txt" | Select-String "HTTP|Content-Type"
  Api DELETE /v1/media/ts.txt
  curl.exe -s -o NUL -w "%{http_code}`n" @K "$T/v1/media/ts.txt"
  ```

  → the uploads as filename/size/mtime rows; download `200` +
  `text/plain`; delete `success: true`; final GET `404`.
- [x] Traversal refused, nothing written:

  Verified 2026-09-06: GET with --path-as-is to
  /v1/media/..%2Fcollection.anki2 returned HTTP 400,
  "filename must not contain path separators".

  ```powershell
  curl.exe -s -o NUL -w "%{http_code}`n" @K "$T/v1/media/..%2Fcollection.anki2"
  ```

  → `400`.

## 11. FSRS & jobs

FSRS optimization needs review history. With sparse history, Anki 23.10
reports a failed job with an insufficient-history error; newer Anki can
return done with empty params and fsrs_items 0. Either is an expected
version-dependent result; empty params are not a trained model. For real
numbers, re-run this suite against your real collection: compute/evaluate
only *return* parameters, they write nothing.

- [x] Submit → poll (`J` shows the nested `progress`/`result`):

  Observed 2026-09-06 on `[DEV] Yomine`: submitting deck:TestSuite
  returned HTTP 202, job c1c9c3132560, status queued. Poll returned
  HTTP 200, status done, result {params: [], fsrs_items: 0,
  health_check_passed: null}, error null. Submission/polling worked,
  but no usable parameters were produced and no not-enough-reviews
  error was reported. Confirmed this matches the adapter's deliberate
  passthrough and existing test_sparse_history_reports_done_with_empty_params
  test for newer Anki. Checklist expectation corrected; running/progress
  was not observed before this small job completed. Existing test inspected,
  not rerun in this environment.

  Broader-history retest on the same test profile: job 6ca5095d4267
  returned HTTP 202, was observed running, then done with 21 finite
  parameters and fsrs_items 211593, error null. Successful computation
  verified; the empty TestSuite result above is also expected for this
  Anki version's sparse-history path.

  ```powershell
  $job = Api POST /v1/fsrs:compute-params '{"search":"deck:TestSuite"}'   # CAPTURE
  Api GET "/v1/jobs/$($job.job_id)" | J
  ```

  → HTTP 202 with `job_id`; polls show `queued`/`running` (with progress),
  then `done` with `result.params`. On sparse history, expect `failed`
  with an insufficient-history `error` on Anki 23.10, or `done` with
  `result.params: []` and `result.fsrs_items: 0` on newer Anki. Only
  nonempty computed parameters are used in the evaluation check below.
- [x] Abort:

  Verified 2026-09-06 on `[DEV] Yomine`: collection-wide computation
  returned HTTP 202, job b754177b6c36, queued. Immediate abort returned
  HTTP 200 with status running while cancellation was pending; the next
  poll returned status aborted, error "Interrupted", result null.

  ```powershell
  $job2 = Api POST /v1/fsrs:compute-params '{}'
  Api POST "/v1/jobs/$($job2.job_id):abort" | J
  ```

  → status ends `aborted` (poll once more if it was mid-transition).
- [x] One-job rule: submit two computes back-to-back → the second is
  rejected or queued per the rule, never interleaved garbage.

  Verified 2026-09-06 on `[DEV] Yomine`: first submission returned
  HTTP 202, job 8915b5f600d7; second returned HTTP 409 naming the
  already-running job. Poll showed running with progress current 710524,
  total 1658224. Aborted the accepted job after the check and confirmed
  its terminal status was aborted; the error explained that computation
  had already finished and its result was discarded.
- [x] Synchronous endpoints (supply explicit simulation limits; on a real
  collection compare against Anki's own FSRS optimizer output):

  Observed 2026-09-06 on `[DEV] Yomine`: all three requests returned
  HTTP 200. Simulation returned four numeric arrays of length 30;
  daily_review_count, daily_new_count and daily_time_cost were all zero.
  Workload returned cost/memorized/review_count maps for retentions 70–99,
  but costs and review counts were all zero and memorized values identical.
  Optimal retention returned 0.9367321133613586, within (0, 1).
  Confirmed the schema defaults deck_size, new_limit, review_limit and
  max_interval to zero and passes them directly to Anki. The zero-workload
  result came from the checklist's omitted limits. Retest with the explicit
  body below returned HTTP 200 for all three endpoints, four length-30
  arrays with nonzero activity, positive workload costs/review counts for
  every retention 70–99, and retention 0.9367321133613586. This signs off
  functional output checks, not numerical agreement with Anki's UI.

  ```powershell
  $simBody = '{"days_to_simulate":30,"deck_size":100,"new_limit":10,"review_limit":100,"max_interval":36500,"desired_retention":0.9,"search":"deck:TestSuite"}'
  $sim = Api POST /v1/fsrs:simulate $simBody
  $sim.daily_review_count
  $sim.daily_new_count
  Api POST /v1/fsrs:simulate-workload $simBody | J
  Api POST /v1/fsrs:optimal-retention $simBody | J
  ```

  → two 30-number arrays print in full; the workload maps and a
  `retention` in (0, 1) as JSON.
- [x] Evaluate with the computed params (real collection):

  Verified 2026-09-06 using the broader review history already present
  in `[DEV] Yomine`; no profile switch. Submitted the 21 parameters from
  job 6ca5095d4267. Evaluation returned HTTP 202, job 8fae703883a3;
  observed running with progress 44032/211590, then done, error null,
  log_loss 0.4507100582122803 and rmse_bins 0.031009767204523087.
  Parameters were not applied to deck settings.

  ```powershell
  $done = Api GET "/v1/jobs/$($job.job_id)"
  $eval = Api POST /v1/fsrs:evaluate-params (@{params=$done.result.params} | ConvertTo-Json -Depth 3)
  Api GET "/v1/jobs/$($eval.job_id)" | J
  ```

  → 202 + a job that finishes with log-loss/RMSE numbers.

## 12. GUI routes

Each produces its visible effect and returns cleanly. Responses are small —
the default view is enough except where marked.

- [x] `Api POST /v1/gui:browse '{"query":"deck:TestSuite"}'` → Browser opens
  filtered; response carries the matching `card_ids` (print them all with
  `(Api POST /v1/gui:browse '{"query":"deck:TestSuite"}').card_ids`).
  Verified 2026-09-06: HTTP 200 with seven matching card ids; user
  confirmed Browser opened/came forward with deck:TestSuite and seven cards.
- [x] `Api POST /v1/gui:select-card (@{card_id=$cid2} | ConvertTo-Json)` →
  the row highlights. Select a few rows by hand, then
  `(Api GET /v1/gui/selected-notes).note_ids` → their note ids print.
  Verified 2026-09-06: select-card returned HTTP 200, ok true;
  selected-notes initially returned only 1786225501336 (card-seed-1).
  After user selected card-seed-1 and card-seed-2 together, selected-notes
  returned exactly [1786225501336, 1786225501352].
- [x] `Api POST /v1/gui:edit-note (@{note_id=$nid} | ConvertTo-Json)` → the
  target note is available for editing.
  Verified 2026-09-06 on Anki 26.08.1: HTTP 200, ok true. User confirmed
  Front tsunagi-front-1 and Back DOG in the Browser's editor sidebar,
  not a separate dialog. No field changes made.
- [x] Add Cards dialog:

  Verified 2026-09-06 on `[DEV] Yomine`: add-cards returned HTTP 200,
  note_id 0; user confirmed TestSuite / Basic, Front "from gui:add-cards",
  Back "x". set-add-note-data with append true returned HTTP 200,
  ok true; user confirmed Back became "xappended" and Front stayed
  unchanged. Add was not clicked; user confirmed the Add Cards window
  was closed afterward.

  ```powershell
  Api POST /v1/gui:add-cards '{"deckName":"TestSuite","modelName":"Basic","fields":{"Front":"from gui:add-cards","Back":"x"}}'
  Api POST /v1/gui:set-add-note-data '{"fields":{"Back":"appended"},"append":true}'
  ```

  → dialog opens pre-filled; the second call updates the open dialog's
  fields.
- [x] Navigation: `Api POST /v1/gui:deck-browser`, then
  `Api POST /v1/gui:deck-overview '{"name":"TestSuite"}'`, then
  `Api POST /v1/gui:deck-review '{"name":"TestSuite"}'` → lands **directly
  in the reviewer** (make sure TestSuite has due/new cards; suite 8's
  forget left some new).
  Verified 2026-09-06: all three routes returned HTTP 200, ok true.
  User confirmed overview -> deck list (rerun from a distinct starting
  screen), deck list -> TestSuite overview, and overview -> reviewer
  question with Show Answer. current-card returned review_active true,
  card.card_id 1786225501336, Front card-seed-1, deck TestSuite.
- [x] Reviewer flow by API only (`J` on current-card shows the nested card):

  In progress 2026-09-06: current-card identified card-seed-1
  (1786225501336); show-answer returned HTTP 200 and user confirmed
  Back b with rating buttons. answer-card ease 3 returned HTTP 200;
  current-card changed to card-seed-2 (1786225501352), and user confirmed
  its question side. After Undo and another show-answer, show-question
  returned HTTP 200; user confirmed Back b was hidden and Show Answer
  was visible again. start-card-timer returned HTTP 200, ok true; elapsed
  timer behavior not independently measured; timer endpoint smoke check only.
  Temporary audio fixture created: deck TestSuite::AudioCheck
  (1788752557678), note/card 1788752557964, media
  tsunagi-audio-check-20260906.wav (quiet half-second 440 Hz tone).
  Sound was on the answer side. User heard automatic playback after
  show-answer and saw the play button. Explicit play-audio returned
  HTTP 200, ok true; user confirmed hearing the tone replay without
  clicking. Left reviewer and deleted fixture note, empty subdeck and
  media; all three deletes returned success. Filtered note/deck list
  reads returned no items; media download returned 404. Direct GET by
  note/deck id is unsupported (405), so list filters verified removal.
  Cleared the unused fixture tag afterward.

  ```powershell
  Api GET /v1/gui/current-card | J
  Api POST /v1/gui:show-answer
  Api POST /v1/gui:answer-card '{"ease":3}'
  Api GET /v1/gui/current-card | J
  ```

  → question shown → answer shown → the second current-card is a
  different `card.card_id`.
  Also: `Api POST /v1/gui:show-question`, `Api POST /v1/gui:start-card-timer`,
  and `Api POST /v1/gui:play-audio` on a card with `[sound:...]`.
- [x] `Api POST /v1/gui:undo` → undoes the reviewer answer (Anki shows its
  undo toast).
  In progress 2026-09-06: HTTP 200, ok true; card-seed-1 review history
  returned to its three pre-answer entries. Immediate current-card read
  still reported card-seed-2, but a later poll returned card-seed-1,
  confirming an asynchronous reviewer transition. User confirmed
  card-seed-1 returned and the undo notification appeared.
- [x] `Api POST /v1/gui:import-file '{"path":"C:\\Users\\Public\\ts-export.apkg"}'`
  → Anki's import flow opens (run after suite 13 creates the file).
  Verified 2026-09-06 with the temporary package from suite 13:
  HTTP 200, ok true; user confirmed an import screen opened, then closed
  it without importing again.
- [ ] LAST, if you want: `Api POST /v1/gui:exit` quits Anki
  (known-cosmetic traceback if Add Cards is open).

## 13. Collection & profiles (destructive-ish — do late)

- [x] Export → file exists → import it back (dupes skipped per Anki rules):

  Verified 2026-09-06 on `[DEV] Yomine`: exported TestSuite to
  C:\Users\Andrew\AppData\Local\Temp\tsunagi-export-a2e24429104340f6b7b68049217a0317.apkg.
  HTTP 200, success true; file exists, 57201 bytes, ZIP opens and contains
  meta, collection.anki21b, collection.anki2 and media. Import returned
  HTTP 200, imported 0, updated 0. All seven TestSuite card/note id pairs
  unchanged afterward. User confirmed main window stayed unchanged.
  Adapter inspection confirms this route calls collection import directly
  and returns counts without opening an import summary. Package retained
  for suite 12's separate GUI import check; after user closed that screen,
  the temporary package was removed and its absence verified.

  ```powershell
  Api POST /v1/collection:export '{"deck":"TestSuite","path":"C:\\Users\\Public\\ts-export.apkg"}'
  Test-Path C:\Users\Public\ts-export.apkg
  Api POST /v1/collection:import '{"path":"C:\\Users\\Public\\ts-export.apkg"}' | J
  ```

  → `success: true`; `True`; import prints its `imported`/`updated`
  counts. This collection API does not open a summary window; test the
  visible import flow separately with suite 12's gui:import-file route.
- [x] `Api POST /v1/collection:check-database` → `success: true`, Anki
  stays healthy. `Api POST /v1/collection:reload` → collection reopens
  (deck list flickers/refreshes).
  Verified 2026-09-06: check-database returned HTTP 200,
  success true. User reported "Added last review time to 1 card.
  Database rebuilt and optimized." User dismissed the result popup.
  Reload returned HTTP 200, success true; health ok, active profile still
  [DEV] Yomine and all seven TestSuite card/note id pairs unchanged.
  User confirmed Anki remained responsive with no error popups.
- [ ] Optional, with AnkiWeb configured: `Api POST /v1/collection:sync | J`
  → sync runs; watch suite 14's `sync started/finished` + `reset` events
  while it does.
- [x] Profiles — list, switch away and back. The server restarts during
  switching: requests may receive 503 or a connection interruption;
  reconnect and confirm the active profile before continuing.

  In progress 2026-09-06: user authorized Tsunagi as a second disposable
  profile. POST profiles:load from [DEV] Yomine to Tsunagi completed with
  HTTP 500, plain-text "Internal Server Error". A concurrent profiles
  probe encountered connection refusal during restart; later GET profiles
  returned HTTP 200, active Tsunagi. The switch succeeded despite the
  initiating request failing. Keep open as a lifecycle/response issue;
  User screenshots confirmed Tsunagi loaded while the Profiles dialog
  remained open, still highlighting [DEV] Yomine. Adapter inspection:
  visible-main-window branch calls unloadProfileAndShowProfileManager,
  then loads the target in a timer callback without closeWithoutQuitting;
  that close exists only in the initially-hidden-window branch. Profile
  close also invokes stop_server, explaining the listener outage; the
  exact HTTP 500 cause still needs a traceback or focused reproduction.
  Reproduction after user closed the dialog: initial GET reported active
  [DEV] Yomine; same-profile load returned HTTP 200, loaded true. Retried
  [DEV] Yomine -> Tsunagi: again HTTP 500, followed by HTTP 200 from
  profiles with active Tsunagi. Repeat UI confirmation pending; leave
  any Profiles dialog open. Controlled return-switch test still pending.

  Fix prepared 2026-09-07: defer profile switching to the next Qt event
  loop turn so call_on_main releases the requesting HTTP handler before
  profile-close server draining, and close the Profiles dialog after
  loading the target in either branch. API description now documents
  acceptance versus completion and restart connection interruptions.
  Five new regression cases cover deferred unloading, delayed unload,
  manager-only switching and unknown/current profile no-ops. Validation
  on Python 3.10 / Anki 23.10: 837 passed, 8 skipped; Ruff passed.
  Installed source synced and user reloaded the add-on. First live retest:
  Tsunagi -> [DEV] Yomine returned HTTP 200, loaded true (previously 500).
  Follow-up profiles read returned HTTP 200, active [DEV] Yomine; all
  seven TestSuite cards remain accessible. User confirmed the Profiles
  dialog closed automatically. Reverse retest [DEV] Yomine -> Tsunagi
  also returned HTTP 200, loaded true; follow-up profiles read confirmed
  active Tsunagi. User confirmed no leftover dialog in that direction
  either. Returned to [DEV] Yomine with HTTP 200; confirmed active profile
  and all seven TestSuite cards. Profile switching passed in both
  directions after the fix on Anki 26.08.1.

  ```powershell
  $profs = Api GET /v1/profiles   # CAPTURE
  $profs | J
  $other = $profs.items | Where-Object { $_ -ne $profs.active } | Select-Object -First 1
  Api POST /v1/profiles:load (@{name=$other} | ConvertTo-Json)
  ```

  → every profile name plus which is `active`; then Anki switches (server
  restarts with it — re-run the load with your original profile's name to
  come back).

## 14. Event stream

Terminal A (leave running — curl prints each event as it arrives, nothing
to format):

```powershell
curl.exe -N "$T/v1/events?api_key=test-key-123"
```

Trigger from terminal B / the Anki UI:

- [x] Connect: `retry:` preamble + `: connected`; `: ping` about every 15s.
  Verified 2026-09-07: HTTP 200, text/event-stream, retry: 3000 and
  : connected on opening. A 20-second stream emitted : ping, then
  close {"reason":"timeout"} and exited cleanly (curl exit 0).
- [x] Review a card in Anki's reviewer → `review {card_id, ease}` then
  `op {origin:"ui", changes:[...card, study_queues...]}` with a label.
  Verified 2026-09-07: user answered one card Good in Anki. Stream
  emitted review seq 1, card_id 1786225501336, ease 3, followed by
  op seq 2, origin ui, label "Answer Card", changes including card,
  deck, mtime, browser_table, browser_sidebar and study_queues.
- [x] Type in Anki's note editor and let the edit save → UI `op`, label
  "Update Note". Observe Anki's save granularity rather than requiring
  one event per keystroke.
  Verified 2026-09-07: user typed 123 normally after DOG; API readback
  confirmed DOG123. Captured one op (seq 3), origin ui, label Update Note,
  changes note, mtime, browser_table and note_text. This run did not emit
  one event per character. User restored DOG; API readback confirmed it,
  and the stream emitted a second UI Update Note event (seq 4).
- [x] API write: `Api POST /v1/cards:suspend (@{cardIds=@($cid1)} | ConvertTo-Json)`
  → `op {origin:"api", card_ids:[...], label:"Suspend"}`. A note patch
  carries `note_ids`; a deck patch carries `deck_ids`.
  In progress 2026-09-07: suspend returned HTTP 200, affected 1, and
  exactly one op (seq 5), origin api, label Suspend,
  card_ids [1786223679020]. Cleanup unsuspend affected 1 and emitted
  one op (seq 6), origin api, label Unbury/Unsuspend, same card_ids.
  Readback confirmed queue 0, suspended false. Note patch emitted one
  Update Note op (seq 7), origin api, note_ids [1786223679020]. Deck
  description patch emitted one Update Deck op (seq 8), origin api,
  deck_ids [1786219820315]. Restoring both produced corresponding ops
  seq 9/10; independent reads confirmed Back DOG and empty description.
- [x] `cards:batch` (suite 8's three-op body) → **one** `op`, label
  "Card Batch", the union of the card ids.
  Verified 2026-09-07: fresh stream captured exactly one op (seq 11),
  origin api, label Card Batch, card_ids
  [1786223679020,1786225501336,1786225501352]; response affected 3 with
  three per-op affected counts of 1. API Undo returned HTTP 200; all
  three cards' saved scheduling, suspension, flag and memory values
  matched the pre-batch snapshots afterward. Separate follow-up finding:
  the undo op (seq 12) had origin null and label Update Deck despite
  reverting Card Batch. Diagnosed 2026-09-07: the hook reads the next
  undoable action's label after undo, not the action just reversed. Fix
  omits this unreliable label when handler is None, retaining origin null
  and change flags. Identified API/UI operations retain their labels.
  Added regression coverage; 52 targeted event/GUI tests passed, Ruff
  and code diff checks passed. Installed source synced and user reloaded.
  Live retest passed: suspension emitted one origin-api op with label
  Suspend and the correct card_ids; Undo emitted one origin-null op with
  change flags and no label. Independent readback matched the pre-test
  card scheduling/flag/memory values, with suspended false. Incorrect
  undo-label finding resolved.
- [x] Shim write: `Api POST / (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid2; ease=3})}} | ConvertTo-Json -Depth 4)`
  → `op {origin:"api", card_ids}` and **no** `review` event (that hook is
  reviewer-only).
  Verified 2026-09-07: keyed answerCards call returned HTTP 200,
  result [true], error null. One op (seq 13), origin api, label Answer
  Card, card_ids [1786225501336]; no review event during capture. One
  new ease-3 review row was saved. API Undo restored the saved card
  scheduling/memory values and exactly the original four review rows.
  Undo metadata issue reproduced: seq 14, origin null, label Update Deck.
- [ ] Sync (if configured) → `sync started`, `sync finished`, then `reset`.
- [x] Change the API key in the settings dialog mid-stream → stream ends
  with `close {"reason":"auth"}`. (Change it back, restart terminal A.)
  Verified 2026-09-07: fresh stream connected using test-key-123; user
  changed and saved test-key-456. Old stream emitted close reason auth
  and exited cleanly. Old header key returned HTTP 401, new header key
  returned HTTP 200. Fresh stream with new key connected and ended with
  timeout after two seconds. User restored test-key-123; profiles returned
  HTTP 200 with that key, and a fresh event stream connected successfully.
- [x] `tsunagi.reload_addon()` in the debug console (or a profile switch)
  with the stream open → `close {"reason":"shutdown"}`, port rebinds,
  reconnect works, and events arrive **exactly once** (no duplicate
  hooks).
  In progress 2026-09-07: initial capture reached its 590-second timeout
  before user reload, so shutdown reason was not tested. After reload,
  health and reconnect returned HTTP 200; a 15-second capture saw exactly
  one Suspend op for one API write, no duplicate. Card was unsuspended
  afterward and verified. Opened a replacement stream without server-side
  timeout (client cap two hours). On the repeated reload, captured close
  reason shutdown and clean stream exit. Health/reconnect returned HTTP
  200; a fresh 10-second capture contained exactly one Suspend op for
  one write (seq 1), then timeout close. Cleanup unsuspend succeeded;
  readback confirmed queue 0 and suspended false.
- [x] Script ergonomics — both close themselves with their reason:

  Verified 2026-09-07: timeout=2 connected with HTTP 200, then emitted
  close reason timeout and exited 0 after about two seconds. max_events=1
  connected with HTTP 200; one suspension produced exactly one op, then
  close reason max_events and exit 0. Cleanup unsuspend returned affected
  1, with readback confirming queue 0 and suspended false.

  ```powershell
  curl.exe -N "$T/v1/events?api_key=test-key-123&timeout=2"
  curl.exe -N "$T/v1/events?api_key=test-key-123&max_events=1"
  ```

- [x] Browser check: from a page on an allowlisted origin,
  `new EventSource("http://127.0.0.1:7777/v1/events?api_key=test-key-123")`
  → events visible in DevTools' Network → EventStream tab.
  Verified 2026-09-07 from http://localhost:7777/docs: user created an
  EventSource for /v1/events?api_key=test-key-123 and confirmed connected.
  One API suspension returned affected 1; user confirmed Console received
  an op with origin api, label Suspend, card_ids [1786223679020].
  Verified through the Console listener; EventStream-tab inspection was
  optional and not separately confirmed. Cleanup unsuspend affected 1;
  readback queue 0, suspended false. User confirmed Browser EventSource
  was closed afterward.

## 15. AnkiConnect shim — protocol

All through `POST /`. With a key set, the shim takes it as the body `"key"`
field; an X-Api-Key header alone is not accepted by the shim. Every command
below pipes through `J` — the `{result, error}` envelope is exactly what
each check inspects, and the default table view mangles array results.

- [x] Envelope + key handling:

  Verified 2026-09-07: valid body key returned HTTP 200, result 6,
  error null; wrong body key returned the canonical key error envelope.
  Version 4 deckNames returned a bare name array. Malformed JSON returned
  HTTP 200 with error "request body is not valid JSON", not HTTP 422.
  Header-only version request returned the key error; corrected the
  checklist's mistaken header-auth claim.

  ```powershell
  Api POST / '{"action":"version","version":6,"key":"test-key-123"}' | J
  Api POST / '{"action":"version","version":6,"key":"wrong"}' | J
  Api POST / '{"action":"deckNames","version":4,"key":"test-key-123"}' | J
  curl.exe -s -X POST $T/ @K -d "not json"
  ```

  → `{"result":6,"error":null}`; `{"result":null,"error":"valid api key
  must be provided"}`; a **bare** name array (version ≤ 4 has no
  envelope); an error envelope — **never** a 422 body.

  Paste this helper before the remaining checks. It adds the body key
  while preserving any explicit key in a request (including negative tests):

  ```powershell
  function Rpc {
    param([string]$Body)
    $request = $Body | ConvertFrom-Json
    if (-not $request.PSObject.Properties['key']) {
      $request | Add-Member -NotePropertyName key -NotePropertyValue 'test-key-123'
    }
    Api POST / ($request | ConvertTo-Json -Depth 12)
  }
  ```
- [x] Reads:

  Verified 2026-09-07 with body key: deckNames, modelNames, findNotes,
  findCards, notesInfo, cardsInfo, getEaseFactors, areDue and getIntervals
  returned error null. TestSuite findNotes/findCards each returned the
  expected seven ids; note fields were tsunagi-front-1 / DOG; cardsInfo
  returned the requested two TestSuite cards; ease factors [2600],
  due flags [true,false], complete intervals [[-600,1,3,2]]. Broad
  notesInfo query deck:* returned HTTP 200, about 59.9 MB in 1.68 seconds;
  parsed response contained 4543 notes and error null. Temporary capture
  removed afterward.

  ```powershell
  Rpc '{"action":"deckNames","version":6}' | J
  Rpc '{"action":"modelNames","version":6}' | J
  Rpc '{"action":"findNotes","version":6,"params":{"query":"deck:TestSuite"}}' | J
  Rpc '{"action":"findCards","version":6,"params":{"query":"deck:TestSuite"}}' | J
  Rpc (@{action="notesInfo";      version=6; params=@{notes=@($nid)}}  | ConvertTo-Json -Depth 3) | J
  Rpc '{"action":"notesInfo","version":6,"params":{"query":"deck:*"}}' | Out-Null   # broad: slow ok, 503 NOT ok
  Rpc (@{action="cardsInfo";      version=6; params=@{cards=@($cid1,$cid2)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="getEaseFactors"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="areDue";         version=6; params=@{cards=@($cid1,$cid2)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="getIntervals";   version=6; params=@{cards=@($cid2); complete=$true}} | ConvertTo-Json -Depth 3) | J
  ```

  → all answer with `error: null`; the broad `notesInfo` prints only
  `HTTP 200` (body discarded — the check is that it answers at all).
- [x] Writes:

  In progress 2026-09-07: createDeck created TestSuite::Shim, id
  1788796638769. addNote created note/card 1788796639073, Front shim-note,
  Back 1, tag shim. Both returned HTTP 200, numeric result, error null.
  Duplicate Front with allowDuplicate false returned result null and
  "cannot create note because it is a duplicate". Readback confirmed
  exactly one note in the subdeck, with original Back 1. Use this
  temporary note/card for subsequent writes; fixture cleanup pending.
  updateNoteFields returned result null, error null; notesInfo confirmed
  Back shim-edited. First suspend returned true and native readback showed
  queue -1, suspended true. Second suspend returned false. Unsuspend
  returned null (canonical shape); readback queue 0, suspended false.
  All calls returned HTTP 200. Scheduling/deck tests also returned 200
  and error null: forgetCards result null, readback queue/type 0/0;
  relearnCards result null, queue/type 1/3; setDueDate days 2 result true,
  queue/type 2/2, due 63; setEaseFactors result [true], factor 2400;
  changeDeck result null, readback deck TestSuite. Temporary card now
  lives in TestSuite, with TestSuite::Shim empty; retain for action-quirk
  tests, then delete fixture note/card and empty subdeck.

  ```powershell
  Rpc '{"action":"createDeck","version":6,"params":{"deck":"TestSuite::Shim"}}' | J
  Rpc '{"action":"addNote","version":6,"params":{"note":{"deckName":"TestSuite::Shim","modelName":"Basic","fields":{"Front":"shim-note","Back":"1"},"options":{"allowDuplicate":false},"tags":["shim"]}}}' | J
  Rpc '{"action":"addNote","version":6,"params":{"note":{"deckName":"TestSuite::Shim","modelName":"Basic","fields":{"Front":"shim-note","Back":"2"},"options":{"allowDuplicate":false}}}}' | J
  Rpc (@{action="updateNoteFields"; version=6; params=@{note=@{id=$nid; fields=@{Back="shim-edited"}}}} | ConvertTo-Json -Depth 4) | J
  Rpc (@{action="suspend";   version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="suspend";   version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J   # again -> result: false
  Rpc (@{action="unsuspend"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J   # -> result: null (canonical quirk)
  Rpc (@{action="forgetCards";  version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="relearnCards"; version=6; params=@{cards=@($cid1)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="setDueDate";   version=6; params=@{cards=@($cid1); days="2"}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="setEaseFactors"; version=6; params=@{cards=@($cid1); easeFactors=@(2400)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="changeDeck";   version=6; params=@{cards=@($cid1); deck="TestSuite"}} | ConvertTo-Json -Depth 3) | J
  ```

  → second `addNote` errors with canonical's duplicate message; the rest
  match the inline annotations.
- [x] The three newest actions, quirks verbatim:

  ```powershell
  Rpc (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid1; ease=3},@{cardId=123; ease=3})}} | ConvertTo-Json -Depth 4) | J
  Rpc (@{action="answerCards"; version=6; params=@{answers=@(@{cardId=$cid1; ease=9})}} | ConvertTo-Json -Depth 4) | J
  Rpc '{"action":"setSpecificValueOfCard","version":6,"params":{"card":[1,2],"keys":["factor"],"newValues":[2600]}}' | J
  Rpc (@{action="setSpecificValueOfCard"; version=6; params=@{card=$cid1; keys=@("reps"); newValues=@(5)}} | ConvertTo-Json -Depth 3) | J
  Rpc (@{action="setSpecificValueOfCard"; version=6; params=@{card=$cid1; keys=@("reps"); newValues=@(5); warning_check=$true}} | ConvertTo-Json -Depth 3) | J
  Rpc '{"action":"setSpecificValueOfCard","version":6,"params":{"card":123,"keys":["factor"],"newValues":[2600],"warning_check":true}}' | J
  $now2 = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
  Rpc (@{action="insertReviews"; version=6; params=@{reviews=@(,@($now2, $cid1, -1, 3, 1, 0, 2500, 3000, 0))}} | ConvertTo-Json -Depth 4) | J
  (Api GET "/v1/reviews?where=id==$now2").items | Select-Object id, card_id, ease | Format-Table
  ```

  → in order: `result: [true, false]`; error `"invalid ease"` (the true
  answer before it kept); `result: false`; `result: false` (risky key, no
  warning_check); `result: [true]`; `result: [[false, "..."]]`;
  `result: null` — and the final read shows the inserted row landed.

  Live verified 2026-09-07 on disposable shim card `1788796639073`: all
  result shapes above passed. Corrected the guarded-field probe from `due`
  (not guarded) to `reps`. Omitted and explicit false `warning_check` both
  returned false and kept reps at 1; true returned `[true]` and readback
  showed reps 5. Missing card 123 returned nested false with a message.
  Inserted review `1788797478685` was read back with the expected values.

- [x] `multi` — per-action results in order, one failure isolated:

  ```powershell
  Rpc '{"action":"multi","version":6,"params":{"actions":[{"action":"version","key":"test-key-123"},{"action":"bogusAction","key":"test-key-123"},{"action":"deckNames","key":"test-key-123"}]}}' | J
  ```

  → `result` is a 3-array: `6`, an `"unsupported action"` entry, the deck
  names.
  Live verified 2026-09-07: HTTP 200, outer error null, ordered results
  `6`, `{result: null, error: "unsupported action"}`, and the deck names.
  Each nested action needs its own body key when authentication is enabled;
  the outer key alone produced three per-action authentication errors.

- [x] Compat GUI set behaves like suite 12:

  ```powershell
  Rpc '{"action":"guiBrowse","version":6,"params":{"query":"deck:TestSuite"}}' | J
  Rpc '{"action":"guiDeckReview","version":6,"params":{"name":"TestSuite"}}' | J
  Rpc '{"action":"guiCurrentCard","version":6}' | J
  Rpc '{"action":"guiShowAnswer","version":6}' | J
  Rpc '{"action":"guiAnswerCard","version":6,"params":{"ease":3}}' | J
  ```

  Live verified 2026-09-07: Browse showed `deck:TestSuite` and eight cards.
  Deck review opened `card-seed-2`; current-card data matched the screen.
  Show Answer revealed `b` and review buttons. Answering Good returned
  true and advanced to `tsunagi-front-1`; user undid once and confirmed
  return to `card-seed-2`.

- [x] Collection/media compat (optional sync excluded):

  ```powershell
  Rpc '{"action":"getProfiles","version":6}' | J
  Rpc '{"action":"exportPackage","version":6,"params":{"deck":"TestSuite","path":"C:\\Users\\Public\\ts-shim-export.apkg"}}' | J
  Rpc '{"action":"importPackage","version":6,"params":{"path":"C:\\Users\\Public\\ts-shim-export.apkg"}}' | J
  Rpc '{"action":"storeMediaFile","version":6,"params":{"filename":"shim.txt","data":"c2hpbQ=="}}' | J
  Rpc '{"action":"getMediaFilesNames","version":6,"params":{"pattern":"shim*"}}' | J
  Rpc '{"action":"retrieveMediaFile","version":6,"params":{"filename":"shim.txt"}}' | J
  Rpc '{"action":"deleteMediaFile","version":6,"params":{"filename":"shim.txt"}}' | J
  ```

  → each in canonical shape (`retrieveMediaFile` → the base64 `c2hpbQ==`,
  `deleteMediaFile` → null; `sync` only with AnkiWeb configured).
  Live verification 2026-09-07: `getProfiles` returned all five
  profiles with error null. Media round trip passed: `shim.txt` was absent
  before creation; store returned the filename, listing included it,
  retrieval returned `c2hpbQ==`, deletion returned null, and the final
  listing was empty. Export and import each returned true with error null.
  Export produced a valid 57,349-byte package; after import, all eight card
  IDs matched the pre-export list. The temporary package was removed.

- [ ] Optional shim sync (only with AnkiWeb configured; not run):

  ```powershell
  Rpc '{"action":"sync","version":6}' | J
  ```

- [x] Reflection + unknown action:

  ```powershell
  Rpc '{"action":"apiReflect","version":6,"params":{"scopes":["actions"]}}' | J
  Rpc '{"action":"noSuchAction","version":6}' | J
  ```

  → the full action list; `{"result":null,"error":"unsupported action"}`.
  Live verified 2026-09-07: reflection returned scope `actions` and 122
  action names with error null. `noSuchAction` returned exactly
  `{ "result": null, "error": "unsupported action" }`.


## 16. Shim — real clients (the drop-in proof)

AnkiConnect (the real addon) **disabled** throughout.

- [x] **Yomitan** pointed at Tsunagi's port: card creation from a lookup
  works end-to-end incl. audio/media; duplicate detection behaves.

  Live verified 2026-09-07 using the existing Yomitan settings and Mining
  destination in `[DEV] Yomine`. User created 船首, note/card
  `1788801318673` (Kiku). Readback confirmed reading せんしゅ, definitions,
  sentence, and expression audio; referenced MP3 retrieved successfully
  (10,508 bytes). User confirmed playback in Anki and Yomitan marking the
  word already mined on another lookup. Test note retained for client tests.

- [x] **Asbplayer**: mining a card and updating the last card's media.

  Partial live verification 2026-09-07: update-last-card passed on 船首
  note/card `1788801318673`. SentenceAudio and Picture were added to that
  same note; the referenced MP3 (86,976 bytes) and JPEG (143,895 bytes)
  were retrievable. User confirmed screenshot display and sentence audio
  playback in Anki. Standalone Export also created 椅子席 in Mining,
  note/card `1788803402613` (Kiku), after the user corrected a setting
  following an empty-note validation error. Readback confirmed Expression,
  sentence, furigana, source information, sentence MP3 (78,336 bytes), and
  screenshot JPEG (158,467 bytes); both media files were retrievable.
  User confirmed screenshot display and sentence audio playback for this
  newly exported card in Anki.

- [x] **Yomine** (your pipeline): add note via Tsunagi → Asbplayer patches
  media → Yomine recognizes and matches the update.

  Live verified 2026-09-07 with the API key disabled by the user because
  Yomine does not yet support API keys. User confirmed 日本 was recognized
  and the workflow completed. Readback verified note/card `1788803735014`
  in Mining, `[DEV] Yomine`, with Expression 日本, sentence, sentence audio
  (75,456 bytes), and screenshot (233,622 bytes); both files retrieved
  successfully. This verifies the observed client workflow; the exact event
  payload and note-targeting request were not captured during this run.
  Follow-up for Yomine: API-key support for requests and event connections;
  authenticated client integration remains untested.

## 17. Performance spot checks

Use a populated disposable test profile. Listings below are read-only;
the separate batch check writes card state and needs Undo verification.
Every listing command prints total route `duration_ms`, which includes dispatch,
hydration, filtering, and projection; it does not isolate the ID query or include
all HTTP response serialization/client overhead. Record at least three runs and
report median/range, collection size, installed revision, and whether Anki is
foreground, background, or minimized. Compare before/after in the same state.

- [ ] Keyset listings — verify bounded ID queries and hydration on both pages
  with instrumentation; record total route and ID-query timings separately.
  A fast route time alone does not prove that the ID walk is bounded:

  ```powershell
  $p1 = Api GET "/v1/cards?limit=100"
  $p1.stats.duration_ms
  (Api GET "/v1/cards?limit=100&cursor=$($p1.next_cursor)").stats.duration_ms
  (Api GET "/v1/notes?limit=100").stats.duration_ms
  (Api GET "/v1/reviews?limit=100").stats.duration_ms
  ```

- [x] Two-phase filtered scan — verify complete results, including late matches,
  and zero renders for rejected rows. Record scanned rows, operation counts,
  worker time, scheduling waits, and total route median/range. Compare full and
  narrow selection, and separately compare Anki `search=is:suspended` without
  assuming that Anki search and the where DSL have identical semantics:

  ```powershell
  (Api GET "/v1/cards?where=queue==-1&limit=50").stats.duration_ms
  (Api GET "/v1/cards?where=queue==-1&select=id,queue&limit=50").stats.duration_ms
  (Api GET "/v1/cards?search=is:suspended&select=id,queue&limit=50").stats.duration_ms
  ```

- [x] Narrow vs full hydration — visible gap (renders/scheduling skipped):

  ```powershell
  (Api GET "/v1/cards?select=id,due&limit=200").stats.duration_ms
  (Api GET "/v1/cards?limit=200").stats.duration_ms
  ```

- [x] A 10-op `cards:batch` on a disposable card → one round trip, one
  undo entry. Live verified 2026-09-07: five suspend/unsuspend pairs on
  shim card `1788796639073`, all ten affected counts 1, HTTP 200,
  server duration 16.976 ms. Queue/type/due/reps/flags matched before and
  after. User saw Undo Card Batch; one Undo changed the label to
  Undo Update Note. Post-Undo state also matched the original snapshot.
- [x] Shim deck lookups — successful, responsive lookup:

  ```powershell
  Api POST / '{"action":"deckNamesAndIds","version":6}' | J
  Api POST / '{"action":"deckNameFromId","version":6,"params":{"deckId":1}}' | J
  ```

  Live measurements 2026-09-07 on populated `[DEV] Yomine` (API key off):
  card pages 1/2: 138.905/139.758 ms; notes: 74.899 ms; reviews: 67.407 ms.
  ID-only card page: 68.514 ms. These are total route timings, not isolated
  ID-walk timings; the stated single-digit target is not demonstrated.
  Narrow/full 200-card results: 75.853/205.839 ms (about 2.7x faster narrow).
  Suspended-card scan returned seven cards in 11,516.677 ms; a narrow
  `select=id,queue` repeat took 11,448.664 ms. Filtered-scan performance
  remains an unresolved issue; full rendering does not explain this delay.
  Shim deck lookups returned expected results with error null, about
  250 ms wall time including Windows curl startup. The 10-op batch passed as recorded above.

  Investigation baseline, later 2026-09-07: same installed routing/card/dispatch
  files as the workspace, Anki 26.08.1, `[DEV] Yomine`, 4,547 cards/notes,
  minimized (confirmed by user). Three narrow suspended scans: median
  329.485 ms, range 299.553–339.682; full scans: median 383.020 ms, range
  336.077–396.868. Native suspended search: median 1.419 ms, range
  1.295–1.562, same seven results. ID-only 100-card page: median 7.779 ms,
  range 7.369–8.510. Narrow scan with limit 250 (larger internal batches):
  median 305.640 ms, range 300.110–305.829. Windows curl adds roughly
  250–275 ms wall time. The earlier 11.5-second delay has not yet reproduced;
  do not attribute the difference to a code fix.

  Phase profiling identified per-card object/model construction and dictionary
  conversion as the largest measured costs in the current scan. Native scalar
  hydration now uses bounded SQL batches inside QueryOp. After reload, three
  uninstrumented narrow scans had median 55.217 ms (50.305–62.122); full scans
  had median 61.174 ms (57.784–62.799), approximately 6× faster than the
  comparable uninstrumented baseline above. Four-page narrow and full cursor
  walks each returned the same seven IDs in order. Twenty scalar fields on
  100 cards matched full responses; GET/POST parity and missing-ID/malformed
  filter errors passed. Full suite: 842 passed, 8 skipped; Ruff passed.
  The historical 11.5-second delay remains unexplained. See
  [routing_efficiency_results.md](routing_efficiency_results.md) for phase
  measurements, methodology, regression coverage, and limitations.

## 18. Errors & busy behaviour

- [x] Unknown ids:

  ```powershell
  Api GET "/v1/notes?where=id==1" | J
  Api DELETE /v1/decks/999999999 | J
  Api PATCH /v1/notes/999999999 '{"fields":{"Front":"x"}}' | J
  ```

  → empty 200 `items: []`; HTTP 404; HTTP 404.
- [x] Malformed inputs (`J` shows the full error message, which the table
  view truncates):

  ```powershell
  Api GET "/v1/cards?search=%22unbalanced" | J
  Api GET "/v1/cards?where=nonsense" | J
  curl.exe -s -o NUL -w "%{http_code}`n" @K -X POST $T/v1/decks -H "Content-Type: application/json" -d "nope"
  ```

  → HTTP 400 with Anki's search error; HTTP 400 with the where-DSL help;
  `422` (native routes may 422 — only `POST /` never does).
  Live verified 2026-09-07: missing-note lookup returned empty HTTP 200;
  deleting missing deck and updating missing note returned HTTP 404.
  Unbalanced search and malformed where returned HTTP 400 with useful
  detail; invalid native JSON returned HTTP 422.

- [x] **Busy/timeout (controlled test)**: ordinary open dialogs are not a
  reliable trigger. The operation bridge raises `AnkiBusyError` when its
  completion event is not received within `op_timeout_seconds` (default
  15 seconds). A blocked UI thread, queued collection operation, or slow
  operation can exercise this path; merely opening Options did not.

  Verify HTTP 503 using a deliberately delayed **read-only** operation or
  controlled test harness, then verify normal requests recover after the
  delay is removed. Do not infer cancellation from a timeout: the bridge
  stops waiting but does not cancel the scheduled work. Avoid mutation
  requests for fault injection or blind retries after a timeout.

  Live probe 2026-09-07: with TestSuite deck Options open, suspending
  disposable shim card `1788796639073` succeeded (HTTP 200, 2.805 ms
  server time, 0.209 s total). Unsuspend also succeeded and readback
  restored queue/type/due/reps/flags. Source inspection confirmed the
  timeout mechanism and existing HTTP-503 mapping tests.

  Controlled live test passed 2026-09-07: user scheduled a 35-second UI
  thread sleep via the debug console with a 10-second delay. Read-only
  `/v1/cards?select=id&limit=1` returned HTTP 503 after 15.222 seconds
  with `Read operation timed out; Anki may be busy or blocked by a dialog`.
  A subsequent read returned HTTP 200 as the UI recovered (2.162 seconds
  total). No mutation requests were used for this controlled test.

- [x] Normal shutdown/restart recovery: live verified 2026-09-07.
  Before closing, polling returned HTTP 200 and the event stream connected.
  After the user closed Anki normally, a fresh request failed to connect
  (curl exit 28, HTTP 000). After reopening `[DEV] Yomine`, active-profile
  lookup and card read returned HTTP 200; the card read took 2.017 ms server
  time. A fresh event stream returned HTTP 200 and `: connected`. The same
  localhost:7777 endpoint served successfully after restart.
- [x] Shutdown with an active event stream and continuous polling: live
  verified 2026-09-07. On normal Anki exit, the stream emitted
  `event: close` with `data: {"reason": "shutdown"}` and curl exited 0.
  The still-running polling monitor changed from HTTP 200 to connection
  failure (HTTP 000, curl exit 28), then back to HTTP 200 after restart.
  Active profile was `[DEV] Yomine`; a fresh event stream connected with
  HTTP 200. Normal shutdown should close gracefully; an abrupt stream
  connection error is not required for this case.
- [ ] Optional forced-crash recovery: not performed. Normal shutdown and
  restart above do not establish behavior after forcibly terminating Anki.


---

When every suite is initialled: `git push` is the only thing left.

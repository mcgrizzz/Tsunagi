# Dataflow walkthroughs — request to Anki internals

How a request travels from the HTTP socket to Anki's Rust backend and back:
which threads it crosses, which planner tier serves it, and what each stage
costs. Companion to [list_models.md](list_models.md), which traces the
Python→rsbridge→Rust→SQL half in per-method detail; these docs start earlier
(at the socket) and focus on the routing decisions Tsunagi itself makes.

Baseline used for cost notes: 100k notes / 150k cards / 40 decks, page ≤200.

## The shared pipeline

Every request passes through the same five stages:

```
client
  │  HTTP
  ▼
uvicorn ── daemon thread "tsunagi-http", asyncio loop (app.py)
  ▼
DynamicCORSMiddleware ── origin allowlist, read live from settings
  ▼
ApiKeyAuthMiddleware ── compare_digest on X-Api-Key / Bearer
  │                     (`?api_key=` accepted for /v1/events only)
  ▼
FastAPI router ── sync handlers, so each request runs on a loop worker thread
  ▼
adapter call ── EVERY collection touch is one cross-thread round trip:
  │   request thread ──run_on_main──▶ Qt MAIN thread (builds the op)
  │                                     │ taskman.run_in_background
  │                                     ▼
  │                                  WORKER thread: fn(col) → Rust backend
  │                                     │ (collection mutex) → SQLite
  │   request thread ◀──Event.set────── done-callback (main thread)
  ▼
response ── Paginated/SchedulingResult envelope, stats.duration_ms
```

The cross-thread hop is why adapters batch: one `@as_query_op` call that
reads 250 rows costs one hop; 250 calls cost 250. (`adapters/ops.py`.)

## The planner: how a read picks its tier

`make_plan` (`shared/planning.py`) decides how `GET /v1/<resource>` runs.
First match wins:

| # | Tier | Fires when | Id enumeration | Hydration | Cost shape |
|---|------|-----------|----------------|-----------|------------|
| 0 | **search** | `?search=` present | full Anki search, per page (stateless cursors) | page only, chunked | search cost × pages |
| 1a | **index (id)** | `where` has `id==` / `id in [...]` | the listed values ARE the ids | page only, chunked | page-bounded |
| 1b | **index (secondary)** | `where` on `note_id` / `card_id` | n/a — fetch by values | all matched rows, then paginate in memory | bounded by values listed |
| 2 | **columns** | `select` ⊆ a registered cheap column set | n/a | one bulk fetch of just those columns | one backend call |
| 3 | **full** | resource has `fetch_all` (decks ~40, models ~30 rows only) | n/a | everything | bounded by table size |
| 4 | **scan** | everything else (bare/`where`-only listing) | **keyset**: `select id … where id > ? limit ?` on the PK (cards/notes/reviews) | page only, chunked | ~1ms/page id walk |

Two orthogonal refinements on the scan/index tiers:

- **The full `where` predicate always re-runs on hydrated rows** — every
  prefilter (search, index values, keyset chunk) only ever narrows to a
  superset, so filters can never silently drop terms.
- **Two-phase hydrate**: a `where`-only query (no `select`) first hydrates
  scan chunks with just the fields the predicate reads, then re-fetches the
  surviving page in full — renders/scheduling/FSRS lookups are spent on the
  page, not on every rejected row. (`route_factory.py::_rehydrate`.)

## Walkthroughs

- [get_cards_page.md](get_cards_page.md) — `GET /v1/cards?limit=50`: the
  keyset scan tier, stage by stage, with the old-vs-new cost.
- [get_cards_filtered.md](get_cards_filtered.md) — `GET /v1/cards?where=
  queue==-1`: two-phase filtered scan.
- [post_cards_suspend.md](post_cards_suspend.md) — `POST /v1/cards:suspend`:
  a mutation's full life, including undo, the browser repaint, and the event
  stream — plus the AnkiConnect Shim variant of the same call.
- [list_models.md](list_models.md) — the original per-method deep dive into
  the Python→rsbridge→Rust→SQL machinery (`service, method` numbers and all).

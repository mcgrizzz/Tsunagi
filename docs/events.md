# Event stream

[← Documentation](README.md)

`GET /v1/events` lets your app keep its Anki data current or react to activity
such as reviewer answers. Apps opt in by opening a connection; use your configured
port in the examples below.

## Keep a note list up to date

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

**Handle one event: `refresh`.** The first one tells you to load your notes.
Later ones tell you to refresh them. This includes changes after sync and recovery
if the server's event queue overflows. There is no separate ready/reset handler.

In a browser, the listener looks like this:

```javascript
const stream = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");
stream.addEventListener("refresh", () => requestNotesRefresh());
```

`requestNotesRefresh()` stands for your app's reload logic. It should refresh the
notes your interface displays, rather than download the entire collection. Keep
one read running at a time: if another notification arrives during that read,
mark a refresh pending and read again afterward. That avoids overlapping responses
replacing newer results with older ones.

Handle connection failures through your app's usual connection/error handling:
discard unfinished reads and wait for the next connection's initial `refresh`
before loading again. Retry failed reads normally. The stream carries refresh
notices; query responses supply current data.

## Choose what you receive

| Your app needs… | Query parameters |
| --- | --- |
| Notes kept current | `resources=notes` |
| Notes and note types kept current | `resources=notes,models` |
| Reviewer answers | `types=review` |
| Sync progress | `types=sync` |
| Note refreshes and reviewer answers | `types=refresh,review&resources=notes` |
| Everything | Omit both filters |

`types` accepts **refresh**, **review**, and **sync**. Supplying `resources` alone
selects refresh notifications. If you supply both parameters, `types` must include
`refresh`; otherwise the request returns HTTP **422** instead of ignoring the
resource filter.

The available resource views are `notes`, `cards`, `models`, `decks`, `tags`,
`reviews`, `scheduler`, and `config`. Separate values with commas. Empty or unknown
values return HTTP **422** before streaming begins.

Filtering happens **before notifications enter your queue**, so unrelated traffic
cannot fill it. Matching includes related query data: a deck rename may change
which notes match `deck:...`, so it can refresh a notes subscription. Broad or
unknown changes refresh your subscribed views. A review-only subscription receives
neither an initial refresh nor broad collection-refresh notifications.

If authentication is enabled, send `X-API-Key` or a Bearer token. Browser
`EventSource` cannot set custom headers; it can use the `api_key` query parameter.

## What a refresh contains

A saved note can produce this event for a notes subscription:

```json
{
  "type": "refresh",
  "session_id": "abc123",
  "seq": 12,
  "ts": 1789214400000,
  "reason": "change",
  "resources": ["notes"],
  "targets": {"notes": [1789162609990]},
  "origin": "ui",
  "action": "notes.updated",
  "anki": {"changes": ["note"], "label": "Update Note"}
}
```

| Field | How to use it |
| --- | --- |
| `resources` | Subscribed views that may need refreshing. No collection-wide wildcard to interpret. |
| `reason` | `initial`, `change`, `collection` (broad Anki invalidation), or `recovery` (after a delivery gap). The same refresh handler can handle all four. |
| `targets` | Known target IDs within those views. Empty when unknown. |
| `origin`, `action`, `anki` | Optional mutation details for advanced clients and diagnostics. |

**You don't need raw Anki flags or IDs to keep a view current.** Target IDs can
help with more selective updates, but they are not a complete change set: they
may include unchanged inputs and omit indirectly affected records. An edit can
also move a note into or out of a filtered query.

Known actions are `notes.created`, `notes.updated`, and `collection.changed` when
more detail is unavailable. Origin is `api`, `ui`, or null when unknown. Anki's
optional label is localized display text; never parse it to identify actions.

## Reviewer answers, sync and delivery problems

| Event | Meaning |
| --- | --- |
| `review` | A reviewer answer: `card_id` and `ease` (1 = Again, 2 = Hard, 3 = Good, 4 = Easy). |
| `sync` | Sync phase: `started` or `finished`. Any resulting data refresh goes only to refresh subscribers. |
| `gap` | The subscriber queue overflowed. Its incomplete backlog was discarded; `discarded` counts those notifications. They cannot be replayed. |
| `close` | The stream ends with reason `shutdown`, `auth`, `timeout`, or `max_events`. An `auth` close requires the current API key on reconnect. |

A `gap` describes **lost delivery**, not a change to Anki. Refresh subscribers
immediately receive a scoped `refresh` with reason `recovery` after it. Their
usual refresh handler restores current data; no extra reset logic is needed.
An app counting reviewer answers should mark that count incomplete when a gap
arrives, because the missing answers cannot be reconstructed from the notice.

None of these messages needs acknowledgement. Heartbeat comments keep idle
connections alive. `max_events` counts delivered notifications, including recovery
refreshes; the initial refresh and gap notices do not count.

## While you type

Ordinary editor notifications wait for **300 ms of quiet**, with a **1-second
maximum** during continuous editing, plus any scheduling/network delay. Anki saves
normally and queries keep reading live collection data.

Compatible notifications combine their target IDs and affected views. General
`collection.changed` and detailed `notes.updated` notifications remain distinct:
they may cover different effects. Coalesce refresh requests in your client;
notification counts are not mutation counts.

API writes, reviews, undo/unknown-origin operations, known creation/deletion and
broader changes bypass this typing debounce and flush pending edits first.
A new subscription flushes older edits before its initial boundary. Large bursts
can flush early to bound memory use. Shutdown closes subscriptions and drops
pending edits; the next connection's initial refresh reloads current data.

## Which changes have IDs?

| Source | Currently identified targets |
| --- | --- |
| Tsunagi note update/delete | Notes |
| Tsunagi scheduling and other card mutations | Cards |
| Tsunagi deck update/delete | Decks |
| Successful Add-dialog save | The new note |
| Confirmed legacy editor save | The edited note, captured when its operation is queued |
| New editor's `addNote` / `updateNotes` requests | IDs from the successful response / submitted notes |
| Reviewer answer | Its separate `review` event supplies the card ID |

Target hints are limited to subscribed affected views. Unsupported save paths,
bulk browser actions, undo/redo and sync may lack IDs. API note creation returns
its ID in the HTTP response; its general event does not yet include that ID.

The Add dialog and newer editor can emit a specific notification alongside
Anki's general one. Specific notifications do not suppress a general one that
could cover additional changes. IDs come from successful operations; failed
saves and unsaved drafts emit no successful-save notification. No extra collection
queries or cached note contents are needed to identify these saves.

## Connection boundaries and reconnecting

The first named event for a refresh subscription has reason **`initial`**:

```json
{
  "type": "refresh",
  "session_id": "abc123",
  "after_seq": 11,
  "ts": 1789214400000,
  "reason": "initial",
  "resources": ["notes"],
  "targets": {}
}
```

Registration and `after_seq` are captured together. Changes arriving before this
initial event reaches you are already queued. Start loading on this event and
retain refresh requests that arrive while loading. The initial event stays outside
the bounded queue. Review/sync-only connections start with a connection comment
and do not request an initial data load.

Live notifications carry `session_id`, `seq`, and `ts` (Unix milliseconds). Their
SSE ID is `<session_id>:<seq>`. Initial/recovery refreshes and gap notices have
`after_seq` instead of `seq` and no SSE ID: they mark a boundary for this connection,
not a globally published mutation. Later live notifications have greater sequence
numbers. Filtering creates normal sequence gaps; a gap in numbers alone does not
prove lost delivery. A live event keeps its ID across subscribers, while its
resource list and target hints are scoped to each subscription.

**Each new connection starts fresh.** The session ID stays the same while the
server runs with the same collection. Restarting the server or switching profiles
creates a new ID and closes old subscriptions. Discard unfinished reads from an
old connection even if a reconnect has the same session ID.

Delivery remains live-only and best-effort. `Last-Event-ID` does not replay missed
events; `gap` reports queue overflow, not every possible network loss. These
boundaries do not make separate HTTP reads an atomic collection snapshot.

No active session returns HTTP **503**. Shutdown racing with an accepted
connection produces `close` instead. Media/import coverage is incomplete, and
another add-on's direct database edits may bypass hooks.

Earlier development versions exposed `ready`, `change`, and `reset` as public
events. Use `refresh` now, including in the `types` parameter; use its `resources`
field in place of the old `refresh` field. There is no legacy event mode.

See the [interactive reference](playground.md) for stream parameters.

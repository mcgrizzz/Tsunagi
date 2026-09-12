# Event stream

[← Documentation](README.md)

`GET /v1/events` tells your app when to refresh its Anki data. Connect while
Anki is running, using your configured port:

```sh
curl -N http://127.0.0.1:7777/v1/events
```

Apps opt in by opening this connection. Without filters it receives all events;
add filters to receive the notifications your app uses.

If authentication is enabled, send `X-API-Key` or a Bearer token. Browser
`EventSource` cannot set custom headers; it can use the `api_key` query parameter.

## Keep a note list up to date

Subscribe to changes that could affect your notes:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?types=change&resources=notes'
```

The client needs three handlers:

| Event | What to do |
| --- | --- |
| `ready` | Load your notes. This also runs after reconnecting. |
| `change` | Refresh your notes: something may have changed. |
| `reset` | Refresh your notes: the server cannot describe all the changes. |

**You don't need to interpret Anki flags or find IDs in each event.** The server
already checked whether the change could affect the views you subscribed to.
For example, renaming a deck can change a note query that uses `deck:...`, so
that notification still reaches a notes subscription.

Use one refresh loop so overlapping requests cannot overwrite newer results:

```text
on ready, change, or reset:
    mark refresh needed
    if a refresh is already running: return

    while refresh is needed and this connection is still ready:
        clear refresh needed
        notes = fetch the current notes your interface displays
        if this connection is still current:
            show(notes)
```

If a change arrives during a read, the loop reads again afterward. If the
connection closes or fails, discard unfinished reads and wait for the next
`ready` before loading again. Treat each `ready` as a new connection, even if
its session ID is unchanged. Retry failed reads through your app's normal error
handling. Events are refresh notices; the query response supplies current data.

## Choose your notifications

| Interest | Query parameters |
| --- | --- |
| Changes affecting notes | `types=change&resources=notes` |
| Changes affecting either notes or models | `types=change&resources=notes,models` |
| Reviewer answers | `types=review` |
| Sync progress | `types=sync` |
| Everything | Omit both filters |

- **`types`** accepts `change`, `review`, and `sync`.
- **`resources`** filters `change` events by their `refresh` views: `notes`,
  `cards`, `models`, `decks`, `tags`, `reviews`, `scheduler`, and `config`.
  It doesn't filter reviewer answers or sync progress; use `types=change` to
  omit those.
- Separate multiple values with commas. Values in one filter are alternatives;
  when you supply both filters, both apply. Unknown or empty values return
  HTTP **422** before the stream opens.

Filtering happens **before events enter your subscription's queue**, so unwanted
traffic cannot fill it. `max_events` counts delivered notifications, including
resets; filtered events and `ready` don't count.

Every subscription still receives `ready`, `reset`, and `close`, plus heartbeat
comments that keep the connection alive. Broad or unknown changes pass every
resource filter so the client can refresh after undo or an operation with limited
details. Filters do not remove fields from matching events. IDs and raw Anki
flags remain available for clients that need them; target-ID filtering is not
offered because those IDs are not a complete list of affected records.

## A note was saved: what should my app do?

An identified editor save produces an SSE event named **`change`**. Its JSON
data looks like this (IDs and raw change flags vary):

```json
{
  "type": "change",
  "session_id": "abc123",
  "seq": 12,
  "ts": 1789214400000,
  "origin": "ui",
  "action": "notes.updated",
  "targets": {"notes": [1789162609990]},
  "refresh": ["cards", "models", "notes", "reviews", "tags"],
  "anki": {"changes": ["note"], "label": "Update Note"}
}
```

| Field | How to use it |
| --- | --- |
| `action` | Known work: `notes.created`, `notes.updated`, or `collection.changed` when a more specific action is unavailable. |
| `targets` | Known operation targets, grouped as `notes`, `cards`, `decks` or `models`. An empty object means the targets are unknown. |
| `refresh` | Resource views that may be affected, including related data. Refresh relevant queries when their membership may have changed. |
| `origin` | `api` for Tsunagi operations, `ui` for Anki UI paths or other attributed handlers, and `null` when unknown. |
| `anki` | Raw change flags and an optional localized label, for diagnostics or advanced clients. Normal clients can use `refresh` instead. |

**Targets are hints, not a complete change set.** They may include unchanged
inputs and omit indirectly affected records. A note edit can change rendered
cards or move a note into or out of a filtered query. Inspect `refresh` even
when you have target IDs.

`refresh` can contain `notes`, `cards`, `models`, `decks`, `tags`, `reviews`,
`scheduler` or `config`. `collection` means to refresh your view broadly. These
are view categories, not instructions to download every record or URL paths.
Unknown future Anki flags conservatively request a collection refresh.
Related query membership counts too: changing a note's tags can change a
review-history query using that tag, even though no review row was modified.

## While you type

Ordinary Anki editor changes are **debounced**: Tsunagi sends notifications after
**300 ms without another edit**, or after **1 second of continuous editing**.
These are notification deadlines; network and task scheduling can add delivery
time. Anki still saves normally, and queries read the current collection.

A burst can update several notes. Notifications with the same action and
compatible Anki metadata combine their target IDs and refresh hints. General
`collection.changed` and detailed `notes.updated` notifications stay distinct,
so a newer-editor burst can produce both. They do not represent a notification
per keystroke or a record of every intermediate field value.

API writes, reviews, undo/unknown-origin operations, known creation/deletion and
changes affecting other resources bypass the typing debounce. Such events flush
waiting edits first. A new subscriber also flushes earlier edits **before** its
`ready` boundary; an input-count limit can flush an unusually large burst early.
Shutdown discards pending edits as it closes subscriptions; reconnecting always
requires a fresh read.

Sequence IDs are assigned after grouping, so listeners receive the same event
ID and payload. The stream wakes for the next debounce deadline instead of
adding a full polling interval to that deadline. `max_events` counts delivered
notifications, including grouped ones.

## Which changes have IDs?

| Source | Currently identified targets |
| --- | --- |
| Tsunagi note update/delete | Notes |
| Tsunagi scheduling and other card mutations | Cards |
| Tsunagi deck update/delete | Decks |
| Successful Add-dialog save | The new note |
| Confirmed legacy editor save | The edited note, captured when its operation is queued |
| New editor's `addNote` / `updateNotes` backend requests | IDs from the successful response / submitted notes |
| Reviewer answer | Its separate `review` event supplies the card ID |

The UI additions cover the checked editor paths, not every way another add-on
or a future Anki version can save a note. Unsupported paths retain general
change notifications. Bulk browser actions, undo/redo and sync can still lack
IDs. API note creation returns its ID in the HTTP response; its general event
does not yet include that ID.

Legacy editor saves enrich their existing operation notification. The Add
dialog and newer editor also emit a specific notification alongside Anki's
general one. **Coalesce refreshes; do not count notifications as mutations.**
Specific notifications never suppress a general one that could cover additional
changes. No extra collection queries or cached note contents are needed to
identify these saves. Failed saves and unsaved drafts emit no successful-save
notification.

## Other events and reconnecting

| Event | Meaning |
| --- | --- |
| `review` | A reviewer answer: `card_id` and `ease` (1 = Again, 2 = Hard, 3 = Good, 4 = Easy). A general change event follows. |
| `sync` | `phase: "started"` or `"finished"`; finished sync is followed by `reset`. |
| `reset` | `refresh: ["collection"]` asks for a broad refresh. `reason: "lagged"` means the queue overflowed; its incomplete backlog is replaced by this reset. |
| `close` | The stream ends: `reason` is `shutdown`, `auth`, `timeout` or `max_events`. An `auth` close requires the current API key on reconnect. |

Notifications carry `session_id`, `seq` and `ts` (Unix milliseconds). Their SSE
`id` is `<session_id>:<seq>`. Sequence numbers increase within a session and can
have gaps, including when other events are filtered out; a gap alone does not
mean you missed a mutation. Closing frames contain
only their reason. Labels are localized; never parse them to identify actions.

## Connect, then load your data

The first named event on each connection is **`ready`**:

```text
event: ready
data: {"type":"ready","session_id":"abc123","after_seq":11,"ts":1789214400000,"refresh":["collection"]}
```

`after_seq` is the sequence at the instant your subscription was registered.
Subsequent notifications on this connection have a greater `seq`. Registration
and that boundary are captured together, so changes arriving before you receive
`ready` are already queued for you. `ready` stays outside that bounded queue,
has no SSE `id`, and does not count toward `max_events`.

1. Open the stream and wait for `ready`.
2. Fetch the data your app needs. Keep notifications received during that fetch.
3. Apply their refresh hints after loading; coalesce repeated refreshes.

A `reset` replaces an overflowed backlog and asks you to refresh broadly. If the
connection closes during a fetch, discard that unfinished load and start again
after the next `ready`. This boundary orders notifications; it does not make
separate HTTP queries an atomic collection snapshot.

**Reconnect always means refresh.** Reconnecting to the same running server
keeps the session ID, but delivery is live-only: `Last-Event-ID` does not replay
missed events. A server restart or profile switch creates a new random session
ID. It identifies this server/collection lifetime, not a persistent collection
or a profile name. Old subscriptions close and cannot receive the new session's
events; discard their pending data when the session changes.

When no event session is active, a new request receives HTTP 503. A shutdown
racing with an already accepted connection produces `close` instead.

Media and import/export coverage is incomplete. Direct database edits by another
add-on may bypass the hooks. The stream cannot maintain an exact collection
replica by itself.

See the [interactive reference](playground.md) for stream parameters.

# Event stream

[← Documentation](README.md)

`GET /v1/events` tells your app when to refresh its Anki data. Connect while
Anki is running, using your configured port:

```sh
curl -N http://127.0.0.1:7777/v1/events
```

If authentication is enabled, send `X-API-Key` or a Bearer token. Browser
`EventSource` cannot set custom headers; it can use the `api_key` query parameter.

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
have gaps; a gap alone does not mean you missed a mutation. Closing frames contain
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

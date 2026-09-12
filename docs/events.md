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

Notifications carry `seq` and `ts` (Unix milliseconds). Closing frames contain
only their reason. Labels are localized; never parse them to identify actions.

Delivery is **live-only and best-effort**. There is no `ready` event,
collection-session token or `Last-Event-ID` replay yet. Establish the subscription
before fetching initial data, retain notifications received during that fetch,
and refresh as needed. Fetch fresh data after reconnecting.

Media and import/export coverage is incomplete. Direct database edits by another
add-on may bypass the hooks. The stream cannot maintain an exact collection
replica by itself.

See the [interactive reference](playground.md) for stream parameters.

# Listen for changes in Anki

[← Documentation](README.md)

`GET /v1/events` keeps a connection open and sends messages describing what
happened: **`notes.created`**, **`notes.updated`**, **`notes.deleted`**, and so on.
Messages contain IDs. Your app decides whether it needs to fetch any contents.

Changes made through the API are announced immediately. Changes made inside
Anki (the Browser, the editor, the Add dialog, the reviewer) are announced
about half a second after they stop; while you type, one message follows a
two-second pause.

## See the messages

Start Anki, then run:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

Use your configured port if it isn't `7777`. After you edit **note 123 through
the API**, a message looks like this (connection metadata omitted):

```text
event: notes.updated
data: {"type":"notes.updated","ids":[123]}
```

Delete it, and the message is:

```text
event: notes.deleted
data: {"type":"notes.deleted","ids":[123]}
```

| Message | What happened |
| --- | --- |
| `notes.created` | New notes were added. `ids` identifies them. |
| `notes.updated` | A note update completed. `ids` identifies the affected notes. |
| `notes.deleted` | A deletion completed. These `ids` are now absent. |
| `notes.stale` | Notes changed, but which ones isn't known. It has no `ids`: reload the notes you show. |

Cards use the same names: `cards.created`, `cards.updated`, `cards.deleted`,
`cards.stale`.

Changes and card answers made through the API also carry `client`: the app
whose key sent the request, or the No key row it fell in (for example `"client":
"Phone"`). A dashboard can tell its own writes from another tool's.

**Known IDs and an unknown change are alternatives for the same resource.**
Deleting note 123 can produce `notes.deleted` and `cards.stale`, because its
deleted card IDs aren't included. That operation won't also produce
`notes.stale`.

## Choose what to receive

| Interest | Query |
| --- | --- |
| All note changes | `?resources=notes` |
| All card changes | `?resources=cards` |
| Both | `?resources=notes,cards` |
| Only confirmed note deletions | `?types=notes.deleted` |
| Note creations and updates | `?types=notes.created,notes.updated` |
| Card answers, in Anki's reviewer or through either API, with the card's new interval, due, queue and FSRS memory state | `?types=review` |
| Sync starting or finishing, from Anki's Sync button or either API | `?types=sync` |
| Due counts for a deck list: new, learning and review cards per deck, sent when they move (answers, suspends, deck changes, syncs, day rollover) | `?types=decks.counts` |

Which kinds you receive depends on your app's role (config.md): change
messages need `events:changes` (Default and Read-only have it), review
messages need `events:reviews` (only Everything has it by default). A kind
your role lacks is never sent; the `ready` message lists the resources you
can receive. If your key or role changes, the stream closes with reason
`auth`; reconnect to pick up the new permissions.

Filters apply before messages enter your connection's queue. A client listening
for note deletions won't queue reviews or card updates.

Use `resources=notes` when maintaining a note list. An exact type filter such as
`types=notes.deleted` excludes `notes.stale`, so it won't cover a deletion
whose details Anki didn't report.

## React in your app

The event describes the change; the handler decides what to do with it. Here,
`notesById` is a JavaScript Map, and the helper functions load notes and draw them:

```js
const events = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");

for (const type of ["notes.created", "notes.updated"]) {
    events.addEventListener(type, ({data}) => {
        fetchNotesById(JSON.parse(data).ids);
    });
}

events.addEventListener("notes.deleted", ({data}) => {
    for (const id of JSON.parse(data).ids) notesById.delete(id);
    drawNotes();
});

events.addEventListener("notes.stale", () => reloadNoteList());
events.addEventListener("ready", () => reloadNoteList());
events.addEventListener("gap", () => reloadNoteList());
```

`fetchNotesById` requests `/v1/notes` with `where=id in [123]`, follows any
returned pages, and updates the Map and display. Use `select` to choose the
fields needed. If an ID no longer exists by the time you read it, remove it
from the Map.

`ready` means the subscription is active. `gap` means queued messages were lost.
Neither says that a note changed. This example loads its list on connection and
reloads it after a gap; a client that just reacts to actions may handle them
differently. There is no separate `refresh` message.

<details>
<summary>Which operations provide IDs?</summary>

| Operation | Event |
| --- | --- |
| Update a note through the Tsunagi API, or its fields through the AnkiConnect Shim | `notes.updated` |
| Delete notes through either API | `notes.deleted` |
| Create a note through either API | `notes.created`, and `cards.created` for its new cards |
| Add or remove tags on given notes through either API | `notes.updated` |
| Answer cards through either API | `cards.updated` for the cards answered |
| Suspend, unsuspend, bury, unbury, forget, flag, move to a deck, set due date, set values or reposition cards through the Tsunagi API | `cards.updated` |
| Changes made inside Anki | `notes.*` and `cards.*` with IDs, and `reviews.created` with review log IDs |
| Undo, and rows Anki restores without a new modification time | `notes.stale`, `cards.stale`, or another affected resource's `.stale` |

Lists contain at most 1,000 IDs per resource. Larger sets produce `.stale`
instead. Repositioning with `shift_existing` also moves other
cards, so it produces `cards.stale`. No extra note or card contents are read to build events.
Deletion batches can include IDs already absent; card-update batches can include
cards already in the requested state. An operation that changes nothing sends
no event.

Each message means that resource's own data changed. An operation can produce
messages about several resources; other resources currently use `.stale`
notifications, such as `decks.stale`.

Media/import coverage is incomplete. Changes other add-ons make without Anki's
notification hooks are reported with the next change Anki does announce.

</details>

<details>
<summary>Keeping displayed notes correct</summary>

**While editing in Anki:** edits are reported once typing pauses for two
seconds, as `notes.updated` for the edited note.

**While loading:** if a change arrives during a request, schedule another load
afterward. An older response must not overwrite newer data. Ignore unfinished
requests from a closed connection. The example leaves this coordination to your
app's helper functions.

**While showing search results:** a search can change without its own resource
changing. `deck:Japanese` results change when that deck is renamed, and `is:due`
results change when cards are answered. Also listen to each resource your search
names, for example `resources=notes,decks`, and repeat the search when one
changes. If your list shows `tag:verb` and a note loses that tag, fetching the
new contents isn't enough—you must also remove it from that list. Repeat the search if your app can't determine whether it still
matches. Sorting, counts and page boundaries can change too.

**After a disconnect:** missed messages aren't replayed. A new connection sends
`ready`; load the relevant data again. A `gap` while connected means that
connection fell behind and lost queued messages.

**Profile switches:** the server stops while no profile is open. The stream
ends with `close` reason `profile_closed`, and connections are refused until a
profile opens again. Retry with a backoff. The next `ready` carries a new
`session_id` for the new collection.

</details>

For API keys, combined filters, review ratings, connection-close reasons and all
message fields, open **GET /v1/events** in the [interactive reference](playground.md).

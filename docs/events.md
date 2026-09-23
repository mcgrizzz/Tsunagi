# Listen for changes in Anki

[← Documentation](README.md)

`GET /v1/events` keeps a connection open and sends messages describing what
happened: **`notes.created`**, **`notes.updated`**, **`notes.deleted`**, and so on.
Messages contain IDs. Your app decides whether it needs to fetch any contents.

Text-only note edits made inside Anki, including typing, are not announced.
API edits, new notes added in Anki, reviews, undo, sync and other collection
actions can still produce messages.

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
| `notes.changed` | Note data or note search results may have changed, but the affected IDs or kind of change aren't known. `ids` is `null`. |

Cards use the same names: `cards.created`, `cards.updated`, `cards.deleted`,
`cards.changed`.

**Known IDs and an unknown change are alternatives for the same resource.**
Deleting note 123 can produce `notes.deleted` and `cards.changed`, because its
deleted card IDs aren't included. That operation won't also produce
`notes.changed`.

## Choose what to receive

| Interest | Query |
| --- | --- |
| All note changes | `?resources=notes` |
| All card changes | `?resources=cards` |
| Both | `?resources=notes,cards` |
| Only confirmed note deletions | `?types=notes.deleted` |
| Note creations and updates | `?types=notes.created,notes.updated` |
| Reviewer answers | `?types=review` |
| Sync starting or finishing | `?types=sync` |

Filters apply before messages enter your connection's queue. A client listening
for note deletions won't queue reviews or card updates.

Use `resources=notes` when maintaining a note list. An exact type filter such as
`types=notes.deleted` excludes `notes.changed`, so it won't cover a deletion
whose details Anki didn't report, or a change in which notes match a search.

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

events.addEventListener("notes.changed", () => reloadNoteList());
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
| Create a note through either API or Anki's Add dialog | `notes.created` |
| Update a note through the Tsunagi API, or its fields through the AnkiConnect Shim | `notes.updated` |
| Delete notes through either API | `notes.deleted` |
| Create a note through the Tsunagi API | `cards.created` for its new cards too |
| Suspend, unsuspend, bury or unbury cards | `cards.updated` |
| Other operations without complete IDs, including undo | `notes.changed`, `cards.changed`, or another affected resource's `.changed` |

Lists contain at most 1,000 IDs per resource. Larger sets produce `.changed`
with `ids: null` instead. No extra note or card contents are read to build events.
Deletion batches can include IDs already absent; card-update batches can include
cards already in the requested state. An operation that changes nothing sends
no event.

An operation can produce messages about several resources. Other resources
currently use `.changed` notifications, such as `decks.changed`. A broad change
can also affect related searches: renaming a deck can change the results of a
note query that uses that deck's name.

General and detailed Add-dialog notifications can overlap. Media/import coverage
is incomplete, and other add-ons can bypass Anki's notification hooks.

</details>

<details>
<summary>Keeping displayed notes correct</summary>

**While editing in Anki:** text-only note edits are excluded, with no later
finished-typing message. Anki still saves normally. Changes that also generate
cards or affect tags can still produce messages. API edits and undo are reported.

**While loading:** if a change arrives during a request, schedule another load
afterward. An older response must not overwrite newer data. Ignore unfinished
requests from a closed connection. The example leaves this coordination to your
app's helper functions.

**While showing search results:** if your list shows `tag:verb` and a note loses
that tag, fetching the new contents isn't enough—you must also remove it from
that list. Repeat the search if your app can't determine whether it still
matches. Sorting, counts and page boundaries can change too.

**After a disconnect:** missed messages aren't replayed. A new connection sends
`ready`; load the relevant data again. A `gap` while connected means that
connection fell behind and lost queued messages.

</details>

For API keys, combined filters, review ratings, connection-close reasons and all
message fields, open **GET /v1/events** in the [interactive reference](playground.md).

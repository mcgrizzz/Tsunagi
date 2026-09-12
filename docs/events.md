# Update your app when Anki changes

[← Documentation](README.md)

`GET /v1/events` keeps a connection open and sends messages when something
changes. **Messages contain IDs, not full notes or cards.** Your app fetches the
contents it needs through the normal API.

Text-only note edits made inside Anki, including typing, are not announced.
API edits, new notes added in Anki, reviews, undo, sync and other collection
actions can still produce messages.

## Connect

Start Anki, then run:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

Leave this running to see messages about notes. Use your configured port if it
isn't `7777`.

| To listen for… | Use |
| --- | --- |
| Note changes | `?resources=notes` |
| Card changes | `?resources=cards` |
| Both | `?resources=notes,cards` |
| Reviewer answers | `?types=review` |
| Sync starting or finishing | `?types=sync` |

## What should your app do?

For notes, handle two message names: **`change`** and **`refresh`**.

A `change` message gives your app one of these instructions:

| In the message | Your app should… |
| --- | --- |
| `changes.notes.fetch` | Fetch the notes with these IDs. |
| `changes.notes.remove` | Remove these IDs from its stored notes. |
| `refresh: ["notes"]` | Run the request that loaded its note list again. The affected IDs aren't all known. |

**It won't ask you to update specific notes and reload the note list in the same
message.** If `changes.notes` exists, `refresh` does not contain `"notes"`.
Cards use the same fields under `changes.cards`.

For example, after you edit **note 123 through the API**, this part of the
message tells your app to fetch it:

```json
{
  "changes": {
    "notes": {"fetch": [123], "remove": []}
  },
  "refresh": []
}
```

Request `/v1/notes` with `where=id in [123]` to get its current contents. Use
`select` if you only need some fields. If you delete note 123 through Tsunagi,
its ID arrives in `remove` instead, so your app can remove it without a lookup.

A separate `refresh` message asks your app to load its notes. You receive one
when you first connect, reconnect, or when Anki reports a change without enough
information to identify the notes. Use the same note-list request your app
already uses; you don't need to download the whole collection.

## Handling the messages

Here, `notesById` is a JavaScript Map containing your app's notes. The helper
functions fetch notes by ID, reload your note list, and draw the notes on screen.
Drawing uses the data already loaded; it doesn't make an API request.

```js
const events = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");

events.addEventListener("change", ({data}) => {
    const message = JSON.parse(data);
    const notes = message.changes.notes;

    if (notes) {
        for (const id of notes.remove) notesById.delete(id);
        if (notes.fetch.length) fetchNotesById(notes.fetch);
        drawNotes();
    } else if (message.refresh.includes("notes")) {
        reloadNoteList();
    }
});

events.addEventListener("refresh", () => reloadNoteList());
```

`fetchNotesById` should request the IDs, follow any returned pages, update
`notesById`, and redraw when done. If an ID is no longer found, remove it from
the Map. The `refresh` listener runs only for messages named `refresh`, not after
every `change`.

<details>
<summary>Which actions send IDs or a reload request?</summary>

| Action | Message contents |
| --- | --- |
| Create or edit a note through the native API | Note ID in `fetch` |
| Create or update note fields through the compatibility API | Note ID in `fetch` |
| Delete notes through either API | Note IDs in `remove` |
| Create a note through the native API | Its new card IDs in `changes.cards.fetch` too |
| Call suspend, unsuspend, bury, or unbury for cards | Card IDs in `fetch` |
| Save a new note in Anki’s Add dialog | Note ID in `fetch` |
| Undo, sync, or another reported change without note/card IDs | Request to reload the note/card list |

Notes and cards are handled separately. Deleting note 123 can tell your app to
remove that note and reload its **cards**, because the deleted card IDs aren't
included. It won't also ask you to reload **notes**.

If a list would contain more than 1,000 note IDs or card IDs, Tsunagi asks your
app to reload that list instead. No extra notes or cards are fetched to build
an event.

</details>

<details>
<summary>Keeping displayed notes correct</summary>

**While editing in Anki:** text-only note edits are excluded. There is no message
after a typing pause or when typing stops. Anki still saves your edits normally.
Changes that also affect other data, such as generating cards or changing tags,
can still produce messages. API edits and undo are still reported.

**While loading:** if another change arrives during a request, remember that
another load is needed and run it afterward. Otherwise an older response could
leave your display out of date. Ignore unfinished requests from a closed
connection. The example above leaves this request coordination to your app.

**While showing search results:** suppose your list shows `tag:verb` and a note
loses that tag. Fetching its new contents isn't enough—you must also remove it
from that list. If your app can't work out whether it still matches the search,
run the search again. The same applies to sorting, counts, and page boundaries.

**After a disconnect:** old messages aren't replayed. Load the list again when
the new connection sends `refresh`. If your app falls behind while connected,
Tsunagi sends `gap`, then `refresh` to request the same reload.

</details>

For API keys, combined filters, review ratings, connection-close reasons, and all
message fields, open **GET /v1/events** in the [interactive reference](playground.md).

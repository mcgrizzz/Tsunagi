# Update your app when Anki changes

[← Documentation](README.md)

`GET /v1/events` keeps a connection open and sends messages when something
changes in Anki. Your app can listen for note changes, card changes, reviewer
answers, or sync progress.

## Connect

Start Anki, then run:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

Leave this running. It prints messages about notes as they arrive. Use your
configured port if it isn't `7777`.

| To listen for… | Use |
| --- | --- |
| Note changes | `?resources=notes` |
| Card changes | `?resources=cards` |
| Both | `?resources=notes,cards` |
| Reviewer answers | `?types=review` |
| Sync starting or finishing | `?types=sync` |

## What should your app do?

For notes, handle two message names: **`change`** and **`refresh`**.

A `change` message tells you what to update:

| In the message | Meaning | Your app should… |
| --- | --- | --- |
| `changes.notes.upsert` | Here are the saved notes, including fields and tags. | Add each note to its stored notes, or replace the note with the same ID. |
| `changes.notes.fetch` | Here are note IDs, but no note contents. | Fetch those notes from the API. |
| `changes.notes.remove` | These note IDs no longer exist. | Remove them from its stored notes. |
| `refresh: ["notes"]` | The message cannot identify every affected note. | Run the request that loaded its note list again. |

`upsert` means **add or replace**. For cards, the same fields appear under
`changes.cards`.

For example, suppose your app shows **note 123**:

- **You edit it through the native API.** The saved note arrives in
  `changes.notes.upsert`. Replace your copy of note 123 with this note. You
  already have its new fields and tags; there is no follow-up note request.
- **You edit it in Anki's editor.** When the editor reports the saved note's ID,
  it arrives in `changes.notes.fetch`. Fetch note 123 to get its new contents.
- **You delete it through Tsunagi.** Its ID arrives in `changes.notes.remove`.
  Remove note 123 from your app too.

A separate `refresh` message asks your app to load its notes. You receive one
when you first connect, reconnect, or when Anki reports a change without enough
information to update individual notes. Use the same note-list request your app
already uses; you don't need to download the whole collection.

## Handling the messages

In this example, `notesById` is a JavaScript Map containing your app's notes.
The three helper functions are code you write: fetch notes by ID, reload your
note list, and draw the notes on screen.

```js
const events = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");

events.addEventListener("change", ({data}) => {
    const message = JSON.parse(data);
    const notes = message.changes.notes;

    if (notes) {
        for (const note of notes.upsert) notesById.set(note.id, note);
        for (const id of notes.remove) notesById.delete(id);
        if (notes.fetch.length) fetchNotesById(notes.fetch);
    }

    if (message.refresh.includes("notes")) reloadNoteList();
    drawNotes();
});

events.addEventListener("refresh", () => reloadNoteList());
```

For `fetch: [123,456]`, request `/v1/notes` with the query parameter
`where=id in [123,456]`. Follow any returned pages. If an ID is no longer found,
remove it from your app. Redraw after the fetched notes arrive.

<details>
<summary>Which actions send notes, IDs, or a reload request?</summary>

| Action | Message contents |
| --- | --- |
| Create or edit a note through the native API | Saved note in `upsert` |
| Create or update note fields through the AnkiConnect compatibility API | Note ID in `fetch` |
| Delete notes through either API | Note IDs in `remove` |
| Create a note through the native API | Its new card IDs in `changes.cards.fetch` |
| Call suspend, unsuspend, bury, or unbury for cards | Card IDs in `fetch` |
| Save a note in Anki’s editor or Add dialog | Note IDs in `fetch` |
| Undo, sync, or another change without note/card IDs | Request to reload the note/card list |

One message can do both: deleting a note supplies its note ID, but may still ask
a card-list listener to reload because the deleted card IDs aren't included.

If saved-note data exceeds 64 KiB, Tsunagi sends IDs to fetch instead. If a list
would contain more than 1,000 note IDs or card IDs, it asks your app to reload
that list instead.

</details>

<details>
<summary>Keeping displayed notes correct</summary>

**While typing:** Anki editor notifications wait for 300 ms without typing, or
up to one second if you keep typing. API writes don't wait for this delay.

**While loading:** suppose a request starts loading note 123, then an event
arrives with a newer edit to that note. The older request must not overwrite the
edit. If an event arrives during a load, remember that another load is needed
and run it afterward. Ignore unfinished requests from a closed connection.
The example above leaves this request coordination to your app.

**While showing search results:** suppose your list shows `tag:verb` and a note
loses that tag. Replacing its fields isn't enough—you must also remove it from
that list. If your app can't work out whether the note still matches the search,
run the search again. The same applies to sorting, counts, and page boundaries.

**After a disconnect:** old messages aren't replayed. Load the list again when
the new connection sends `refresh`. If your app falls behind while connected,
Tsunagi sends `gap`, then `refresh` to request the same reload.

</details>

For API keys, combined filters, review ratings, connection-close reasons, and all
message fields, open **GET /v1/events** in the [interactive reference](playground.md).

# How Tsunagi shortens Yomitan's Anki workflow

[← Documentation](README.md) · [Install Tsunagi](../README.md#install)

You look up **食べる** in Yomitan. The popup needs to know whether you've saved it
before, which note to open if you have, and which cards were created if you save
it now. AnkiConnect can supply these answers, but some require a follow-up lookup.

**Tsunagi returns the related answers together.** Here are three places where that
shortens the client code, and what changes in the Anki work behind each request.

| When Yomitan needs to… | Its current calls | With native Tsunagi |
| --- | --- | --- |
| Identify an existing duplicate | Check the note → search for its ID | **One check returns both** |
| Save a note and suspend its cards | Save → find cards → suspend | **Save returns the card IDs** |
| Show a note type's fields | Get model names → request fields | **Models arrive with their fields** |

> These examples show how a native integration could work. Yomitan currently
> uses AnkiConnect requests, which Tsunagi already supports through its compatibility API.

The flows below are pseudocode. AnkiConnect actions are sent to `POST /`;
Tsunagi's native paths are shown directly. `note` means the candidate in the
format expected by that API, including the user's duplicate-check settings.

## 1. Check a duplicate and get its ID in one request

Suppose **食べる is already in Anki**. Yomitan needs to mark it as a duplicate and
offer to open the saved note. A yes/no check can't supply that note's ID.

```text
AnkiConnect:
  canAddNotesWithErrorDetail({notes: [note]})
                                 → cannot add; duplicate error text
  findNotes(search_for_note)      → existing note IDs

Tsunagi:
  POST /v1/notes:check {notes: [note]}
                                 → state: "duplicate", duplicate_note_ids: [...]
```

**The AnkiConnect response:** its check returns an error explaining that the
note is a duplicate, but no matching IDs. Yomitan recognizes that error text,
builds a search from the candidate, and asks Anki for the existing notes.

**What Tsunagi does with that work:**

- **Return both answers.** `state` identifies the duplicate and
  `duplicate_note_ids` supplies the IDs. The client can use the result directly.
- **Share the setup.** For ten candidates using one note type and deck, Tsunagi
  resolves that type once and that deck once. It reuses them across the batch.

Anki still validates each candidate and searches for duplicate IDs where needed.
Those searches use its note-type ID and first field directly within the check;
the client doesn't have to construct and send a second search request.

## 2. Save a note without having to search for its new cards

Now suppose you save a new word with **automatic suspension enabled**. Saving a
note generates cards, and Yomitan needs their IDs before it can suspend them.

```text
AnkiConnect:
  addNote(note)                  → note ID
  findCards("nid:" + noteId)      → card IDs
  suspend(cardIds)

Tsunagi:
  POST /v1/notes                 → note ID + card IDs
  POST /v1/cards:suspend         ← those card IDs
```

**The AnkiConnect response:** `addNote` returns only the note ID. Yomitan
uses it to build a `nid:...` browser search, gets the card IDs, then suspends them.

**What Tsunagi returns together:** the saved note and its card IDs. It reads the
persisted note once, so the response includes Anki’s normalized fields, tags and
metadata, and obtains the cards through Anki’s direct `card_ids_of_note()` method.
No browser card search is needed. [Event subscribers](events.md) can receive that
same note result without another lookup.

The client takes `result.cards` from the save response and passes them to the
suspend endpoint. **Three requests become two.** Saving without suspension is
one request in either API; Tsunagi doesn't change that user setting.

## 3. Get field names with the model list

In Yomitan's settings, you select **Basic** and map dictionary content to its
**Front** and **Back** fields. The picker needs both the model name and its fields.

```text
AnkiConnect:
  modelNames()                   → model names
  modelFieldNames("Basic")       → ["Front", "Back"]

Tsunagi:
  GET /v1/models?select=id,name,fields[].name
                                 → models with their field names
```

**The AnkiConnect response:** the initial list contains names. Selecting
Basic triggers `modelFieldNames("Basic")`; selecting another type needs its own
field request. A client could prefetch these, but would still need an action per
model and pair the results itself.

**What Tsunagi keeps together:** Anki's model record already contains its fields.
Tsunagi loads the records for the requested page and returns each model with its
field names attached. **Selecting a loaded model needs no field request.**

The planner also matches the work to the question. An `id,name` query uses
`all_names_and_ids()` without loading full model definitions. Ask for fields and
it loads the page's model records; `select` keeps unused templates and styling
out of the response. For full field metadata, use `select=id,name,fields` on the
same endpoint. Decks remain a separate query, and more pages mean more requests.

<details>
<summary>Also show how many notes use each type</summary>

A picker can label a type “Basic · 250 notes” without downloading those notes:

```text
GET /v1/models?select=id,name,note_count
  → {items: [{id: 123, name: "Basic", note_count: 250}, ...], ...}
```

`note_count` counts notes across all decks, including zero for an unused type.
It does not count generated cards. Tsunagi gets names, IDs and counts together
through Anki's `all_use_counts()` method. Queries asking only for names and IDs
keep the cheaper path described above.

You can filter with `where=note_count>0`, or request fields and counts together
with `select=id,name,note_count,fields[].name`. Counts are read from the current
collection on each request, so additions, deletions and undo are reflected.
They are also included in full model queries, but may be null in mutation
responses. Follow `next_cursor` for additional pages; the collection can change
between page requests.

</details>

## Try the endpoints

Open the [interactive reference](http://127.0.0.1:7777/) with Anki running, using
your configured port if different. Search for the native path above and use
**Test Request**. Full request bodies and response schemas are available there.
Use a disposable profile when trying note creation or suspension.

<details>
<summary>Sources and comparison details</summary>

The AnkiConnect flows follow Yomitan at
[`d34832d`](https://github.com/yomidevs/yomitan/tree/d34832d756e05dc00945e5b7d7ebc80963299a7a):

- [Duplicate detection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L651-L753)
  and [ID searches](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/comm/anki-connect.js#L308-L364).
- [Card lookup before suspension](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L808-L816).
- [Settings lists](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L439-L484)
  and [field selection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L1100-L1170).

The duplicate flow shows one existing duplicate. Yomitan sends the `findNotes`
action inside `multi`; for multiple distinct searches, it can first search their
union. Both APIs support checking a batch. Tsunagi still validates each candidate
and searches for duplicate IDs where needed; the shared setup is reused within
the request. A new word needs only the initial check in either API.

Suspension is optional. Saving alone is one request in either API. Media handling,
optional sync, connection checks and additional note/card details are omitted.
A native client must preserve the user's settings and map the request formats;
this is a comparison of selected flows, not a complete Yomitan port.

The model example omits deck loading and shows a page of models. Follow
`next_cursor` for additional pages. An AnkiConnect client can prefetch fields via
`multi`, but still needs a field-name action per model. Native `select` trims the
response; the model record itself is still loaded internally.

Implementation: [note checks and creation](../tsunagi/adapters/anki/notes.py),
[model adapters](../tsunagi/adapters/anki/models.py), and
[query planning](../tsunagi/shared/planning.py).

A disposable-collection check confirmed one note-type resolution and one deck
resolution for ten distinct duplicate candidates, plus ten duplicate-ID searches.
A native save made one `card_ids_of_note` call, no `find_cards` calls and no
`get_note` calls. These are adapter/API call counts, not SQL counts or measured
speedups.

</details>

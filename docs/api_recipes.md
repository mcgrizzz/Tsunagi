# How Tsunagi simplifies a Yomitan integration

[← Documentation](README.md) · [Install Tsunagi](../README.md#install)

You look up **食べる** in Yomitan. The popup needs to know whether you've saved it
before, which note to open if you have, and which cards were created if you save
it now. AnkiConnect can answer all of that, but some answers take a follow-up
request. The Tsunagi API returns related answers together, so an integration
needs fewer requests and less code.

> Yomitan uses AnkiConnect today, which Tsunagi supports as it is. These
> examples show what a future integration with the Tsunagi API could look like.

| When Yomitan needs to… | AnkiConnect today | A future Tsunagi API integration |
| --- | --- | --- |
| Identify an existing duplicate | Check the note → search for its ID | **One check returns both** |
| Save a note and suspend its cards | Save → find cards → suspend | **The save returns the card IDs** |
| Show a note type's fields | Get note type names → ask for the selected type's fields | **Note types come with their fields** |

The requests below are abbreviated: `{...note}` stands for the note in each
API's format, including the user's duplicate settings. AnkiConnect actions are
sent to `POST /`. Anki calls note types *models*, so that's the name in both
APIs' requests.

## 1. Check a duplicate and get its ID in one request

食べる is **already in Anki**. Yomitan marks it as a duplicate and offers to
open the saved note, so it needs that note's ID.

```text
AnkiConnect:
  canAddNotesWithErrorDetail({notes: [{...note}]})   → can't add: duplicate
  findNotes("<search built from the note>")          → the existing note IDs

Tsunagi API:
  POST /v1/notes:check {"notes": [{...note}]}
      → state: "duplicate", duplicate_note_ids: [1789200000000]
```

AnkiConnect's check only says the note is a duplicate, so Yomitan has to build
a search from it to find the existing note.

The check's IDs are the notes that make it a duplicate. With Yomitan's default
settings, those are notes of the same note type, but Yomitan lists every note
with the word, whatever its note type: after you move from one note type to a
newer one, it shows both. For that list, look the duplicates up by their first
field:

```text
GET /v1/notes?where=first_field in ["食べる"]&select=id,first_field
    → items: [{id: 1789200000000, first_field: "食べる"}, ...]
```

This uses the same index as Anki's duplicate check, so it doesn't read every
note. With "Check for duplicates across all models" on, the check's IDs
already cover every note type.

For the whole flow, checking 20 dictionary entries and listing the matches,
the [benchmarks](benchmarks.md#real-client-workloads) measured 5.7 ms with the
Tsunagi API (the check, then the notes by first field) against 188 ms with
AnkiConnect (three requests).

Within a request, Tsunagi also shares work between words. Each note names its
note type and deck as text ("Kiku+", "Mining"), and Anki has to find those
before it can check the note. When the words share a note type and deck,
Tsunagi finds them once for the whole request instead of once per word.

## 2. Save a note and suspend its cards

You save a new word with **automatic suspension** on. Yomitan needs the new
cards' IDs to suspend them.

```text
AnkiConnect:
  addNote({...note})                  → note ID
  findCards("nid:<note ID>")          → card IDs
  suspend(<card IDs>)

Tsunagi API:
  POST /v1/notes?include=cards {...note}
      → created: [{id: <note ID>, cards: [<card IDs>]}]
  POST /v1/cards:suspend {"cardIds": [<card IDs>]}
```

Saving and suspending goes from three requests to two; saving alone is one
request in either API. `?include=cards` returns the new card IDs with the
save, so there's nothing to search for. Check that `failed` is empty before
using `created[0].cards`.

## 3. Show a note type's fields

In Yomitan's settings, you pick the **Basic** note type and map dictionary
content to its **Front** and **Back** fields.

```text
AnkiConnect:
  modelNames()                        → note type names
  modelFieldNames("Basic")            → ["Front", "Back"]   (one request per selected type)

Tsunagi API:
  GET /v1/models?select=id,name,fields[].name
      → each note type with its field names
```

Picking another note type needs no further request. Ask only for what you
show: `select=id,name` skips loading full note types, and even with fields,
templates and styling stay out of the response. Decks are a separate request
in both APIs.

<details>
<summary>Also show how many notes use each note type</summary>

A picker can label a type "Basic · 250 notes" without downloading those notes:

```text
GET /v1/models?select=id,name,note_count
  → {items: [{id: 123, name: "Basic", note_count: 250}, ...], ...}
```

- `note_count` counts notes (not cards) in all decks, and is 0 for an unused
  type.
- Filter with `where=note_count>0`, or ask for fields too with
  `select=id,name,note_count,fields[].name`.
- Counts are read fresh on every request, so new notes, deletions and undo
  show up.

</details>

## Try the endpoints

With Anki running, open the [interactive reference](playground.md), search for
a path above and click **Test Request**; it has every request and response
format. [Creating notes](creating_notes.md) covers single notes, batches and
failures. Try creating and suspending in a throwaway profile.

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
A Tsunagi API client must preserve the user's settings and map the request formats;
this is a comparison of selected flows, not a complete Yomitan port.

The model example omits deck loading. An AnkiConnect client can prefetch fields via
`multi`, but still needs a field-name action per model. The Tsunagi API's `select` trims
the response; the model record itself is still loaded internally.

Implementation: [note checks](../tsunagi/adapters/anki/notes.py),
[note creation](../tsunagi/adapters/anki/note_batches.py),
[model adapters](../tsunagi/adapters/anki/models.py), and
[query planning](../tsunagi/shared/planning.py).

A disposable-collection check confirmed one note-type resolution and one deck
resolution for ten distinct duplicate candidates, plus ten duplicate-ID searches.
A Tsunagi API save requesting `include=cards` makes one `card_ids_of_note` call, no `find_cards` calls and no
`get_note` calls. These are adapter/API call counts, not SQL counts or measured
speedups.

</details>

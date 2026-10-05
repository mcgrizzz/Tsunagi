# Tsunagi TypeScript client

A typed client for [Tsunagi](https://github.com/mcgrizzz/Tsunagi/blob/main/README.md)'s API: queries with checked
field names, named values instead of Anki's codes, and writes that are keyed,
never retried by themselves, and report each item. No runtime dependencies
(Fetch, AbortSignal, Web Crypto); runs in browsers and Node.

Its major.minor is the add-on's: client 0.6.x speaks the API of Tsunagi
0.6.x. Patch versions bring client features and fixes without an add-on
release. Tsunagi's CI checks it against the real server on every push. New to Tsunagi's API? [Build your first integration](https://github.com/mcgrizzz/Tsunagi/blob/main/docs/getting_started.md)
shows the requests this client sends.

## Install

```sh
npm install tsunagi-client
```

Needs Node 22 or newer, or a current browser. Tsunagi must be running in Anki
on the computer you connect to.

<details>
<summary>Build it from the repository</summary>

For working on the client itself (needs Node, and Python 3 for the tests):

```sh
cd packages/typescript
npm install      # the build's own tools
npm test         # generates the code from Tsunagi's API description, builds dist/ and runs every test
```

</details>

## Example

Mine a word with its audio, unless the collection already has it, then read
back the cards it made:

```ts
const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:7777", apiKey: settings.apiKey });

const word = { deck: "Japanese::Mining", noteType: "Basic", fields: { Front: "犬", Back: "dog" } };
if (await anki.notes.exists(word)) {
  console.log("Already have it");
} else {
  const note = await anki.notes.create({
    ...word,
    tags: ["mined"],
    audio: [{ data: audio, filename: "inu.mp3", fields: ["Back"] }],
  }, { cards: true });

  const cards = await anki.cards
    .where("noteId", "eq", note.id)
    .select("id", "queue", "due")
    .take(10);
  console.log(cards); // [{ id, queue: "new", due }]

  if (!(await anki.access()).can(anki.cards.suspend)) console.log("This app can't suspend cards");
}
anki.close(); // access() keeps a connection open to stay current
```

## Adding notes: which method?

| You want to | Use |
| --- | --- |
| Know whether it's saved, before the user decides | `notes.exists(word)` |
| Add it, refusing a duplicate | `notes.create(word)`: a duplicate raises `ItemRejectedError` with code `duplicate` |
| Add it, or update the note you already have | `notes.upsert(word)` |
| Know why it can't be added (an empty first field, a missing cloze) | `notes.check([word])` |

`exists` and `check` change nothing. `exists` takes one note, or a list for
an answer per note; `check` takes a list.

## Where to go next

- [What changed in each version](https://github.com/mcgrizzz/Tsunagi/blob/main/packages/typescript/CHANGELOG.md).
- [`examples/`](https://github.com/mcgrizzz/Tsunagi/tree/main/packages/typescript/examples) has more, each compiled by the client's tests.
- Every resource is a query: `cards`, `notes`, `reviews`, `decks`,
  `noteTypes`, `deckPresets`, `tags`, `media`. Field names, values and sorts
  come from Tsunagi's API description (generated into `src/generated.ts` when
  you build); your editor lists them.
- `query.watch({ added, updated, removed })` keeps an app in step with a
  query as Anki changes; `cards.onAnswered`, `collection.onSync`,
  `decks.onCounts` and `onAccessChange` report events.
- `anki.raw.request()` reaches any endpoint the client doesn't cover.
- [`../spec/behavior.md`](https://github.com/mcgrizzz/Tsunagi/blob/main/packages/spec/behavior.md) is what every Tsunagi client
  does, in any language.
- [Tsunagi's documentation](https://github.com/mcgrizzz/Tsunagi/blob/main/docs/README.md) for what the server does.

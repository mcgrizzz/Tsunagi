# Tsunagi TypeScript client

A typed client for [Tsunagi](../../README.md)'s API: queries with checked
field names, named values instead of Anki's codes, and writes that are keyed,
never retried by themselves, and report each item. No runtime dependencies
(Fetch, AbortSignal, Web Crypto); runs in browsers and Node.

Not published yet. Its version is the add-on's: each Tsunagi release ships the
client it was tested against, and Tsunagi's CI checks it against the real
server on every push.

## Try it

```sh
npm install
npm test
```

Building needs Node and Python 3 (the shared test cases are built with it).

Then import `dist/index.js`.

## Example

Mine a word with its audio, unless the collection already has it, then read
back the cards it made:

```ts
const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:7777", apiKey: settings.apiKey });

const word = { deck: "Japanese::Mining", noteType: "Basic", fields: { Front: "犬", Back: "dog" } };
const [check] = await anki.notes.check([word]);
if (check?.state === "duplicate") {
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

## Where to go next

- `examples/` has more, each compiled by `npm test`.
- Every resource is a query: `cards`, `notes`, `reviews`, `decks`,
  `noteTypes`, `deckPresets`, `tags`, `media`. Field names, values and sorts
  come from Tsunagi's API description (generated into `src/generated.ts` when
  you build); your editor lists them.
- `query.watch({ added, updated, removed })` keeps an app in step with a
  query as Anki changes; `cards.onAnswered`, `collection.onSync`,
  `decks.onCounts` and `onAccessChange` report events.
- `anki.raw.request()` reaches any endpoint the client doesn't cover.
- [`../spec/behavior.md`](../spec/behavior.md) is what every Tsunagi client
  does, in any language.
- [Tsunagi's documentation](../../docs/README.md) for what the server does.

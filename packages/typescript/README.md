# Tsunagi TypeScript client

A typed client for [Tsunagi](../../README.md)'s API: queries with checked
field names, named values instead of Anki's codes, and writes that are keyed,
never retried by themselves, and report each item. No runtime dependencies
(Fetch, AbortSignal, Web Crypto); runs in browsers and Node.

Its version is the add-on's: each Tsunagi release ships the client it was
tested against, and Tsunagi's CI checks it against the real server on every
push. New to Tsunagi's API? [Build your first integration](../../docs/getting_started.md)
shows the requests this client sends.

## Install

**Not on npm yet.** Until it is, build it from this repository (needs Node):

```sh
cd packages/typescript
npm install      # the build's own tools; this doesn't install the client anywhere
npm run build    # generates the code from Tsunagi's API description and writes dist/
```

Then install this folder in your app, `npm install <path to Tsunagi>/packages/typescript`,
and import it by its current package name, `@tsunagi/client-draft`, which may
change before it's published. Run `npm run build` again after you update the
repository.

`npm test` builds it and runs every test; it also needs Python 3, which builds
the shared test cases.

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

// The README's example, compiled by `npm test` (test/readme.test.mjs keeps them the same).
import { Tsunagi } from "../src/index.js";

declare const settings: { apiKey: string };
declare const audio: Uint8Array;

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

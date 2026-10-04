// docs/events.md's example, compiled by `npm test` (test/readme.test.mjs keeps them the same).
import { Tsunagi } from "../src/index.js";

type Shown = { id: number; firstField: string };
declare const anki: Tsunagi;
declare function showAll(notes: Shown[]): void;
declare function showNotes(notes: Shown[]): void;
declare function removeNotes(ids: number[]): void;

await anki.notes.select("id", "firstField").watch({
  added: (notes, change) => (change.initial ? showAll(notes) : showNotes(notes)),
  updated: notes => showNotes(notes),
  removed: ids => removeNotes(ids),
});

// docs/api_recipes.md's example, compiled by `npm test` (test/readme.test.mjs keeps them the same).
import { Tsunagi, type NoteInput } from "../src/index.js";

declare const anki: Tsunagi;
declare const note: NoteInput;
declare function openNotes(ids: number[]): void;

// 1. Is 食べる saved already? Every note with the word, whatever its note type.
const [check] = await anki.notes.check([note], { duplicateIds: true });
const saved = await anki.notes.where("firstField", "in", ["食べる"]).select("id", "firstField").take(20);
if (check?.state === "duplicate") openNotes(saved.map(n => n.id));

// 2. Save it and suspend its cards.
const created = await anki.notes.create(note, { cards: true });
await anki.cards.suspend(created.cards ?? []);

// 3. Note types with their fields, for the settings page.
const noteTypes = await anki.noteTypes.select("id", "name", "fields").take(100);

// The repository README's example, compiled by `npm test` (test/readme.test.mjs keeps them the same).
import { Tsunagi } from "../src/index.js";

declare function show(notes: { id: number; firstField: string }[]): void;
declare function hide(ids: number[]): void;

const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:7777" });

// Anki's states by name, checked as you type: is("suspended"), is("due")...
const suspended = await anki.cards.search("deck:Mining").is("suspended").count();

// Keep a list of the deck's notes current as Anki changes, whoever changes it.
await anki.notes.search("deck:Mining").select("id", "firstField").watch({
  added: notes => show(notes),
  updated: notes => show(notes),
  removed: ids => hide(ids),
});

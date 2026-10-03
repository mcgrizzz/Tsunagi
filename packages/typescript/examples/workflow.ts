import { Tsunagi } from "../src/index.js";

/** Call explicitly with a test collection: this example creates a note and syncs. */
export async function workflow(baseUrl: string, apiKey: string, signal?: AbortSignal) {
  const anki = new Tsunagi({ baseUrl, apiKey });
  const note = await anki.notes.create({
    deck: "Default",
    noteType: "Basic",
    fields: { Front: "Draft client example", Back: "Created through Tsunagi" },
  }, { signal });
  await anki.notes.update(note.id, { fields: { Back: "Updated through Tsunagi" } }, { signal });
  const cards = await anki.cards
    .search("is:due")
    .where("interval", "gte", 30)
    .select("id", "question")
    .take(20, { signal });
  const sync = await anki.collection.sync({ signal });
  return { note, cards, sync };
}

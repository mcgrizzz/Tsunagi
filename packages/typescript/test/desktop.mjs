// The checks a test server can't make: changes reaching a watch through Anki's
// operation hooks. Run against a desktop Anki with Tsunagi, from this folder:
//   npm run build && node test/desktop.mjs http://127.0.0.1:7777 <key with write:notes>
// It adds one note tagged tsunagi-desktop-check to the Default deck, changes it,
// and deletes it.
import assert from "node:assert/strict";
import { Tsunagi } from "../dist/index.js";

const [baseUrl = "http://127.0.0.1:7777", apiKey] = process.argv.slice(2);
const anki = new Tsunagi({ baseUrl, apiKey });
const tag = "tsunagi-desktop-check";
const heard = [];
let notify = () => {};
const record = name => (items, change) => { heard.push({ name, items, change }); notify(); };
const next = async name => {
  const deadline = Date.now() + 10_000;
  while (true) {
    const at = heard.findIndex(entry => entry.name === name);
    if (at !== -1) return heard.splice(at, 1)[0];
    if (Date.now() > deadline) throw new Error(`No ${name} within 10 s; heard ${JSON.stringify(heard)}`);
    await new Promise(resolve => { notify = resolve; setTimeout(resolve, 200); });
  }
};

const watching = await anki.notes.search(`tag:${tag}`).select("firstField", "tags")
  .watch({ added: record("added"), updated: record("updated"), removed: record("removed") });
assert.deepEqual(heard, [], `notes tagged ${tag} are left from an earlier run: delete them first`);

const note = await anki.notes.create({ deck: "Default", noteType: "Basic", fields: { Front: "desktop check" }, tags: [tag] });
const added = await next("added");
assert.deepEqual([added.items[0].id, added.change.by], [note.id, "api"]);
console.log("added: ok");

await anki.notes.update(note.id, { fields: { Front: "desktop check, edited" } });
assert.equal((await next("updated")).items[0].firstField, "desktop check, edited");
console.log("updated: ok");

await anki.notes.update(note.id, { removeTags: [tag] });
assert.deepEqual((await next("removed")).items, [note.id]);
console.log("removed when it lost the tag: ok");

await anki.notes.update(note.id, { addTags: [tag] });
await next("added");
await anki.notes.delete([note.id]);
assert.deepEqual((await next("removed")).items, [note.id]);
console.log("removed when deleted: ok");

watching.stop();
anki.close();
console.log("DESKTOP OK");

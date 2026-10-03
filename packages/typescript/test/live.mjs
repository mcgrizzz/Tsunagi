// The built client against a real Tsunagi: node test/live.mjs <server root>.
// Run by Tsunagi's tests/test_typescript_client.py, which starts the server on
// a throwaway collection, waits for "WATCHING", then changes this app's role.
import assert from "node:assert/strict";
import { Tsunagi } from "../dist/index.js";

const anki = new Tsunagi({ baseUrl: process.argv[2] });
const viaPost = new Tsunagi({ baseUrl: process.argv[2], maxGetUrlLength: 60 }); // POST /query

const access = await anki.access();
assert.equal(access.caller.name, "No key, this computer");
assert.equal(access.check(anki.notes.create).status, "available");

const ids = [];
for (const front of ["apple", "banana", "carrot"]) {
  ids.push((await anki.notes.create({ deck: "Default", noteType: "Basic", fields: { Front: front, Back: "x" }, tags: ["live"] })).id);
}
const report = await anki.notes.createMany([
  { deck: "Default", noteType: "Basic", fields: { Front: "date" } },
  { deck: "Default", noteType: "Basic", fields: { Front: "apple" } },
], { onError: "collect" });
assert.deepEqual(report.items.map(item => item.ok ? "ok" : item.error.code), ["ok", "duplicate"]);
await anki.notes.update(ids[0], { fields: { Back: "A" }, addTags: ["checked"] });

for (const client of [anki, viaPost]) {
  const names = (await client.notes.where("first_field", "contains", "a").where("first_field", "ne", "banana")
    .select("first_field").take(10)).map(note => note.first_field);
  assert.deepEqual(names.sort(), ["apple", "carrot", "date"]);
  const seen = [];
  for await (const note of client.notes.select("first_field").iterate({ size: 2 })) seen.push(note.first_field);
  assert.deepEqual(seen.sort(), ["apple", "banana", "carrot", "date"]);
}
const [first] = await anki.notes.where("id", "eq", ids[0]).select("fields", "tags", "model_id").take(1);
assert.deepEqual(first.fields.map(field => [field.name, field.value]), [["Front", "apple"], ["Back", "A"]]);
assert.deepEqual([...first.tags].sort(), ["checked", "live"]);
for (const sort of ["id", "note_modified", "sort_field"]) await anki.notes.orderBy(sort, "desc").values("id").take(4);

const [card] = await anki.cards.select("id", "note_id", "deck_id", "interval", "due", "queue", "reps", "lapses",
  "deck_name", "question", "answer").take(1);
assert.equal(card.deck_name, "Default");
for (const sort of ["due", "interval", "reps", "lapses"]) await anki.cards.orderBy(sort).values("id").take(4);
assert.equal((await anki.cards.distinctOn("note_id").values("note_id").take(10)).length, 4);
assert.equal((await anki.cards.search("is:new").values("id").take(10)).length, 4);

assert.equal((await anki.raw.request("DELETE", `/v1/notes/${ids[2]}`)).status, 200);
assert.equal((await anki.notes.values("id").take(10)).length, 3);

// Access follows a role change: Default can't see card answers, Everything can.
const answers = state => state.access.capabilities.operations["GET /v1/events"].options["cards.answered"].status;
const watching = AbortSignal.timeout(20_000);
let announced = false;
for await (const state of anki.watchAccess({ signal: watching, backoffMs: 50 })) {
  if (state.status !== "ready") continue;
  if (!announced) {
    assert.equal(answers(state), "disabled");
    console.log("WATCHING");
    announced = true;
  } else if (answers(state) === "available") {
    assert.equal(state.access.caller.role, "Everything");
    console.log("LIVE OK");
    process.exit(0);
  }
}
throw new Error("watchAccess never saw the role change");

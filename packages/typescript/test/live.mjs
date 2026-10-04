// The built client against a real Tsunagi: node test/live.mjs <server root>.
// Run by Tsunagi's tests/test_typescript_client.py, which starts the server on
// a throwaway collection, waits for "WATCHING", then changes this app's role.
import assert from "node:assert/strict";
import { Tsunagi } from "../dist/index.js";
import { resources } from "../dist/generated.js";

let reports = 0;  // capabilities requests: the access cache should spare most
const counting = (url, init) => { if (new URL(url).pathname.endsWith("/v1/capabilities")) reports++; return fetch(url, init); };
const anki = new Tsunagi({ baseUrl: process.argv[2], fetch: counting });
const viaPost = new Tsunagi({ baseUrl: process.argv[2], maxGetUrlLength: 60, keepAccess: false }); // POST /query

const access = await anki.access();
assert.equal(access.caller.name, "No key, this computer");
assert.equal(access.caller.key, "none");
assert.equal(access.check(anki.notes.create).status, "available");
assert.equal((await anki.health()).collection.state, "ready");

const ids = [];
for (const front of ["apple", "banana", "carrot"]) {
  ids.push((await anki.notes.create({ deck: "Default", noteType: "Basic", fields: { Front: front, Back: "x" }, tags: ["live"] })).id);
}
const report = await anki.notes.createMany([
  { deck: "Default", noteType: "Basic", fields: { Front: "date" }, audio: [{ data: new Uint8Array([1, 2, 3]), filename: "date.mp3", fields: ["Back"] }] },
  { deck: "Default", noteType: "Basic", fields: { Front: "apple" } },
], { onError: "collect", cards: true, duplicateIds: true });
assert.deepEqual(report.items.map(item => item.ok ? "ok" : item.error.code), ["ok", "duplicate"]);
assert.equal(report.items[0].value.files[0].filename, "date.mp3");
assert.equal(report.items[0].value.cards.length, 1);
assert.deepEqual(report.items[1].error.duplicateNoteIds, [ids[0]]);
await anki.notes.update(ids[0], { fields: { Back: "A" }, addTags: ["checked"] });
const [check] = await anki.notes.check([{ deck: "Default", noteType: "Basic", fields: { Front: "banana" } }], { duplicateIds: true });
assert.deepEqual([check.state, check.duplicateNoteIds], ["duplicate", [ids[1]]]);
const upserted = await anki.notes.upsert({ deck: "Default", noteType: "Basic", fields: { Front: "banana", Back: "B" }, fieldRules: { Back: "replace" } });
assert.deepEqual([upserted.action, upserted.id, upserted.fieldsChanged], ["updated", ids[1], ["Back"]]);

for (const client of [anki, viaPost]) {
  const names = (await client.notes.where("firstField", "contains", "a").where("firstField", "ne", "banana")
    .select("firstField").take(10)).map(note => note.firstField);
  assert.deepEqual(names.sort(), ["apple", "carrot", "date"]);
  const seen = [];
  for await (const note of client.notes.select("firstField").iterate({ size: 2 })) seen.push(note.firstField);
  assert.deepEqual(seen.sort(), ["apple", "banana", "carrot", "date"]);
}
const [first] = await anki.notes.where("id", "eq", ids[0]).select("fields", "tags", "noteTypeId").take(1);
assert.deepEqual(first.fields.map(field => [field.name, field.value, field.index]), [["Front", "apple", 0], ["Back", "A", 1]]);
assert.deepEqual([...first.tags].sort(), ["checked", "live"]);
assert.equal(await anki.notes.where("firstField", "in", ["apple", "date"]).count(), 2);
assert.equal(await anki.notes.where("firstField", "startsWith", "ca").where("firstField", "endsWith", "ot").count(), 1);

// Every resource reads whole rows, and each sort is one the server takes.
for (const [name, resource] of Object.entries(resources)) {
  if (name === "addons") continue;
  await anki[name].take(100);
  for (const sort of Object.keys(resource.sorts)) await anki[name].orderBy(sort, "desc").take(1);
}

const cardIds = await anki.cards.values("id").take(10);
await anki.cards.setFlag(cardIds.slice(0, 1), "green");
await anki.cards.suspend(cardIds.slice(1, 2));
assert.deepEqual(await anki.cards.where("flag", "eq", "green").values("id").take(10), cardIds.slice(0, 1));
assert.deepEqual(await anki.cards.where("queue", "eq", "suspended").values("id").take(10), cardIds.slice(1, 2));
await anki.cards.answer([{ cardId: cardIds[2], rating: "good" }]);
const [review] = await anki.reviews.distinctOn("cardId").orderBy("id", "desc").select("cardId", "rating", "type").take(5);
assert.deepEqual(review, { cardId: cardIds[2], rating: "good", type: "learning" });
assert.equal((await anki.cards.distinctOn("noteId").values("noteId").take(10)).length, 4);
assert.equal((await anki.cards.search("is:new").values("id").take(10)).length, 3);

// A watch's first load: every row matching, in client names, through pages.
// (Changes reach a watch through Anki's operation hooks, which only real Anki
// fires: the shared scenarios cover them, and the owner's desktop check.)
let loaded;
const watching = await anki.notes.search("tag:live").select("firstField").watch({ added: (rows, change) => { loaded = [rows, change]; } });
assert.deepEqual(loaded[0].map(note => note.firstField).sort(), ["apple", "banana", "carrot"]);
assert.ok(loaded[0].every(note => typeof note.id === "number"));
assert.equal(loaded[1].initial, true);
const changes = await anki.notes.onChange(() => {});
watching.stop();
changes.stop();
await watching.done;

const stored = await anki.media.upload({ filename: "live.txt", data: new TextEncoder().encode("hi") });
assert.equal(stored.size, 2);
assert.deepEqual(await anki.notes.delete([ids[2]]), { affected: 1 });
assert.equal(await anki.notes.count(), 3);

// Access is answered from the cache, and follows a role change: Default can't
// see card answers, Everything can.
const answers = access => access.capabilities.operations["GET /v1/events"].options["cards.answered"].status;
const before = await anki.access();
const counted = reports;
assert.equal((await anki.access()).caller.role, before.caller.role);
assert.equal(reports, counted, "a second access() made a request");
assert.equal(answers(before), "disabled");
let seeChange;
const changed = new Promise(resolve => { seeChange = resolve; });
await anki.onAccessChange(access => { if (answers(access) === "available") seeChange(access); });
console.log("WATCHING");
const after = await Promise.race([changed, new Promise((_, reject) => setTimeout(() => reject(new Error("onAccessChange never saw the role change")), 20_000))]);
assert.equal(after.caller.role, "Everything");
assert.equal((await anki.access()).caller.role, "Everything");
// Card answers, which the Everything role may hear.
let heard;
const answered = new Promise(resolve => { heard = resolve; });
await anki.cards.onAnswered(answer => heard(answer));
const [newCard] = await anki.cards.where("queue", "eq", "new").values("id").take(1);
await anki.cards.answer([{ cardId: newCard, rating: "easy" }]);
const answer = await answered;
assert.deepEqual([answer.cardId, answer.rating, answer.by, answer.app], [newCard, "easy", "api", "No key, this computer"]);
anki.close();
console.log("LIVE OK");
process.exit(0);

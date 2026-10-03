import assert from "node:assert/strict";
import { test } from "node:test";
import { Tsunagi, AuthenticationError, PermissionError, HttpError, ProtocolError } from "../dist/index.js";

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json" },
});
const state = (status = "available", setting = null, reason = null) => ({ status, setting, reason });
const operation = (status = "available", setting = null, reason = null, options = {}) => ({
  ...state(status, setting, reason), operation_id: "fixture_operation", options,
});
function report(role = "Custom role") {
  return {
    versions: { api: "v1", addon: "0.4.0", anki: "25.09" },
    caller: { name: "No key, this computer", role, this_computer: true, host: "127.0.0.1" },
    operations: {
      "GET /v1/cards": operation(),
      "GET /v1/notes": operation(),
      "POST /v1/notes": operation("disabled", "permissions.write:notes", "Allow write:notes in this app's role in Tsunagi settings"),
      "PATCH /v1/notes/{id}": operation(),
      "POST /v1/collection:sync": operation("unsupported", null, "Unavailable in this Anki version"),
      "POST /v1/media": operation("available", null, null, {
        path: state("disabled", "permissions.local_files", "Allow local_files in Tsunagi settings"),
      }),
    },
    features: { fsrs_scheduling: state("disabled", "anki.fsrs", "FSRS is not enabled") },
  };
}

test("construction is lazy; optional API keys send no header during access discovery", async () => {
  const calls = [];
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:12345/proxy/",
    fetch: async (url, init) => { calls.push({ url: new URL(url), ...init }); return json(report()); },
  });
  assert.equal(calls.length, 0);
  const access = await anki.access();
  assert.equal(access.caller.role, "Custom role");
  assert.equal(access.caller.name, "No key, this computer");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, "/proxy/v1/capabilities");
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].headers.has("X-Api-Key"), false);
  assert.equal(calls[0].headers.has("Idempotency-Key"), false);
});

test("checks use effective operation states, even when the role is named Everything", async () => {
  const anki = new Tsunagi({ baseUrl: "http://localhost/", fetch: async () => json(report("Everything")) });
  const access = await anki.access();
  assert.equal(access.can("cards.query"), true);
  assert.equal(access.can("notes.create"), false);
  assert.deepEqual(access.check("notes.create"), {
    operation: "POST /v1/notes", option: null, allowed: false, status: "disabled",
    setting: "permissions.write:notes", permission: "write:notes",
    reason: "Allow write:notes in this app's role in Tsunagi settings",
  });
  assert.deepEqual(access.check("notes.createMany"), access.check("notes.create"));
  assert.equal(access.check("notes.update").operation, "PATCH /v1/notes/{id}");
  assert.equal(access.check("collection.sync").status, "unsupported");
  assert.deepEqual(access.check("collection.startSync"), access.check("collection.sync"));
  assert.throws(() => access.can("write:notes"), TypeError);
  assert.throws(() => access.can("toString"), TypeError);
});

test("option-level permissions and missing reports are distinguishable", async () => {
  const data = report();
  data.operations["POST /v1/blocked"] = operation("disabled", "permissions.write:cards", "No card writes", { permitted: state() });
  const anki = new Tsunagi({ baseUrl: "http://localhost/", fetch: async () => json(data) });
  const access = await anki.access();
  assert.equal(access.operation("POST /v1/media").allowed, true);
  const local = access.operation("POST /v1/media", "path");
  assert.equal(local.allowed, false);
  assert.equal(local.permission, "local_files");
  assert.equal(local.setting, "permissions.local_files");
  assert.equal(access.operation("POST /v1/blocked", "permitted").allowed, false);
  for (const decision of [access.operation("GET /v1/missing"), access.operation("POST /v1/media", "not_reported"), access.operation("toString")]) {
    assert.equal(decision.status, "unknown");
    assert.equal(decision.allowed, false);
    assert.equal(decision.permission, null);
  }
  assert.equal(access.capabilities.features.fsrs_scheduling.setting, "anki.fsrs");
});

test("access refreshes on each call, respects rotating credentials, and retains immutable older snapshots", async () => {
  const keys = [];
  let apiKey;
  const anki = new Tsunagi({
    baseUrl: "http://localhost/", apiKey: () => apiKey,
    fetch: async (_url, init) => {
      keys.push(init.headers.get("X-Api-Key"));
      const data = report(apiKey ? "Writer" : "Reader");
      if (apiKey) data.operations["POST /v1/notes"] = operation();
      return json(data);
    },
  });
  const before = await anki.access();
  apiKey = "new-app-key";
  const after = await anki.access();
  assert.deepEqual(keys, [null, "new-app-key"]);
  assert.equal(before.can("notes.create"), false);
  assert.equal(after.can("notes.create"), true);
  assert.equal(before.caller.role, "Reader");
  assert.equal(after.caller.role, "Writer");
  assert.throws(() => { before.caller.role = "Everything"; }, TypeError);
  assert.throws(() => { before.capabilities.operations["POST /v1/notes"].status = "available"; }, TypeError);
  assert.throws(() => { before.check("notes.create").allowed = true; }, TypeError);
});

test("ordinary calls have no permission preflight and expose actual 403 denials without retrying", async () => {
  const calls = [];
  const detail = "Reader has the role 'Read only', which does not allow write:notes; change it in Tsunagi's settings";
  const anki = new Tsunagi({
    baseUrl: "http://localhost/",
    fetch: async (url, init) => { calls.push({ url: new URL(url), ...init }); return json({ detail }, 403); },
  });
  await assert.rejects(anki.notes.update(1, { fields: { Front: "a" } }), error => {
    assert.ok(error instanceof PermissionError);
    assert.ok(error instanceof HttpError);
    assert.equal(error.status, 403);
    assert.equal(error.detail, detail);
    assert.equal(error.message.includes(detail), false);
    assert.equal(error.reason, undefined);
    return true;
  });
  assert.deepEqual(calls.map(call => [call.method, call.url.pathname]), [["PATCH", "/v1/notes/1"]]);
});

test("401 and 403 have distinct errors and preserve non-JSON proxy responses", async () => {
  for (const [status, ErrorClass] of [[401, AuthenticationError], [403, PermissionError]]) {
    for (const body of [true, false]) {
      const anki = new Tsunagi({
        baseUrl: "http://localhost/",
        fetch: async () => body ? json({ detail: "Access denied" }, status) : new Response("Proxy denied access", { status }),
      });
      await assert.rejects(anki.access(), error => {
        assert.ok(error instanceof ErrorClass);
        assert.equal(error.status, status);
        assert.equal(error.detail, body ? "Access denied" : undefined);
        assert.deepEqual(error.body, body ? { detail: "Access denied" } : "Proxy denied access");
        return true;
      });
    }
  }
});

test("standard error detail, reason and validation problems remain accessible without message parsing", async () => {
  const problem = { loc: ["body", "fields"], msg: "Field required", type: "missing" };
  const anki = new Tsunagi({
    baseUrl: "http://localhost/",
    fetch: async () => json({ detail: "Invalid request", reason: "invalid", errors: [problem] }, 422),
  });
  await assert.rejects(anki.raw.request("PATCH", "/v1/notes/1", { body: {} }), error => {
    assert.ok(error instanceof HttpError);
    assert.equal(error.detail, "Invalid request");
    assert.equal(error.reason, "invalid");
    assert.deepEqual(error.errors, [problem]);
    return true;
  });
});

test("capabilities are decoded and malformed permission reports cannot imply access", async () => {
  for (const mutate of [
    data => { data.caller.this_computer = "true"; },
    data => { data.operations["POST /v1/notes"].status = "maybe"; },
    data => { data.operations["POST /v1/notes"].reason = {}; },
    data => { delete data.operations; },
  ]) {
    const data = report();
    mutate(data);
    const anki = new Tsunagi({ baseUrl: "http://localhost/", fetch: async () => json(data) });
    await assert.rejects(anki.access(), ProtocolError);
  }
  const anki = new Tsunagi({ baseUrl: "http://localhost/", fetch: async () => json(report()) });
  assert.equal((await anki.capabilities()).caller.role, "Custom role");
});

test("query access follows builder transformations and fetches discovery without executing the query", async () => {
  const calls = [];
  const anki = new Tsunagi({
    baseUrl: "http://localhost/",
    fetch: async (url, init) => { calls.push([init.method, new URL(url).pathname]); return json(report()); },
  });
  const query = anki.cards.search("is:due").where("interval", "gte", 30).select("id").orderBy("due").distinctOn("id");
  assert.equal(calls.length, 0);
  assert.equal((await query.checkAccess()).allowed, true);
  assert.deepEqual(calls, [["GET", "/v1/capabilities"]]);
  const access = await anki.access();
  assert.equal(access.check(query.values("id")).operation, "GET /v1/cards");
  assert.equal(access.can(anki.notes), true);
  assert.equal(access.can(anki.notes.create), false);
  assert.deepEqual(access.check(anki.notes.createMany), access.check(anki.notes.create));
  assert.equal(access.check(anki.notes.update).operation, "PATCH /v1/notes/{id}");
  assert.equal(access.check(anki.collection.sync).status, "unsupported");
  assert.deepEqual(access.check(anki.collection.startSync), access.check(anki.collection.sync));
  assert.equal(calls.length, 2);
});

test("bulk checks use one discovery snapshot, retain every named decision, and perform no writes", async () => {
  let requests = 0;
  const anki = new Tsunagi({ baseUrl: "http://localhost/", fetch: async () => { requests++; return json(report()); } });
  const access = await anki.access();
  const batch = access.checkMany({
    dueCards: anki.cards.search("is:due").select("id"),
    addNote: anki.notes.create,
    sync: anki.collection.sync,
  });
  assert.equal(requests, 1);
  assert.equal(batch.allowed, false);
  assert.deepEqual(Object.keys(batch.checks), ["dueCards", "addNote", "sync"]);
  assert.equal(batch.checks.dueCards.allowed, true);
  assert.equal(batch.checks.addNote.permission, "write:notes");
  assert.equal(batch.checks.sync.status, "unsupported");
  assert.equal(access.checkMany({ cards: anki.cards, notes: anki.notes }).allowed, true);
  assert.equal(access.checkMany({}).allowed, true);
  assert.throws(() => { batch.checks.addNote.allowed = true; }, TypeError);
});

test("snapshots reject foreign and fabricated targets and do not serialize client credentials", async () => {
  const anki = new Tsunagi({ baseUrl: "http://localhost/", apiKey: "never-log-this-key", fetch: async () => json(report()) });
  const other = new Tsunagi({ baseUrl: "http://other-server/", fetch: async () => json(report()) });
  const access = await anki.access();
  for (const target of [other.cards, other.notes.create, {}, () => {}, Promise.resolve([])]) {
    assert.throws(() => access.check(target), TypeError);
  }
  assert.throws(() => access.checkMany({ wrongClient: other.notes.update }), TypeError);
  assert.equal(JSON.stringify(access).includes("never-log-this-key"), false);
  assert.deepEqual(Object.keys(access), ["capabilities"]);
});

test("method references remain bound and callable after checking access", async () => {
  const calls = [];
  const anki = new Tsunagi({
    baseUrl: "http://localhost/",
    fetch: async (url, init) => {
      calls.push([init.method, new URL(url).pathname]);
      if (init.method === "GET") {
        const data = report();
        data.operations["POST /v1/notes"] = operation();
        return json(data);
      }
      return json({ created: [{ index: 0, id: 123 }], failed: [] });
    },
  });
  const create = anki.notes.create;
  const access = await anki.access();
  assert.equal(access.can(create), true);
  assert.deepEqual(await create({ deck: "Default", noteType: "Basic", fields: { Front: "a" } }), { id: 123 });
  assert.deepEqual(calls, [["GET", "/v1/capabilities"], ["POST", "/v1/notes"]]);
});

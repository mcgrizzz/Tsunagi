import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import {
  Tsunagi, HttpError, JobFailedError, JobWaitTimeoutError, PartialWriteError,
  RequestTimeoutError, WriteOutcomeUnknownError,
} from "../dist/index.js";

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json" },
});
const page = (items, next_cursor = null) => json({ items, next_cursor, stats: {} });
const input = () => ({ deck: "Japanese", noteType: "Basic", fields: { Front: "食べる", Back: "to eat" } });
function fixture(responses, options = {}) {
  const calls = [];
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:12345/proxy/",
    apiKey: "secret-key",
    fetch: async (url, init) => {
      const call = { url: new URL(url), ...init };
      calls.push(call);
      assert.ok(responses.length, "unexpected extra request");
      const response = responses.shift();
      return typeof response === "function" ? response(call) : response;
    },
    ...options,
  });
  return { anki, calls };
}

test("queries are lazy and immutable; string filters are quoted and repeated", async () => {
  const { anki, calls } = fixture([page([{ id: 1 }]), page([{ id: 2 }])]);
  const base = anki.cards.select("id");
  const value = 'Japanese "quotes" \\ slash\n猫';
  const filtered = base.where("deckName", "eq", value).where("interval", "gt", 1);
  assert.equal(calls.length, 0);
  await filtered.take(1);
  await base.take(1);
  assert.deepEqual(calls[0].url.searchParams.getAll("where"), [`deck_name==${JSON.stringify(value)}`, "interval>1"]);
  assert.deepEqual(calls[1].url.searchParams.getAll("where"), []);
});

test("page defaults are bounded, cursor/query are retained, end returns null", async () => {
  const { anki, calls } = fixture([page([{ id: 1 }], "opaque +/="), page([{ id: 2 }])]);
  const first = await anki.cards.search("is:due").select("id").page();
  assert.equal(first.hasMore, true);
  assert.equal(calls[0].url.searchParams.get("limit"), "50");
  const second = await first.next();
  assert.deepEqual(second.items, [{ id: 2 }]);
  assert.equal(calls[1].url.searchParams.get("cursor"), "opaque +/=");
  assert.equal(calls[1].url.searchParams.get("search"), "is:due");
  assert.equal(await second.next(), null);
  assert.equal(calls.length, 2);
});

test("iterate follows an empty page with a cursor and never prefetches after break", async () => {
  const { anki, calls } = fixture([page([], "one"), page([{ id: 2 }, { id: 3 }], "two")]);
  for await (const item of anki.cards.select("id").iterate()) {
    assert.equal(item.id, 2);
    break;
  }
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url.searchParams.get("limit"), "100");
});

test("bulk failures retain successes, restore input order, and support explicit collection", async () => {
  const response = () => json({ created: [{ index: 2, id: 12 }, { index: 0, id: 10 }], failed: [{ index: 1, code: "invalid_note", message: "Bad note" }] });
  const { anki, calls } = fixture([response(), response()]);
  await assert.rejects(anki.notes.createMany([input(), input(), input()]), error => {
    assert.ok(error instanceof PartialWriteError);
    assert.deepEqual(error.report.items.map(item => item.index), [0, 1, 2]);
    assert.equal(error.report.items[2].value.id, 12);
    return true;
  });
  const report = await anki.notes.createMany([input(), input(), input()], { onError: "collect" });
  assert.deepEqual(report.items.map(item => item.ok), [true, false, true]);
  assert.notEqual(calls[0].headers.get("Idempotency-Key"), calls[1].headers.get("Idempotency-Key"));
});

test("body is serialized before asynchronous credentials; keys can rotate", async () => {
  const note = input();
  let key = "first";
  const { anki, calls } = fixture([json({ created: [{ index: 0, id: 1 }], failed: [] }), page([1])], {
    apiKey: async () => { note.fields.Front = "mutated"; return key; },
  });
  await anki.notes.create(note, { idempotencyKey: "stable" });
  key = "second";
  await anki.cards.values("id").take(1);
  assert.equal(JSON.parse(calls[0].body)[0].fields.Front, "食べる");
  assert.equal(calls[0].headers.get("X-Api-Key"), "first");
  assert.equal(calls[1].headers.get("X-Api-Key"), "second");
});

test("lost writes and 503s retain identity and are never automatically retried", async () => {
  for (const response of [() => { throw new TypeError("connection lost"); }, json({ detail: "busy", reason: "busy" }, 503)]) {
    const { anki, calls } = fixture([response]);
    await assert.rejects(anki.notes.create(input(), { idempotencyKey: "edit-1" }), error => {
      assert.ok(error instanceof WriteOutcomeUnknownError);
      assert.equal(error.idempotencyKey, "edit-1");
      return true;
    });
    assert.equal(calls.length, 1);
  }
});

test("HTTP conflicts and proxy errors preserve status/body without logging data", async () => {
  const { anki } = fixture([json({ detail: "private field" }, 409), new Response("proxy error", { status: 502 })]);
  await assert.rejects(anki.notes.create(input()), error => error instanceof HttpError && error.status === 409 && !error.message.includes("private field"));
  await assert.rejects(anki.health(), error => error instanceof HttpError && error.status === 502 && error.body === "proxy error");
});

test("pre-aborted writes send nothing; in-flight cancellation retains uncertainty", async () => {
  const controller = new AbortController();
  const reason = new Error("stop");
  controller.abort(reason);
  const first = fixture([]);
  await assert.rejects(first.anki.notes.create(input(), { signal: controller.signal }), error => error === reason);
  assert.equal(first.calls.length, 0);
  const inFlight = new AbortController();
  const second = fixture([() => { inFlight.abort(reason); return new Promise(() => {}); }]);
  await assert.rejects(second.anki.notes.create(input(), { signal: inFlight.signal }), error => error instanceof WriteOutcomeUnknownError && error.cause === reason);
});

test("read deadlines bound stuck fetch and credential providers", async () => {
  const stuck = fixture([() => new Promise(() => {})]);
  await assert.rejects(stuck.anki.health({ timeoutMs: 20 }), RequestTimeoutError);
  const credentials = fixture([], { apiKey: () => new Promise(() => {}) });
  await assert.rejects(credentials.anki.health({ timeoutMs: 20 }), RequestTimeoutError);
  assert.equal(credentials.calls.length, 0);
});

test("sync hides 202/polling and returns the same result as immediate completion", async () => {
  const result = { status: 0, server_message: "", stats: {} };
  const slow = fixture([
    json({ job_id: "abc", status: "running", stats: {} }, 202),
    json({ id: "abc", kind: "sync", stats: {}, status: "running", result: null, error: null }),
    json({ id: "abc", kind: "sync", stats: {}, status: "done", result, error: null }),
  ]);
  const fast = fixture([json(result)]);
  assert.deepEqual(await slow.anki.collection.sync({ pollIntervalMs: 1 }), await fast.anki.collection.sync());
  assert.equal(slow.calls.filter(call => call.method === "POST").length, 1);
  assert.equal(slow.calls[1].url.pathname, "/proxy/v1/jobs/abc");
});

test("waiting twice or resuming a wait never submits a new sync", async () => {
  const controller = new AbortController();
  const reason = new Error("leave this screen");
  const { anki, calls } = fixture([
    json({ job_id: "abc", status: "queued", stats: {} }, 202),
    () => { controller.abort(reason); return new Promise(() => {}); },
    json({ id: "abc", kind: "sync", stats: {}, status: "done", result: { status: 1, server_message: "done" }, error: null }),
  ]);
  const operation = await anki.collection.startSync();
  assert.equal(operation.abortable, false);
  await assert.rejects(operation.wait({ signal: controller.signal }), error => error === reason);
  assert.equal((await operation.wait()).status, 1);
  assert.equal((await operation.wait()).status, 1);
  assert.equal(calls.length, 3);
  assert.equal(calls.filter(call => call.method === "POST").length, 1);
});

test("overall wait timeout carries a resumable handle; job failure is distinct", async () => {
  const { anki } = fixture([
    json({ job_id: "abc", status: "queued", stats: {} }, 202),
    () => new Promise(() => {}),
    json({ id: "abc", kind: "sync", stats: {}, status: "failed", error: "Sync failed", result: null }),
  ]);
  let operation;
  await assert.rejects(anki.collection.sync({ waitTimeoutMs: 20 }), error => {
    assert.ok(error instanceof JobWaitTimeoutError);
    operation = error.operation;
    return true;
  });
  await assert.rejects(operation.wait(), error => error instanceof JobFailedError && error.detail === "Sync failed");
});

test("raw access is scoped to the configured root and uses no redirects", async () => {
  const { anki, calls } = fixture([json({ custom: true })]);
  for (const path of ["https://example.com/v1/cards", "/v1/../../outside", "/v1/cards?api_key=bad"]) {
    await assert.rejects(anki.raw.request("GET", path), TypeError);
  }
  const response = await anki.raw.request("GET", "/v1/capabilities");
  assert.deepEqual(response.data, { custom: true });
  assert.equal(calls[0].redirect, "error");
  assert.equal(calls[0].credentials, "omit");
});

test("raw access reaches DELETE routes as a write", async () => {
  const { anki, calls } = fixture([json({ success: true, affected_ids: [1] })]);
  const response = await anki.raw.request("DELETE", "/v1/notes/1", { idempotencyKey: "delete-1" });
  assert.deepEqual(response.data, { success: true, affected_ids: [1] });
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].headers.get("Idempotency-Key"), "delete-1");
});

test("real HTTP transport completes the draft workflow against a local protocol fixture", async t => {
  const received = [];
  const server = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    received.push({ method: req.method, url: req.url, key: req.headers["x-api-key"], body });
    res.setHeader("content-type", "application/json");
    const url = new URL(req.url, "http://localhost");
    let response;
    if (req.method === "POST" && url.pathname === "/v1/notes") response = { created: [{ id: 7, index: 0 }], failed: [] };
    else if (req.method === "PATCH") response = { result: true, stats: {} };
    else if (url.pathname === "/v1/cards") response = { items: [{ id: 8, question: "hello" }], next_cursor: null, stats: {} };
    else if (url.pathname === "/v1/collection:sync") { res.statusCode = 202; response = { job_id: "local", status: "queued", stats: {} }; }
    else response = { id: "local", kind: "sync", stats: {}, status: "done", result: { status: 0, server_message: "" }, error: null };
    res.end(JSON.stringify(response));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  const anki = new Tsunagi({ baseUrl: `http://127.0.0.1:${server.address().port}`, apiKey: "local-key" });
  const note = await anki.notes.create(input());
  await anki.notes.update(note.id, { fields: { Back: "updated" } });
  assert.deepEqual(await anki.cards.select("id", "question").take(20), [{ id: 8, question: "hello" }]);
  assert.equal((await anki.collection.sync()).status, 0);
  assert.equal(received.length, 5);
  assert.ok(received.every(call => call.key === "local-key"));
});

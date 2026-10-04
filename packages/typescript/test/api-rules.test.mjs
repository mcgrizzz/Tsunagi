import assert from "node:assert/strict";
import { test } from "node:test";
import { Tsunagi, HttpError, ProtocolError, WriteOutcomeUnknownError } from "../dist/index.js";

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json" },
});

test("sync submits with an idempotency key and polls the accepted job without resubmitting", async () => {
  const calls = [];
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:12345/",
    makeIdempotencyKey: () => "sync-submission-key",
    fetch: async (url, init) => {
      calls.push({ url: new URL(url), ...init });
      return init.method === "POST"
        ? json({ job_id: "sync-1", status: "queued", stats: {} }, 202)
        : json({ id: "sync-1", kind: "sync", stats: {}, status: "done", result: { status: 0, server_message: "" }, error: null });
    },
  });
  assert.deepEqual(await anki.collection.sync(), { status: 0, serverMessage: "" });
  assert.deepEqual(calls.map(call => [call.method, call.url.pathname]), [
    ["POST", "/v1/collection:sync"], ["GET", "/v1/jobs/sync-1"],
  ]);
  assert.equal(calls[0].headers.get("Idempotency-Key"), "sync-submission-key");
  assert.equal(calls[1].headers.has("Idempotency-Key"), false);
});

test("sync accepts supplied keys for deliberate recovery using the current server contract", async () => {
  const keys = [];
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:12345/",
    makeIdempotencyKey: () => { throw new Error("Keep the supplied key"); },
    fetch: async (_url, init) => { keys.push(init.headers.get("Idempotency-Key")); return json({ status: 0, server_message: "" }); },
  });
  const operation = await anki.collection.startSync({ idempotencyKey: "saved-sync" });
  await operation.wait();
  await anki.collection.sync({ idempotencyKey: "saved-sync" });
  assert.deepEqual(keys, ["saved-sync", "saved-sync"]);
});

test("uncertain sync submissions retain their cause and key without automatic retry", async t => {
  const dropped = new TypeError("Connection dropped after submission");
  const cases = [
    ["lost response", () => { throw dropped; }, error => assert.equal(error.cause, dropped)],
    ["503", () => json({ detail: "Anki is busy", reason: "busy" }, 503), error => {
      assert.ok(error.cause instanceof HttpError);
      assert.equal(error.cause.status, 503);
    }],
    ["missing job receipt", () => json({}, 202), error => assert.ok(error.cause instanceof ProtocolError)],
  ];
  for (const [name, respond, checkCause] of cases) {
    await t.test(name, async () => {
      let calls = 0;
      const anki = new Tsunagi({
        baseUrl: "http://127.0.0.1:12345/",
        makeIdempotencyKey: () => "uncertain-sync-key",
        fetch: async () => { calls++; return respond(); },
      });
      await assert.rejects(anki.collection.sync(), error => {
        assert.ok(error instanceof WriteOutcomeUnknownError);
        assert.equal(error.idempotencyKey, "uncertain-sync-key");
        assert.match(error.message, /Preserve/);
        checkCause(error);
        return true;
      });
      assert.equal(calls, 1);
    });
  }
});

test("raw writes require an explicit key and still report uncertain completion without one", async () => {
  const keys = [];
  const dropped = new TypeError("Lost response");
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:12345/",
    makeIdempotencyKey: () => { throw new Error("Raw routes have unverified replay coverage"); },
    fetch: async (_url, init) => { keys.push(init.headers.get("Idempotency-Key")); throw dropped; },
  });
  for (const key of [undefined, "explicit-key"]) {
    await assert.rejects(anki.raw.request("POST", "/v1/notes", { body: [], idempotencyKey: key }), error => {
      assert.ok(error instanceof WriteOutcomeUnknownError);
      assert.equal(error.idempotencyKey, key);
      assert.equal(error.cause, dropped);
      return true;
    });
  }
  assert.deepEqual(keys, [null, "explicit-key"]);
});

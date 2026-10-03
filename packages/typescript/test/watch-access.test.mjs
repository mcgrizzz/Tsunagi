import assert from "node:assert/strict";
import { test } from "node:test";
import { AuthenticationError, Tsunagi } from "../dist/index.js";

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json" },
});
const report = role => ({
  versions: { api: "v1", addon: "0.5.1", anki: "26.09.2" },
  caller: { name: "Yomine", role, enabled: true, key: "valid", this_computer: true, host: "127.0.0.1" },
  operations: {}, features: {},
});

/** A fake Tsunagi: each GET /v1/events opens a stream the test writes frames to. */
function server({ roles = ["Default", "Read-only", "Everything"], holdReports = false } = {}) {
  const streams = [];
  const reports = [];
  const encoder = new TextEncoder();
  const fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === "/v1/events") {
      let controller;
      const body = new ReadableStream({ start(c) { controller = c; } });
      const stream = {
        query: new URL(url).searchParams.get("types"),
        send(event, data) { controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)); },
        end() { controller.close(); },
        aborted: () => init.signal.aborted,
      };
      init.signal.addEventListener("abort", () => { try { controller.error(init.signal.reason); } catch {} });
      streams.push(stream);
      return new Response(body, { headers: { "content-type": "text/event-stream" } });
    }
    if (path === "/v1/capabilities") {
      const answer = json(report(roles[Math.min(reports.length, roles.length - 1)]));
      if (!holdReports) { reports.push(null); return answer; }
      return new Promise(resolve => reports.push(() => resolve(answer)));
    }
    throw new Error(`unexpected ${path}`);
  };
  return { fetch, streams, reports };
}

const tick = (ms = 5) => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, ms = 2_000) {
  const end = Date.now() + ms;
  while (!check()) { if (Date.now() > end) throw new Error("timed out"); await tick(); }
}

/** Collect states in the background; the test reads `states` as they arrive. */
function watch(anki, options = {}) {
  const controller = new AbortController();
  const states = [];
  const done = (async () => {
    for await (const state of anki.watchAccess({ signal: controller.signal, backoffMs: 1, ...options })) {
      states.push(state);
    }
  })();
  return { states, done, stop: () => controller.abort() };
}
const roles = states => states.filter(s => s.status === "ready").map(s => s.access.caller.role);

test("fetches the report after connecting and again on access.changed", async () => {
  const fake = server();
  const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:1/", fetch: fake.fetch });
  const w = watch(anki);
  await until(() => fake.streams.length === 1);
  assert.equal(fake.streams[0].query, "access.changed");
  assert.equal(w.states[0].status, "loading");
  fake.streams[0].send("ready", { type: "ready", heartbeat_ms: 15000 });
  await until(() => roles(w.states).length === 1);
  fake.streams[0].send("access.changed", { type: "access.changed", ts: 1 });
  await until(() => roles(w.states).length === 2);
  assert.deepEqual(roles(w.states), ["Default", "Read-only"]);
  w.stop();
  await w.done;
  assert.ok(fake.streams[0].aborted());
});

test("notifications during a fetch collapse into one more fetch", async () => {
  const fake = server({ holdReports: true });
  const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:1/", fetch: fake.fetch });
  const w = watch(anki);
  await until(() => fake.streams.length === 1);
  fake.streams[0].send("ready", { type: "ready" });
  await until(() => fake.reports.length === 1);
  for (let i = 0; i < 3; i++) fake.streams[0].send("access.changed", { type: "access.changed", ts: i });
  await tick(20);
  fake.reports[0]();
  await until(() => fake.reports.length === 2);
  fake.reports[1]();
  await until(() => roles(w.states).length === 1);
  await tick(20);
  assert.equal(fake.reports.length, 2);
  assert.deepEqual(roles(w.states), ["Read-only"]);  // only the fresh report counts as ready
  w.stop();
  await w.done;
});

test("a close with reason auth reconnects and fetches again", async () => {
  const fake = server();
  const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:1/", fetch: fake.fetch });
  const w = watch(anki);
  await until(() => fake.streams.length === 1);
  fake.streams[0].send("ready", { type: "ready" });
  await until(() => roles(w.states).length === 1);
  fake.streams[0].send("access.changed", { type: "access.changed", ts: 1 });
  fake.streams[0].send("close", { reason: "auth" });
  await until(() => fake.streams.length === 2);
  assert.ok(w.states.some(s => s.status === "reconnecting" && s.access !== null));
  fake.streams[1].send("ready", { type: "ready" });
  await until(() => roles(w.states).length >= 2 && fake.reports.length >= 3);
  w.stop();
  await w.done;
});

test("silence for three heartbeats reconnects", async () => {
  const fake = server();
  const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:1/", fetch: fake.fetch });
  const w = watch(anki);
  await until(() => fake.streams.length === 1);
  fake.streams[0].send("ready", { type: "ready", heartbeat_ms: 10 });
  await until(() => fake.streams.length === 2);
  assert.ok(fake.streams[0].aborted());
  w.stop();
  await w.done;
});

test("a refused key ends the watch with AuthenticationError", async () => {
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:1/",
    fetch: async () => json({ detail: "Invalid or missing API key" }, 401),
  });
  await assert.rejects(async () => {
    for await (const _ of anki.watchAccess({ backoffMs: 1 })) { /* loading */ }
  }, AuthenticationError);
});

test("an aborted signal ends the watch without opening a stream", async () => {
  const fake = server();
  const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:1/", fetch: fake.fetch });
  const states = [];
  for await (const state of anki.watchAccess({ signal: AbortSignal.abort() })) states.push(state);
  assert.deepEqual(states, []);
  assert.equal(fake.streams.length, 0);
});

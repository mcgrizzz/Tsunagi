// Listening behavior that depends on the language's scheduling; the rest is in packages/spec/cases.
import assert from "node:assert/strict";
import { test } from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import { Tsunagi } from "../dist/index.js";

const settle = async () => { for (let i = 0; i < 100; i++) await tick(); };
const json = data => new Response(JSON.stringify(data), { headers: { "content-type": "application/json" } });

/** A client whose event stream the test writes to; other requests answer `answer(url)`. */
function fixture(answer = () => json({ items: [], next_cursor: null, stats: {} })) {
  let stream;
  const anki = new Tsunagi({
    baseUrl: "http://127.0.0.1:7777/",
    fetch: async (url, init) => {
      if (new URL(url).pathname === "/v1/events") {
        const body = new ReadableStream({ start: controller => { stream = controller; } });
        init.signal.addEventListener("abort", () => { try { stream.error(init.signal.reason); } catch { /* closed */ } });
        return new Response(body, { headers: { "content-type": "text/event-stream" } });
      }
      return answer(url);
    },
  });
  let seq = 0;
  const send = (event, data) => stream.enqueue(new TextEncoder().encode(
    `event: ${event}\ndata: ${JSON.stringify({ type: event, seq: ++seq, session_id: "s", ts: 1, ...data })}\n\n`));
  const ready = resources => stream.enqueue(new TextEncoder().encode(`event: ready\ndata: ${JSON.stringify(
    { type: "ready", session_id: "s", after_seq: 0, ts: 1, resources, heartbeat_ms: 15000 })}\n\n`));
  return { anki, send, ready };
}

test("onChange: changes during a running call make one more call afterwards", async () => {
  const { anki, send, ready } = fixture();
  let calls = 0;
  let finish;
  const subscribing = anki.notes.onChange(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
  await settle();
  ready(["notes"]);
  await subscribing;
  send("notes.created", { ids: [1] });
  await settle();
  send("notes.updated", { ids: [1] });
  send("notes.updated", { ids: [2] });
  await settle();
  assert.equal(calls, 1);
  finish();
  await settle();
  assert.equal(calls, 2);
  finish();
  await settle();
  assert.equal(calls, 2);
  anki.close();
});

test("a watch handler that throws ends the watch with its error", async () => {
  const { anki, send, ready } = fixture(url => json({
    items: new URL(url).searchParams.has("where") ? [{ first_field: "b", id: 2 }] : [{ first_field: "a", id: 1 }],
    next_cursor: null, stats: {},
  }));
  const failure = new Error("app bug");
  const watching = anki.notes.select("firstField").watch({ added: (rows, change) => { if (!change.initial) throw failure; } });
  await settle();
  ready(["notes"]);
  const subscription = await watching;
  send("notes.created", { ids: [2], origin: "ui" });
  await assert.rejects(subscription.done, error => error === failure);
  anki.close();
});

test("aborting a subscription's signal stops it", async () => {
  const { anki, ready } = fixture();
  const controller = new AbortController();
  const subscribing = anki.decks.onCounts(() => {}, { signal: controller.signal });
  await settle();
  ready(["decks"]);
  const subscription = await subscribing;
  controller.abort();
  assert.equal(await subscription.done, undefined);
  anki.close();
});

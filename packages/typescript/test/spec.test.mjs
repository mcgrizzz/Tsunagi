// Runs the shared conformance cases (packages/spec/cases) against this client.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import {
  Tsunagi, AuthenticationError, HttpError, ItemRejectedError, JobFailedError,
  PartialWriteError, PermissionError, ProtocolError, WriteOutcomeUnknownError,
} from "../dist/index.js";

const folder = new URL("../../spec/cases/", import.meta.url);
const files = readdirSync(folder).filter(name => name.endsWith(".json"));
const base = "http://127.0.0.1:7777/";

/** Arguments as this client takes them: {"$bytes": base64} is a Uint8Array. */
function argument(value) {
  if (Array.isArray(value)) return value.map(argument);
  if (value && typeof value === "object") {
    if (Object.keys(value).length === 1 && "$bytes" in value) return Uint8Array.from(Buffer.from(value.$bytes, "base64"));
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, argument(item)]));
  }
  return value;
}

function kind(error) {
  if (error instanceof TypeError || error instanceof RangeError) return "argument";
  if (error instanceof AuthenticationError) return "authentication";
  if (error instanceof PermissionError) return "permission";
  if (error instanceof HttpError) return "http";
  if (error instanceof WriteOutcomeUnknownError) return "outcomeUnknown";
  if (error instanceof ItemRejectedError) return "itemRejected";
  if (error instanceof PartialWriteError) return "partialWrite";
  if (error instanceof JobFailedError) return "jobFailed";
  if (error instanceof ProtocolError) return "protocol";
  throw error;
}

async function run(anki, call) {
  if (call.query) {
    let query = anki[call.query];
    for (const [method, ...args] of call.steps) query = query[method](...argument(args));
    const [runner, options = {}] = call.run;
    if (runner === "take") return query.take(options);
    if (runner === "count") return query.count();
    if (runner === "openBrowser") return query.openBrowser(options);
    if (runner === "page") {
      const page = await query.page(options);
      return { items: page.items, hasMore: page.hasMore, total: page.total };
    }
    if (runner === "pages") {
      const items = [];
      for (let page = await query.page(options); page; page = await page.next()) items.push(...page.items);
      return items;
    }
    throw new Error(`Unknown runner ${runner}`);
  }
  const path = call.method.split(".");
  const owner = path.slice(0, -1).reduce((object, key) => object[key], anki);
  return owner[path.at(-1)](...argument(call.args));
}

function checkRequest(expected, url, init) {
  if ("key" in expected) assert.equal(init.headers.get("X-Api-Key"), expected.key);
  const actual = new URL(url);
  assert.equal(init.method, expected.method);
  assert.equal(actual.href.slice(base.length - 1, actual.href.length - actual.search.length), expected.path);
  const query = {};
  for (const key of new Set(actual.searchParams.keys())) {
    const values = actual.searchParams.getAll(key);
    query[key] = Array.isArray(expected.query?.[key]) ? values : values.join("\n");
  }
  assert.deepEqual(query, expected.query ?? {});
  if ("body" in expected) assert.deepEqual(JSON.parse(init.body), expected.body);
  else assert.equal(init.body, undefined);
  const key = init.headers.get("Idempotency-Key");
  if (expected.keyed === true) assert.ok(key);
  else if (expected.keyed === false) assert.equal(key, null);
  else if (typeof expected.keyed === "string") assert.equal(key, expected.keyed);
}

const respond = ({ status, body, text }) => text !== undefined ? new Response(text, { status })
  : new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function outcomeOf(spec, promise) {
  return promise.then(result => ({ result }), error => ({
    error: Object.assign({ kind: kind(error) }, ...Object.keys(spec.error ?? {}).filter(key => key !== "kind").map(key => ({ [key]: error[key] }))),
  }));
}
function compare(spec, outcome) {
  if ("error" in spec) assert.deepEqual(outcome, { error: spec.error });
  else assert.deepEqual(JSON.parse(JSON.stringify({ result: project(outcome.result) ?? null })), { result: spec.result ?? null });
}
/** An access snapshot is compared as its caller's role (cases/README.md). */
function project(value) {
  if (value && typeof value === "object" && "capabilities" in value && "caller" in value) return { role: value.caller.role };
  if (Array.isArray(value)) return value.map(project);
  return value;
}

async function runExchanges(spec) {
  const exchanges = [...spec.exchanges];
  const anki = new Tsunagi({
    baseUrl: base, ...spec.client,
    fetch: async (url, init) => {
      const exchange = exchanges.shift();
      assert.ok(exchange, `unexpected request ${init.method} ${url}`);
      checkRequest(exchange.request, url, init);
      return respond(exchange.response);
    },
  });
  const outcome = await outcomeOf(spec, run(anki, spec.call));
  assert.equal(exchanges.length, 0, "requests the case expects were not made");
  compare(spec, outcome);
}

async function runScript(spec, t) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const settle = async () => { for (let i = 0; i < 200; i++) await tick(); };
  const pending = [];
  let stream = null;
  let key = "k1";
  const anki = new Tsunagi({
    baseUrl: base, apiKey: () => key, ...spec.client,
    fetch: (url, init) => new Promise((resolve, reject) => {
      const entry = { url, init, resolve };
      pending.push(entry);
      init.signal?.addEventListener("abort", () => {
        const at = pending.indexOf(entry);
        if (at !== -1) pending.splice(at, 1);
        reject(init.signal.reason);
      }, { once: true });
    }),
  });
  const calls = {};
  const heard = {};
  try {
    for (const step of spec.script) {
      await settle();
      if (step.call) {
        let args = argument(step.call.args ?? []);
        if (step.listener) {
          const record = heard[step.listener] = [];
          // watch and onSync take named handlers, recorded as [name, ...arguments]; others one function.
          const named = { watch: ["added", "updated", "removed"], onSync: ["started", "finished"] }[step.call.method.split(".").at(-1)];
          const listener = named
            ? Object.fromEntries(named.map(name => [name, (...values) => record.push([name, ...values])])
              .concat([["error", error => record.push(["error", kind(error)])]]))
            : (...values) => record.push(values.length > 1 ? values.map(project) : project(values[0]) ?? null);
          args = [listener, ...args];
        }
        let root = anki;
        if (step.call.query) {
          root = { query: anki[step.call.query] };
          for (const [method, ...rest] of step.call.steps ?? []) root.query = root.query[method](...argument(rest));
        }
        const path = (step.call.query ? "query." : "") + step.call.method;
        const owner = path.split(".").slice(0, -1).reduce((object, name) => object[name], root);
        const method = path.split(".").at(-1);
        let value;
        try { value = owner[method](...args); } catch (error) { value = Promise.reject(error); }
        if (value instanceof Promise) value.catch(() => {});  // settled later by a `settle` step
        calls[step.as] = value;
      } else if (step.expect) {
        const at = pending.findIndex(entry => entry.init.method === step.expect.method
          && new URL(entry.url).pathname === new URL(step.expect.path.slice(1), base).pathname);
        assert.notEqual(at, -1, `expected ${step.expect.method} ${step.expect.path}; pending: ${pending.map(entry => entry.url)}`);
        const [entry] = pending.splice(at, 1);
        checkRequest(step.expect, entry.url, entry.init);
        if (step.stream) {
          const body = new ReadableStream({ start: controller => { stream = controller; } });
          // As a real fetch does: aborting the request fails its body.
          const controller = stream;
          entry.init.signal?.addEventListener("abort", () => {
            try { controller.error(entry.init.signal.reason); } catch { /* already closed */ }
            if (stream === controller) stream = null;
          }, { once: true });
          entry.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
        } else entry.resolve(respond(step.response));
      } else if (step.send) {
        for (const message of step.send) {
          const text = message.comment !== undefined ? `: ${message.comment}\n\n`
            : `event: ${message.event}\ndata: ${JSON.stringify(message.data ?? {})}\n\n`;
          stream.enqueue(new TextEncoder().encode(text));
        }
      } else if (step.end) {
        stream.close();
        stream = null;
      } else if (step.wait) {
        t.mock.timers.tick(step.wait);
      } else if (step.quiet) {
        assert.deepEqual(pending.map(entry => `${entry.init.method} ${entry.url}`), []);
      } else if (step.settle) {
        const call = calls[step.settle];
        const outcome = await outcomeOf(step, step.done ? (await call).done : call);
        if (step.ok) assert.ok(!("error" in outcome), `${step.settle} failed: ${JSON.stringify(outcome)}`);
        else compare(step, outcome);
      } else if (step.heard) {
        assert.deepEqual(heard[step.heard], step.calls);
        heard[step.heard].length = 0;
      } else if (step.setKey) {
        key = step.setKey;
      } else if (step.close) {
        anki.close();
      } else if (step.stop) {
        (await calls[step.stop]).stop();
      } else throw new Error(`Unknown step ${JSON.stringify(step)}`);
    }
    await settle();
    assert.deepEqual(pending.map(entry => `${entry.init.method} ${entry.url}`), [], "requests the script didn't expect");
  } finally {
    anki.close();
    stream?.close();
  }
}

for (const file of files) {
  for (const spec of JSON.parse(readFileSync(new URL(file, folder), "utf8")).cases) {
    test(`${file}: ${spec.name}`, t => spec.script ? runScript(spec, t) : runExchanges(spec));
  }
}

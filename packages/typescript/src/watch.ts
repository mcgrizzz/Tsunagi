import { decodeAs } from "./decode.js";
import { AuthenticationError, PermissionError, ProtocolError } from "./errors.js";
import { events } from "./generated.js";
import type { EventConnection, Signal } from "./events.js";
import type { DraftProtocol, QueryParams } from "./protocol.js";
import { Subscription } from "./subscription.js";

/** Who made a change, when the server said (packages/spec/behavior.md, Watching a query). */
export interface Change {
  /** The first load. */
  readonly initial: boolean;
  readonly by: "ui" | "api" | null;
  /** The app that made it, for `by: "api"`. */
  readonly app: string | null;
}
export interface WatchHandlers<Row, Key> {
  /** The first load (`change.initial`), new rows, and rows that now match. */
  added?(rows: Row[], change: Change): void;
  /** Rows whose selected values changed. */
  updated?(rows: Row[], change: Change): void;
  /** Rows deleted, or that no longer match. */
  removed?(keys: Key[], change: Change): void;
  /** The error that ended the watch. Without it, the subscription's `done` rejects. */
  error?(error: unknown): void;
}

/** What the watch needs from its query. */
export interface Watched {
  readonly protocol: DraftProtocol;
  readonly connection: EventConnection;
  readonly path: string;
  /** The resource's event name: the path's last part, with _ for - (note_types). */
  readonly events: string;
  readonly key: string;           // client name
  readonly keyWire: string;
  readonly search: string | undefined;
  readonly selected: readonly string[] | null;  // client names; null for all
  /** Other resources whose changes can change its rows: the description's x-from, for its search and selected fields. */
  readonly related: readonly string[];
  /** The query's parameters, narrowed by more filters or a replacement search. */
  params(narrow: { where?: readonly string[]; search?: string }): QueryParams;
  decode(row: unknown): Record<string, unknown>;
}

const PAGE = 2_000;
const FIRST_DELAY = 1_000;
const LONGEST_DELAY = 30_000;

/** A 53-bit hash of a row as the server sent it (cyrb53). */
function fingerprint(row: unknown): number {
  const text = JSON.stringify(row);
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

/** A handler raised: the watch ends with its error. */
class HandlerFailure extends Error {
  constructor(readonly cause: unknown) { super("A watch handler raised"); }
}

type Origin = { by: "ui" | "api" | null; app: string | null };
const unknown: Origin = { by: null, app: null };
const originOf = (message: Readonly<Record<string, unknown>>): Origin => {
  const by = message.origin === "ui" || message.origin === "api" ? message.origin : null;
  return { by, app: by === "api" && typeof message.client === "string" ? message.client : null };
};
const tag = (origin: Origin) => `${origin.by}\u0000${origin.app}`;

/** Messages gathered while the watch was busy. */
class Pending {
  reread = false;
  check = new Map<unknown, Origin>();
  deleted = new Map<unknown, Origin>();
  viaCards = new Map<unknown, Origin>();   // card ids on a notes watch
  viaNotes = new Map<unknown, Origin>();   // note ids on a cards watch
  get empty(): boolean {
    return !this.reread && !this.check.size && !this.deleted.size && !this.viaCards.size && !this.viaNotes.size;
  }
}

export function watch<Row, Key>(handlers: WatchHandlers<Row, Key>, watched: Watched, signal?: AbortSignal): Promise<Subscription> {
  const subscription = new Subscription(signal);
  const seen = new Map<unknown, number>();
  let pending = new Pending();
  let busy = false;
  let loaded = false;
  let waitingForReady = true;
  let delay = FIRST_DELAY;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let first!: { resolve: () => void; reject: (error: unknown) => void };
  const started = new Promise<Subscription>((resolve, reject) => {
    first = { resolve: () => resolve(subscription), reject };
  });

  const own = watched.events;
  const resources = [own, ...watched.related];
  const fail = (error: unknown) => {
    if (!subscription.active) return;
    if (!loaded) first.reject(error);
    else if (handlers.error) { try { handlers.error(error); } catch { /* the watch is ending anyway */ } }
    subscription.end(handlers.error || !loaded ? undefined : error);
  };

  const hear = (signal: Signal) => {
    if (signal.kind === "ready") {
      if (!signal.resources.includes(own)) {
        fail(new PermissionError(403, { detail: `This app may not read ${own}.` }, "/v1/events", undefined));
        return;
      }
      waitingForReady = false;
      pending.reread = true;
    } else if (signal.kind === "down") {
      // Never connected: fail the awaited watch rather than wait forever.
      if (!loaded && waitingForReady && !signal.deliberate) { fail(signal.error); return; }
      waitingForReady = true;
      return;
    } else if (signal.kind === "gap") {
      pending.reread = true;
    } else if (signal.kind === "message") {
      gather(signal.message);
    } else return;
    work();
  };

  const gather = (raw: Readonly<Record<string, unknown>>) => {
    const type = String(raw.type);
    const entry = Object.hasOwn(events, type) ? events[type as keyof typeof events] : undefined;
    // The connection is shared: only this watch's resources count.
    if (!entry || !("resource" in entry) || !resources.includes(entry.resource)) return;
    const message = decodeAs<{ ids?: number[]; by?: Origin["by"]; app?: string | null; decks?: { deckId: number }[] }>(entry.schema, raw);
    const resource = entry.resource;
    const kind = type.slice(resource.length + 1);
    const origin: Origin = { by: message.by ?? null, app: message.app ?? null };
    const ids = message.ids ?? [];
    if (kind === "stale") { pending.reread = true; return; }
    if (resource === own) {
      if (kind === "deleted") {
        for (const id of ids) { pending.deleted.set(id, origin); pending.check.delete(id); }
      } else if (kind === "created" || kind === "updated") {
        for (const id of ids) if (!pending.deleted.has(id)) pending.check.set(id, origin);
      } else if (kind === "counts") {
        for (const deck of message.decks ?? []) pending.check.set(deck.deckId, origin);
      }
    } else if (own === "notes" && resource === "cards") {
      for (const id of ids) pending.viaCards.set(id, origin);
    } else if (own === "cards" && resource === "notes") {
      for (const id of ids) pending.viaNotes.set(id, origin);
    }
  };

  /** One request per page: the rows matching the query, plus a key filter. */
  const read = async (narrow: { where?: readonly string[]; search?: string }) => {
    const rows: unknown[] = [];
    let cursor: string | null = null;
    const seenCursors = new Set<string>();
    do {
      const page = await watched.protocol.query(watched.path, watched.params(narrow), PAGE, cursor, {});
      rows.push(...page.items);
      cursor = page.cursor;
      if (cursor !== null) {
        if (seenCursors.has(cursor)) throw new ProtocolError("Server repeated a pagination cursor");
        seenCursors.add(cursor);
      }
    } while (cursor !== null);
    return rows;
  };
  const values = async (path: string, params: QueryParams) => {
    const out: unknown[] = [];
    let cursor: string | null = null;
    do {
      const page = await watched.protocol.query(path, params, PAGE, cursor, {});
      out.push(...page.items);
      cursor = page.cursor;
    } while (cursor !== null);
    return out;
  };
  const list = (keys: Iterable<unknown>) => `[${[...keys].map(key => JSON.stringify(key)).join(",")}]`;
  /**
   * The query restricted to some keys. With a search on notes or cards, the
   * ids go into the search (nid:, cid:), so Anki narrows before searching;
   * otherwise a filter on the key.
   */
  const narrowTo = (keys: Iterable<unknown>) => {
    const by = { notes: "nid", cards: "cid" }[own];
    if (watched.search !== undefined && by) return { search: `(${watched.search}) ${by}:${[...keys].join(",")}` };
    return { where: [`${watched.keyWire} in${list(keys)}`] };
  };

  type Changes = { removed: Map<unknown, Origin>; updated: Map<Row, Origin>; added: Map<Row, Origin> };
  const changes = (): Changes => ({ removed: new Map(), updated: new Map(), added: new Map() });

  /** Calls in the order removed, updated, added; once per origin. A handler that raises ends the watch. */
  const deliver = (found: Changes, initial: boolean) => {
    for (const [name, entries] of [["removed", found.removed], ["updated", found.updated], ["added", found.added]] as const) {
      const groups = new Map<string, { origin: Origin; items: unknown[] }>();
      for (const [item, origin] of entries) {
        if (!groups.has(tag(origin))) groups.set(tag(origin), { origin, items: [] });
        groups.get(tag(origin))!.items.push(item);
      }
      for (const { origin, items } of groups.values()) {
        if (!subscription.active) return;
        const handler = handlers[name] as ((items: unknown[], change: Change) => void) | undefined;
        try { handler?.(items, { initial: initial && name === "added", by: origin.by, app: origin.app }); }
        catch (error) { throw new HandlerFailure(error); }
      }
    }
  };

  /** Compare rows read now with what was seen; `keys` limits the comparison to those keys. */
  const compare = (found: Changes, rows: unknown[], keys: Map<unknown, Origin> | null) => {
    const now = new Map<unknown, unknown>();
    for (const raw of rows) now.set(watched.decode(raw)[watched.key], raw);
    for (const [key, raw] of now) {
      const origin = keys?.get(key) ?? unknown;
      const print = fingerprint(raw);
      const before = seen.get(key);
      if (before === undefined) found.added.set(watched.decode(raw) as Row, origin);
      else if (before !== print) found.updated.set(watched.decode(raw) as Row, origin);
      seen.set(key, print);
    }
    for (const key of keys ? [...keys.keys()] : [...seen.keys()]) {
      if (!now.has(key) && seen.delete(key)) found.removed.set(key, keys?.get(key) ?? unknown);
    }
  };

  const step = async (batch: Pending) => {
    const found = changes();
    if (batch.reread) {
      const initial = !loaded;
      compare(found, await read({}), null);
      deliver(found, initial);
      if (initial) { loaded = true; first.resolve(); }
      return;
    }
    const check = new Map(batch.check);
    if (batch.viaCards.size) {
      const ids = await values("/v1/notes", { select: "id", shape: "scalar", where: [], search: `cid:${[...batch.viaCards.keys()].join(",")}` });
      const origin = [...batch.viaCards.values()].at(-1)!;
      for (const id of ids) if (!check.has(id) && !batch.deleted.has(id)) check.set(id, origin);
    }
    if (batch.viaNotes.size) {
      const ids = await values("/v1/cards", { select: "id", shape: "scalar", where: [`note_id in${list(batch.viaNotes.keys())}`] });
      const origin = [...batch.viaNotes.values()].at(-1)!;
      for (const id of ids) if (!check.has(id) && !batch.deleted.has(id)) check.set(id, origin);
    }
    if (check.size) compare(found, await read(narrowTo(check.keys())), check);
    for (const [key, origin] of batch.deleted) if (seen.delete(key)) found.removed.set(key, origin);
    deliver(found, false);
  };

  const work = () => {
    if (busy || retry || waitingForReady || !subscription.active || pending.empty) return;
    if (!loaded && !pending.reread) return;  // the first load comes first
    busy = true;
    const batch = pending;
    pending = new Pending();
    step(batch).then(() => {
      delay = FIRST_DELAY;
      busy = false;
      work();
    }, error => {
      busy = false;
      if (error instanceof HandlerFailure) { fail(error.cause); return; }
      if (!loaded || error instanceof AuthenticationError || error instanceof PermissionError || error instanceof ProtocolError) {
        fail(error);
        return;
      }
      // Anything else may pass: read everything again, later.
      pending.reread = true;
      retry = setTimeout(() => { retry = undefined; work(); }, delay);
      delay = Math.min(delay * 2, LONGEST_DELAY);
    });
  };

  const leave = watched.connection.join({
    need: { resources },
    hear: signal => {
      try { hear(signal); } catch (error) { fail(error); }
    },
    end: fail,
  });
  subscription.onEnd(() => { clearTimeout(retry); leave(); });
  if (watched.connection.carries({ resources })) hear({ kind: "ready", resources: watched.connection.resources });
  return started;
}

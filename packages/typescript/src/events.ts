import { decodeAs } from "./decode.js";
import { AuthenticationError, PermissionError } from "./errors.js";
import type { Close, Ready } from "./generated.js";
import type { Transport } from "./transport.js";

/** What a listener needs the connection to carry. */
export interface Need {
  readonly resources?: readonly string[];
  /** Non-data types: cards.answered, sync. */
  readonly types?: readonly string[];
}

/** What a listener hears. A data message is the server's JSON, with `type`. */
export type Signal =
  | { readonly kind: "ready"; readonly resources: readonly string[] }
  | { readonly kind: "message"; readonly message: Readonly<Record<string, unknown>> }
  | { readonly kind: "gap" }
  | { readonly kind: "accessChanged" }
  /** `deliberate`: the client reconnects on purpose (a new need or key), not a failure. */
  | { readonly kind: "down"; readonly error: unknown; readonly deliberate: boolean };

export interface Listener {
  readonly need: Need;
  hear(signal: Signal): void;
  /** The connection can't serve this listener any more (401, or 403 for data). */
  end(error: unknown): void;
}

interface Frame { event: string; data: unknown }

/** Server-Sent Events frames from a fetch body; anything received counts as activity. */
async function* frames(body: ReadableStream<Uint8Array>, activity: () => void): AsyncGenerator<Frame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      activity();
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let event: string | null = null;
        let data: unknown = null;
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data = JSON.parse(line.slice(6));
        }
        if (event !== null) yield { event, data };
      }
    }
  } finally { reader.releaseLock(); }
}

const FIRST_DELAY = 1_000;
const LONGEST_DELAY = 30_000;

/**
 * The client's one connection to GET /v1/events, carrying the union of what
 * its listeners need (packages/spec/behavior.md, The event connection).
 */
export class EventConnection {
  private readonly listeners = new Set<Listener>();
  private carrying = "";        // the query the open connection was made with
  private current: AbortController | null = null;
  private running: Promise<void> | null = null;
  private wake: (() => void) | null = null;
  private closed = false;
  private soon = false;         // reconnect without the usual delay
  /** True between a `ready` and the connection dropping or being replaced. */
  up = false;
  /** What the last `ready` said the stream carries (resources the app may read). */
  resources: readonly string[] = [];

  constructor(private readonly transport: Transport) {}

  /** Whether the open connection already carries this need: a joining listener then gets no new `ready`. */
  carries(need: Need): boolean {
    const query = new URLSearchParams(this.carrying);
    const resources = query.get("resources")?.split(",") ?? [];
    const types = query.get("types")?.split(",") ?? [];
    return this.up && (need.resources ?? []).every(resource => resources.includes(resource))
      && (need.types ?? []).every(type => types.includes(type));
  }

  join(listener: Listener): () => void {
    if (this.closed) throw new TypeError("This client is closed");
    this.listeners.add(listener);
    this.update();
    return () => { if (this.listeners.delete(listener)) this.update(); };
  }

  /** Connect again (a new key): listeners see the drop and the new ready. */
  reconnect(): void {
    this.soon = true;
    this.current?.abort();
  }

  close(): void {
    this.closed = true;
    this.listeners.clear();
    this.update();
  }

  private query(): URLSearchParams {
    const resources = new Set<string>();
    const types = new Set<string>();
    for (const { need } of this.listeners) {
      need.resources?.forEach(resource => resources.add(resource));
      need.types?.forEach(type => types.add(type));
    }
    const query = new URLSearchParams();
    if (resources.size) {
      query.set("resources", [...resources].sort().join(","));
      query.set("types", ["change", ...[...types].sort()].join(","));
    } else {
      query.set("types", types.size ? [...types].sort().join(",") : "access.changed");
    }
    return query;
  }

  private update(): void {
    if (!this.listeners.size) {
      this.carrying = "";
      this.current?.abort();
      this.wake?.();
      return;
    }
    const wanted = this.query().toString();
    if (wanted === this.carrying) return;
    this.carrying = wanted;
    this.up = false;  // being replaced: listeners hear a new ready
    if (this.running) { this.current?.abort(); this.wake?.(); }
    else this.running = this.run().finally(() => { this.running = null; });
  }

  private tell(signal: Signal): void {
    for (const listener of [...this.listeners]) listener.hear(signal);
  }

  private async run(): Promise<void> {
    let delay = FIRST_DELAY;
    while (this.listeners.size && !this.closed) {
      const connection = this.current = new AbortController();
      const query = new URLSearchParams(this.carrying);
      let heartbeat = 15_000;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const activity = () => {
        clearTimeout(timer);
        timer = setTimeout(() => connection.abort(new Error("No heartbeat")), heartbeat * 3);
      };
      let error: unknown = new Error("The event stream ended");
      let now = false;  // reconnect without waiting
      try {
        const body = await this.transport.stream("/v1/events", query, connection.signal);
        activity();
        for await (const frame of frames(body, activity)) {
          const data = (frame.data ?? {}) as Record<string, unknown>;
          if (frame.event === "ready") {
            const ready = decodeAs<Ready>("Ready", data);
            if (ready.heartbeatMs > 0) heartbeat = ready.heartbeatMs;
            activity();
            delay = FIRST_DELAY;
            this.up = true;
            this.resources = ready.resources;
            this.tell({ kind: "ready", resources: ready.resources });
          } else if (frame.event === "access.changed") {
            this.tell({ kind: "accessChanged" });
          } else if (frame.event === "gap") {
            this.tell({ kind: "gap" });
          } else if (frame.event === "close") {
            const { reason } = decodeAs<Close>("Close", data);
            error = new Error(`The event stream closed (${reason})`);
            now = reason === "auth";
            break;
          } else {
            this.tell({ kind: "message", message: data });
          }
        }
      } catch (caught) {
        if (caught instanceof AuthenticationError) {
          for (const listener of [...this.listeners]) { this.listeners.delete(listener); listener.end(caught); }
        } else if (caught instanceof PermissionError) {
          // Only data needs read permission; access.changed alone needs none.
          for (const listener of [...this.listeners]) {
            if (listener.need.resources?.length || listener.need.types?.length) { this.listeners.delete(listener); listener.end(caught); }
          }
          this.carrying = this.listeners.size ? this.query().toString() : "";
          now = true;
        }
        error = caught;
      } finally {
        clearTimeout(timer);
        connection.abort();
      }
      this.up = false;
      if (!this.listeners.size || this.closed) return;
      // A changed need or key aborts the connection on purpose: reconnect at once.
      if (query.toString() !== this.carrying || this.soon) now = true;
      const deliberate = this.soon || query.toString() !== this.carrying;
      this.soon = false;
      this.tell({ kind: "down", error, deliberate });
      if (!now) {
        const wait = delay;
        delay = Math.min(delay * 2, LONGEST_DELAY);
        await new Promise<void>(resolve => {
          const timeout = setTimeout(resolve, wait);
          this.wake = () => { clearTimeout(timeout); resolve(); };
        });
        this.wake = null;
      }
    }
  }
}

import { AccessSnapshot } from "./access.js";
import { AuthenticationError } from "./errors.js";
import type { DraftProtocol } from "./protocol.js";
import { pause } from "./transport.js";
import type { Transport } from "./transport.js";

/** The latest known access, and whether it is current. */
export type AccessState =
  | { readonly status: "loading"; readonly access: null }
  | { readonly status: "ready"; readonly access: AccessSnapshot }
  | { readonly status: "refreshing"; readonly access: AccessSnapshot | null }
  | { readonly status: "reconnecting"; readonly access: AccessSnapshot | null; readonly error: unknown };

export interface WatchAccessOptions {
  signal?: AbortSignal | undefined;
  /** First reconnect delay; doubles up to maxBackoffMs. */
  backoffMs?: number;
  maxBackoffMs?: number;
}

interface Frame { event: string; data: unknown }

/** Server-Sent Events frames from a fetch body; comments count as activity. */
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

/**
 * Watches GET /v1/events?types=access.changed and refetches the capabilities
 * report after each connection and each access.changed or gap. Notifications
 * during a fetch coalesce into one more fetch. A slow consumer sees the latest
 * state. Ends on abort, or with AuthenticationError when the key is refused.
 */
export async function* watchAccess(
  transport: Transport, protocol: DraftProtocol, options: WatchAccessOptions = {},
): AsyncGenerator<AccessState> {
  const outer = options.signal;
  const stop = new AbortController();
  const stopped = () => stop.abort(outer?.reason);
  if (outer?.aborted) return;
  outer?.addEventListener("abort", stopped, { once: true });

  let access: AccessSnapshot | null = null;
  let latest: AccessState = { status: "loading", access: null };
  let pending = true;  // the consumer hasn't seen `latest`
  let failure: unknown = null;
  let notify: (() => void) | null = null;
  const publish = (state: AccessState) => { latest = state; pending = true; notify?.(); };

  // One report fetch at a time; a request during one runs once more after it.
  let fetching = false;
  let dirty = false;
  const refresh = async (): Promise<void> => {
    if (fetching) { dirty = true; return; }
    fetching = true;
    try {
      do {
        dirty = false;
        publish({ status: "refreshing", access });
        const report = await protocol.capabilities({ signal: stop.signal });
        access = new AccessSnapshot(report, protocol);
      } while (dirty);
      publish({ status: "ready", access });
    } catch (error) {
      if (!stop.signal.aborted) publish({ status: "reconnecting", access, error });
    } finally { fetching = false; }
  };

  const run = async () => {
    let backoff = options.backoffMs ?? 1_000;
    while (!stop.signal.aborted) {
      const connection = new AbortController();
      const cancel = () => connection.abort();
      stop.signal.addEventListener("abort", cancel, { once: true });
      let heartbeatMs = 15_000;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const activity = () => {
        clearTimeout(timer);
        // A few heartbeats of silence means a dead connection.
        timer = setTimeout(() => connection.abort(new Error("No heartbeat")), heartbeatMs * 3);
      };
      let error: unknown = new Error("The event stream ended");
      try {
        const body = await transport.stream("/v1/events", new URLSearchParams({ types: "access.changed" }), connection.signal);
        activity();
        for await (const frame of frames(body, activity)) {
          if (frame.event === "ready") {
            const ms = (frame.data as { heartbeat_ms?: unknown } | null)?.heartbeat_ms;
            if (typeof ms === "number" && ms > 0) heartbeatMs = ms;
            activity();
            backoff = options.backoffMs ?? 1_000;
            void refresh();
          } else if (frame.event === "access.changed" || frame.event === "gap") {
            void refresh();
          } else if (frame.event === "close") {
            const reason = (frame.data as { reason?: unknown } | null)?.reason;
            error = new Error(`The event stream closed (${String(reason)})`);
            if (reason === "auth") backoff = 0;  // new permissions: reconnect at once
            break;
          }
        }
      } catch (caught) {
        if (caught instanceof AuthenticationError) { failure = caught; notify?.(); return; }
        error = caught;
      } finally {
        clearTimeout(timer);
        connection.abort();
        stop.signal.removeEventListener("abort", cancel);
      }
      if (stop.signal.aborted) return;
      publish({ status: "reconnecting", access, error });
      if (backoff > 0) await pause(backoff, { signal: stop.signal }).catch(() => undefined);
      backoff = Math.min(Math.max(backoff * 2, options.backoffMs ?? 1_000), options.maxBackoffMs ?? 30_000);
    }
  };
  const running = run();

  try {
    while (true) {
      if (failure) throw failure;
      if (stop.signal.aborted) return;
      if (pending) { pending = false; yield latest; continue; }
      await new Promise<void>(resolve => {
        notify = resolve;
        stop.signal.addEventListener("abort", () => resolve(), { once: true });
      });
      notify = null;
    }
  } finally {
    outer?.removeEventListener("abort", stopped);
    stop.abort();
    await running;
  }
}

import type { AccessSnapshot } from "./access.js";
import { PermissionError } from "./errors.js";
import type { EventConnection, Need, Signal } from "./events.js";
import { Subscription } from "./subscription.js";

/** A listener's own part: what to do with each signal once the connection is up. */
export interface Hearing {
  /** A resource the connection must carry for this listener (`ready.resources`). */
  readonly resource?: string;
  /** An events option the capabilities report must show available (cards.answered, sync). */
  readonly option?: string;
  hear(signal: Signal, subscription: Subscription): void;
}

const refused = (detail: string) => new PermissionError(403, { detail }, "/v1/events", undefined);

/**
 * Join the event connection; resolve once it is up, or fail when the app may
 * not receive what it asked for (packages/spec/behavior.md, Listening).
 */
export async function listen(
  connection: EventConnection, need: Need, hearing: Hearing,
  access: () => Promise<AccessSnapshot>, signal?: AbortSignal,
): Promise<Subscription> {
  if (hearing.option) {
    const decision = (await access()).operation("GET /v1/events", hearing.option);
    if (!decision.allowed) throw refused(decision.reason);
  }
  const subscription = new Subscription(signal);
  let started = false;
  let up!: { resolve: () => void; reject: (error: unknown) => void };
  const ready = new Promise<void>((resolve, reject) => { up = { resolve, reject }; });
  const start = (resources: readonly string[]) => {
    if (started) return;
    started = true;
    if (hearing.resource && !resources.includes(hearing.resource)) {
      const error = refused(`This app may not read ${hearing.resource}.`);
      up.reject(error);
      subscription.end(error);
    } else up.resolve();
  };
  const leave = connection.join({
    need,
    hear: heard => {
      if (heard.kind === "ready" && !started) { start(heard.resources); return; }
      if (heard.kind === "down" && !started && !heard.deliberate) {
        // Never connected: fail the awaited call rather than wait forever.
        started = true;
        up.reject(heard.error);
        subscription.end(heard.error);
        return;
      }
      if (!started || !subscription.active) return;
      try { hearing.hear(heard, subscription); } catch (error) { subscription.end(error); }
    },
    end: error => { if (!started) { started = true; up.reject(error); } subscription.end(error); },
  });
  subscription.onEnd(leave);
  if (connection.carries(need)) start(connection.resources);
  await ready;
  return subscription;
}

/**
 * Call `listener` once per burst: signals that arrive while it runs (until
 * what it returns settles) become one more call afterwards.
 */
export function coalescing(listener: () => unknown): (subscription: Subscription) => void {
  let running = false;
  let again = false;
  const fire = (subscription: Subscription): void => {
    if (running) { again = true; return; }
    running = true;
    let result: unknown;
    try { result = listener(); } catch (error) { subscription.end(error); return; }
    Promise.resolve(result).then(() => {
      running = false;
      if (again && subscription.active) { again = false; fire(subscription); }
    }, error => subscription.end(error));
  };
  return fire;
}

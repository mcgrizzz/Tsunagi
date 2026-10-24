/**
 * Resending a write whose outcome is unknown (packages/spec/behavior.md,
 * Resending): the transport records each keyed attempt, and every write
 * method is wrapped so its outcome-unknown error can send it again.
 */
import { pause } from "./transport.js";

/** A keyed write as it was first sent. */
export interface Attempt {
  readonly method: string;
  readonly url: string;
  readonly text: string | undefined;
  readonly key: string;
  /** The server session the client saw before sending (Tsunagi-Session); undefined when it knew none. */
  readonly session: string | undefined;
  /** When resending stops being safe: the first send plus the key's retention, less a minute. Unix ms. */
  readonly until: number;
}

/** Internal write option: send this attempt again instead of a new request. Never sent. */
export const resendOf: unique symbol = Symbol("Tsunagi resend");
export type Resending = { readonly [resendOf]?: Attempt };

// Off the public error objects.
export const attempts = new WeakMap<object, Attempt>();
export const resenders = new WeakMap<object, () => Promise<unknown>>();

const isUnknown = (error: unknown): error is Error => error instanceof Error && attempts.has(error);

/**
 * A write method whose options are argument `at`: its outcome-unknown error
 * can retry() (the same arguments, sending the recorded attempt), and
 * `resendIfUnknown: true` resends by itself, 1 s, then twice as long each
 * time up to 30 s, until an answer, the window, a session change or the
 * caller's signal; then it raises what the last attempt gave.
 */
export function resendable<A extends unknown[], T>(at: number, method: (...args: A) => Promise<T>): (...args: A) => Promise<T> {
  return async (...args: A): Promise<T> => {
    const options = (args[at] ?? {}) as { resendIfUnknown?: unknown; signal?: AbortSignal | undefined };
    if (options.resendIfUnknown !== undefined && typeof options.resendIfUnknown !== "boolean") {
      throw new TypeError("resendIfUnknown is true or false");
    }
    const send = (attempt?: Attempt): Promise<T> => {
      const next = [...args] as unknown[] as A;
      next[at] = attempt ? { ...options, [resendOf]: attempt } : options;
      return method(...next).catch(error => {
        if (isUnknown(error)) {
          const recorded = attempts.get(error)!;
          resenders.set(error, () => send(recorded));
        }
        throw error;
      });
    };
    let pending = send();
    if (options.resendIfUnknown !== true) return pending;
    for (let wait = 1_000; ; wait = Math.min(wait * 2, 30_000)) {
      try {
        return await pending;
      } catch (error) {
        if (!isUnknown(error)) throw error;
        const left = attempts.get(error)!.until - Date.now();
        if (left <= 0) throw error;
        try { await pause(Math.min(wait, left), { signal: options.signal }); } catch { throw error; }
        pending = (error as Error & { retry(): Promise<T> }).retry();
      }
    }
  };
}

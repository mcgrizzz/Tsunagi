import { objectFields } from "./generated.js";
import { attempts, resenders } from "./resend.js";
import type { Attempt } from "./resend.js";
import type { ItemReport } from "./types.js";

/** What every item failure carries; each write's own type names its codes. */
export interface ItemFailure { readonly index: number; readonly code: string; readonly message: string }

export class TsunagiError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = new.target.name;
  }
}
export class ProtocolError extends TsunagiError {}
export class RequestTimeoutError extends TsunagiError {}
export class TransportError extends TsunagiError {}
export class HttpError extends TsunagiError {
  readonly detail: string | undefined;
  /** On a 503, why Anki can't answer now. */
  readonly reason: "busy" | "closed" | "syncing" | undefined;
  readonly errors: readonly unknown[] | undefined;

  constructor(
    readonly status: number,
    readonly body: unknown,
    readonly path: string,
    readonly idempotencyKey: string | undefined,
  ) {
    // Keep server text in .body: it may contain private field content.
    super(`Tsunagi returned HTTP ${status} for ${path}`);
    const data = typeof body === "object" && body !== null && !Array.isArray(body)
      ? body as Record<string, unknown> : {};
    this.detail = typeof data.detail === "string" ? data.detail : undefined;
    const reasons: Readonly<Record<string, string | null>> = objectFields.ErrorBody.reason.values;
    this.reason = typeof data.reason === "string" && Object.hasOwn(reasons, data.reason)
      ? reasons[data.reason] as HttpError["reason"] : undefined;
    this.errors = Array.isArray(data.errors) ? Object.freeze([...data.errors]) : undefined;
  }
}
/** Missing/rejected credentials or a No key role without access. */
export class AuthenticationError extends HttpError {}
/** The accepted caller cannot perform this request. See .detail for guidance. */
export class PermissionError extends HttpError {}
export class WriteOutcomeUnknownError<T = unknown> extends TsunagiError {
  /** Until when retry() is safe: a little before Tsunagi forgets the key. Undefined for a write sent without a key. */
  readonly resendableUntil: Date | undefined;
  constructor(readonly idempotencyKey: string | undefined, cause: unknown, attempt?: Attempt) {
    super(idempotencyKey === undefined
      ? "Anki may have started or completed this write. Do not resubmit it automatically."
      : "Anki may have completed this write. retry() sends it again, the same request with the same key, "
        + "safely until resendableUntil.", { cause });
    this.resendableUntil = attempt ? new Date(attempt.until) : undefined;
    if (attempt) attempts.set(this, attempt);
  }
  /**
   * Sends the same write again: the same body and key, so Tsunagi answers the
   * first attempt's result, or writes once if it never arrived. Resolves or
   * raises as the original call. Raises ResendExpiredError past
   * resendableUntil, or when Anki restarted or switched profile since.
   */
  retry(): Promise<T> {
    const attempt = attempts.get(this);
    const resend = resenders.get(this);
    if (!attempt || !resend) return Promise.reject(new TypeError("This write was sent without a key: it can't be resent safely"));
    if (Date.now() > attempt.until) return Promise.reject(new ResendExpiredError(attempt.key, "window"));
    if (attempt.session === undefined) return Promise.reject(new ResendExpiredError(attempt.key, "session"));
    return resend() as Promise<T>;
  }
}
/** Anki switched profile: a watch ends, since an app's copy belongs to one profile. */
export class ProfileChangedError extends TsunagiError {
  constructor(readonly from: string, readonly to: string) {
    super("Anki switched profile, so the watch ended: start a new one for the new profile.");
  }
}
/** A write that can no longer be resent safely; it may or may not have happened. */
export class ResendExpiredError extends TsunagiError {
  constructor(readonly idempotencyKey: string, readonly why: "window" | "session") {
    super((why === "window"
      ? "Too late to resend this write safely: Tsunagi no longer keeps its key. "
      : "Anki restarted or switched profile since this write was sent, so it can't be resent safely. ")
      + "It may or may not have happened: check (for a note, search for it) before writing it again.");
  }
}
export class ItemRejectedError extends TsunagiError {
  constructor(readonly failure: ItemFailure) {
    super(`Tsunagi rejected item ${failure.index} (${failure.code})`);
  }
}
export class PartialWriteError extends TsunagiError {
  constructor(readonly report: ItemReport<unknown, ItemFailure>) {
    super("Some items were rejected. Inspect the report; successful writes were not rolled back.");
  }
}
export class JobFailedError extends TsunagiError {
  constructor(readonly jobId: string, readonly status: string, readonly detail: string | null) {
    super(`Tsunagi job ${jobId} ended with status ${status}`);
  }
}
export class JobWaitTimeoutError extends TsunagiError {
  constructor(readonly operation: { readonly id: string | null; wait(options?: import("./types.js").WaitOptions): Promise<unknown> }) {
    super("Stopped waiting for the job. Use error.operation.wait() to continue observing it.");
  }
}

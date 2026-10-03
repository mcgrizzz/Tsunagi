import type { CreationReport, ItemFailure } from "./types.js";

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
  readonly reason: string | undefined;
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
    this.reason = typeof data.reason === "string" ? data.reason : undefined;
    this.errors = Array.isArray(data.errors) ? Object.freeze([...data.errors]) : undefined;
  }
}
/** Missing/rejected credentials or a No key role without access. */
export class AuthenticationError extends HttpError {}
/** The accepted caller cannot perform this request. See .detail for guidance. */
export class PermissionError extends HttpError {}
export class WriteOutcomeUnknownError extends TsunagiError {
  constructor(readonly idempotencyKey: string | undefined, cause: unknown) {
    super(idempotencyKey === undefined
      ? "Anki may have started or completed this write. Do not resubmit it automatically."
      : "Anki may have completed this write. Preserve its key and request; verify replay support before retrying.", { cause });
  }
}
export class ItemRejectedError extends TsunagiError {
  constructor(readonly failure: ItemFailure) {
    super(`Tsunagi rejected item ${failure.index} (${failure.code})`);
  }
}
export class PartialWriteError extends TsunagiError {
  constructor(readonly report: CreationReport) {
    super("Some notes were rejected. Inspect the report; successful writes were not rolled back.");
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

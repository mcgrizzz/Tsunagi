import { HttpError, ProtocolError, RequestTimeoutError, ResendExpiredError, TransportError, WriteOutcomeUnknownError } from "./errors.js";
import { idempotency } from "./generated.js";
import { resendOf } from "./resend.js";
import type { Attempt, Resending } from "./resend.js";
import type { ClientOptions, RequestOptions, WriteOptions } from "./types.js";

export function positive(value: number, name: string): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw new RangeError(`${name} must be a positive safe integer`);
  return value;
}

/** Also bounds injected fetch/key providers that do not themselves observe abort. */
export function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const aborted = () => { signal.removeEventListener("abort", aborted); reject(signal.reason); };
    signal.addEventListener("abort", aborted, { once: true });
    if (signal.aborted) aborted();
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", aborted));
  });
}

export function deadline(timeoutMs: number, parent?: AbortSignal) {
  positive(timeoutMs, "timeoutMs");
  const controller = new AbortController();
  const aborted = () => controller.abort(parent?.reason);
  if (parent?.aborted) aborted();
  else parent?.addEventListener("abort", aborted, { once: true });
  const timer = setTimeout(() => controller.abort(new RequestTimeoutError("Request deadline expired")), timeoutMs);
  return {
    signal: controller.signal,
    close() { clearTimeout(timer); parent?.removeEventListener("abort", aborted); },
  };
}

export interface JsonResponse {
  status: number; data: unknown; headers: Headers; idempotencyKey: string | undefined;
  /** A keyed write's attempt, for an outcome found unknown after it answered. */
  attempt?: Attempt | undefined;
}
/** Each response's server session (packages/spec/behavior.md, Resending). */
const SESSION = "tsunagi-session";
export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class Transport {
  private readonly root: URL;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly timeout: number;
  readonly maxGetUrlLength: number;
  /** Told of every 401 or 403 answer (the access cache drops its snapshot). */
  refused: (() => void) | null = null;
  /** The last server session a response named, sent back when a write is resent. */
  private session: string | undefined;
  private sessionRead: Promise<unknown> | undefined;

  constructor(private readonly options: ClientOptions) {
    this.root = new URL(options.baseUrl);
    if (!/^https?:$/.test(this.root.protocol) || this.root.username || this.root.password || this.root.search || this.root.hash) {
      throw new TypeError("baseUrl must be an HTTP(S) server root without credentials, query, or fragment");
    }
    this.root.pathname = this.root.pathname.replace(/\/*$/, "/");
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeout = positive(options.requestTimeoutMs ?? 30_000, "requestTimeoutMs");
    this.maxGetUrlLength = positive(options.maxGetUrlLength ?? 2_000, "maxGetUrlLength");
  }

  url(path: string, query?: URLSearchParams): URL {
    if (!path.startsWith("/v1/") || /[?#\\]/.test(path)) throw new TypeError("Expected a /v1/ path without a query or fragment");
    const url = new URL(path.slice(1), this.root);
    if (url.origin !== this.root.origin || !url.pathname.startsWith(this.root.pathname + "v1/")) {
      throw new TypeError("Request must stay inside the configured Tsunagi API");
    }
    if (query) url.search = query.toString();
    return url;
  }

  async request(
    method: Method,
    path: string,
    { body, query, write = false, ...options }: WriteOptions & Resending & {
      body?: unknown; query?: URLSearchParams | undefined; write?: false | "keyed" | "unkeyed";
    } = {},
  ): Promise<JsonResponse> {
    options.signal?.throwIfAborted();
    const url = this.url(path, query);
    const resend = write ? options[resendOf] : undefined;
    if (resend && (resend.method !== method || resend.url !== url.href)) throw new TypeError("A resend must be the same request");
    // Freeze the wire representation before awaiting a key provider or fetch.
    const text = resend ? resend.text : body === undefined ? undefined : JSON.stringify(body);
    // Generate a key only for operations with documented replay support.
    // Raw calls may supply one explicitly after checking their route's contract.
    const key = resend ? resend.key : write ? options.idempotencyKey ?? (write === "keyed"
      ? this.options.makeIdempotencyKey?.() ?? globalThis.crypto.randomUUID()
      : undefined) : undefined;
    if (key !== undefined && (!key || /[\r\n]/.test(key))) throw new TypeError("Invalid idempotencyKey");
    // A first write learns the session first, so it can be resent (once per client; a failure is ignored).
    if (key && !resend && this.session === undefined) {
      await (this.sessionRead ??= this.request("GET", "/v1/health", { signal: options.signal }).catch(() => undefined));
    }
    const scope = deadline(options.timeoutMs ?? this.timeout, options.signal);
    let dispatched = false;
    let attempt: Attempt | undefined = resend;
    try {
      const supplied = this.options.apiKey;
      const apiKey = await abortable(Promise.resolve(typeof supplied === "function" ? supplied() : supplied), scope.signal);
      scope.signal.throwIfAborted();
      const headers = new Headers({ Accept: "application/json" });
      if (apiKey) headers.set("X-Api-Key", apiKey);
      if (key) headers.set("Idempotency-Key", key);
      if (resend?.session) headers.set("If-Session", resend.session);
      if (text !== undefined) headers.set("Content-Type", "application/json");
      const init: RequestInit = { method, headers, signal: scope.signal, redirect: "error", credentials: "omit" };
      if (text !== undefined) init.body = text;
      attempt ??= key === undefined ? undefined : {
        method, url: url.href, text, key, session: this.session,
        until: Date.now() + (idempotency.retentionSeconds - 60) * 1_000,
      };
      dispatched = true;
      const response = await abortable(this.fetcher(url, init), scope.signal);
      this.session = response.headers.get(SESSION) ?? this.session;
      if (resend && response.status === 412) throw new ResendExpiredError(resend.key, "session");
      const Failure = response.status === 401 ? AuthenticationError
        : response.status === 403 ? PermissionError : HttpError;
      if (Failure !== HttpError) this.refused?.();
      const raw = await abortable(response.text(), scope.signal);
      let data: unknown;
      try { data = raw ? JSON.parse(raw) : null; }
      catch {
        if (!response.ok) throw new Failure(response.status, raw, path, key);
        throw new ProtocolError("Expected a JSON response from Tsunagi");
      }
      if (!response.ok) throw new Failure(response.status, data, path, key);
      if (!response.headers.get("content-type")?.toLowerCase().includes("application/json")) {
        throw new ProtocolError("Expected application/json from Tsunagi");
      }
      return { status: response.status, headers: response.headers, data, idempotencyKey: key, attempt };
    } catch (error) {
      if (error instanceof ResendExpiredError) throw error;
      if (write && dispatched && (!(error instanceof HttpError) || error.status >= 500)) {
        throw new WriteOutcomeUnknownError(key, error, attempt);
      }
      if (scope.signal.aborted) throw scope.signal.reason;
      if (error instanceof HttpError || error instanceof ProtocolError) throw error;
      throw new TransportError("Could not complete the Tsunagi request", { cause: error });
    } finally { scope.close(); }
  }

  /** The key for the next request: a provider is asked each time. */
  async apiKey(signal?: AbortSignal): Promise<string | undefined> {
    const supplied = this.options.apiKey;
    const value = typeof supplied === "function" ? supplied() : supplied;
    return signal ? abortable(Promise.resolve(value), signal) : value;
  }

  /** A long-lived text/event-stream body: no deadline; the caller's signal ends it. */
  async stream(path: string, query: URLSearchParams, signal: AbortSignal): Promise<ReadableStream<Uint8Array>> {
    const url = this.url(path, query);
    const supplied = this.options.apiKey;
    const apiKey = await abortable(Promise.resolve(typeof supplied === "function" ? supplied() : supplied), signal);
    const headers = new Headers({ Accept: "text/event-stream" });
    if (apiKey) headers.set("X-Api-Key", apiKey);
    const response = await this.fetcher(url, { method: "GET", headers, signal, redirect: "error", credentials: "omit" });
    this.session = response.headers.get(SESSION) ?? this.session;
    if (!response.ok) {
      const raw = await response.text();
      let data: unknown = raw;
      try { data = JSON.parse(raw); } catch { /* keep the text */ }
      const Failure = response.status === 401 ? AuthenticationError
        : response.status === 403 ? PermissionError : HttpError;
      throw new Failure(response.status, data, path, undefined);
    }
    if (!response.body) throw new ProtocolError("Expected an event stream from Tsunagi");
    return response.body;
  }
}

export async function pause(ms: number, options: RequestOptions = {}): Promise<void> {
  options.signal?.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const done = () => { options.signal?.removeEventListener("abort", aborted); resolve(); };
    const timer = setTimeout(done, ms);
    const aborted = () => { clearTimeout(timer); options.signal?.removeEventListener("abort", aborted); reject(options.signal?.reason); };
    options.signal?.addEventListener("abort", aborted, { once: true });
    if (options.signal?.aborted) aborted();
  });
}
import { AuthenticationError, PermissionError } from "./errors.js";

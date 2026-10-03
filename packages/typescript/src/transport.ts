import { HttpError, ProtocolError, RequestTimeoutError, TransportError, WriteOutcomeUnknownError } from "./errors.js";
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

export interface JsonResponse { status: number; data: unknown; headers: Headers; idempotencyKey: string | undefined }

export class Transport {
  private readonly root: URL;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly timeout: number;
  readonly maxGetUrlLength: number;

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
    method: "GET" | "POST" | "PATCH" | "DELETE",
    path: string,
    { body, query, write = false, ...options }: WriteOptions & {
      body?: unknown; query?: URLSearchParams; write?: false | "keyed" | "unkeyed";
    } = {},
  ): Promise<JsonResponse> {
    options.signal?.throwIfAborted();
    const url = this.url(path, query);
    // Freeze the wire representation before awaiting a key provider or fetch.
    const text = body === undefined ? undefined : JSON.stringify(body);
    // Generate a key only for operations with documented replay support.
    // Raw calls may supply one explicitly after checking their route's contract.
    const key = write ? options.idempotencyKey ?? (write === "keyed"
      ? this.options.makeIdempotencyKey?.() ?? globalThis.crypto.randomUUID()
      : undefined) : undefined;
    if (key !== undefined && (!key || /[\r\n]/.test(key))) throw new TypeError("Invalid idempotencyKey");
    const scope = deadline(options.timeoutMs ?? this.timeout, options.signal);
    let dispatched = false;
    try {
      const supplied = this.options.apiKey;
      const apiKey = await abortable(Promise.resolve(typeof supplied === "function" ? supplied() : supplied), scope.signal);
      scope.signal.throwIfAborted();
      const headers = new Headers({ Accept: "application/json" });
      if (apiKey) headers.set("X-Api-Key", apiKey);
      if (key) headers.set("Idempotency-Key", key);
      if (text !== undefined) headers.set("Content-Type", "application/json");
      const init: RequestInit = { method, headers, signal: scope.signal, redirect: "error", credentials: "omit" };
      if (text !== undefined) init.body = text;
      dispatched = true;
      const response = await abortable(this.fetcher(url, init), scope.signal);
      const Failure = response.status === 401 ? AuthenticationError
        : response.status === 403 ? PermissionError : HttpError;
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
      return { status: response.status, headers: response.headers, data, idempotencyKey: key };
    } catch (error) {
      if (write && dispatched && (!(error instanceof HttpError) || error.status >= 500)) {
        throw new WriteOutcomeUnknownError(key, error);
      }
      if (scope.signal.aborted) throw scope.signal.reason;
      if (error instanceof HttpError || error instanceof ProtocolError) throw error;
      throw new TransportError("Could not complete the Tsunagi request", { cause: error });
    } finally { scope.close(); }
  }

  /** A long-lived text/event-stream body: no deadline; the caller's signal ends it. */
  async stream(path: string, query: URLSearchParams, signal: AbortSignal): Promise<ReadableStream<Uint8Array>> {
    const url = this.url(path, query);
    const supplied = this.options.apiKey;
    const apiKey = await abortable(Promise.resolve(typeof supplied === "function" ? supplied() : supplied), signal);
    const headers = new Headers({ Accept: "text/event-stream" });
    if (apiKey) headers.set("X-Api-Key", apiKey);
    const response = await this.fetcher(url, { method: "GET", headers, signal, redirect: "error", credentials: "omit" });
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

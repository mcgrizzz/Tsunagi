import { routeWrites } from "./generated.js";
import type { RawRoutes } from "./generated.js";
import type { JsonResponse, Method, Transport } from "./transport.js";
import type { RequestOptions, WriteOptions } from "./types.js";

/** An operation, "METHOD /v1/path" as the API description names it, path parameters in braces. */
export type RawRoute = keyof RawRoutes;
/** The route's parameters and body in wire names, and the request's options; a keyed write also takes its key. */
export type RawOptions<R extends RawRoute> = RawRoutes[R]["options"]
  & (RawRoutes[R]["keyed"] extends true ? WriteOptions : RequestOptions);
/** One of the route's answers: its status says which data, in wire names as the server sent it. */
export type RawAnswer<R extends RawRoute> = {
  [S in keyof RawRoutes[R]["answers"]]: {
    status: S; data: RawRoutes[R]["answers"][S]; headers: Headers; idempotencyKey: string | undefined;
  }
}[keyof RawRoutes[R]["answers"]];

type Parameters = Record<string, unknown>;
const methods: readonly string[] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

/** A path parameter as one segment; `.` and `..` would leave it. */
function segment(name: string, value: unknown): string {
  if (value === undefined || value === null) throw new TypeError(`Missing path parameter ${name}`);
  const text = String(value);
  if (text === "" || text === "." || text === "..") throw new TypeError(`Invalid path parameter ${name}`);
  return encodeURIComponent(text);
}

function search(query: Parameters | undefined): URLSearchParams | undefined {
  if (!query) return undefined;
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) params.append(name, String(item));
  }
  return params;
}

/** Every operation in the API description, typed (packages/spec/behavior.md, Transport). */
export function raw(transport: Transport) {
  /**
   * Send one operation and answer its JSON undecoded. Writes are keyed as the
   * client's own methods are; nothing is retried.
   */
  function request<R extends RawRoute>(
    route: R, ...options: {} extends RawOptions<R> ? [options?: RawOptions<R>] : [options: RawOptions<R>]
  ): Promise<RawAnswer<R>>;
  /**
   * @deprecated Name the route instead, `request("POST /v1/notes", { body })`: typed, and keyed like the
   * client's own writes. This form stays for routes newer than the client; a write is keyed only with an idempotencyKey.
   */
  function request(method: Method, path: string, options?: WriteOptions & { body?: unknown; query?: URLSearchParams }): Promise<JsonResponse>;
  async function request(first: string, second?: unknown, third: WriteOptions & { body?: unknown; query?: URLSearchParams } = {}): Promise<unknown> {
    if (typeof second === "string") {
      return transport.request(first as Method, second, { ...third, write: first === "GET" ? false : "unkeyed" });
    }
    const space = first.indexOf(" ");
    const method = first.slice(0, space);
    if (space < 0 || !methods.includes(method)) throw new TypeError('Expected a route such as "GET /v1/cards"');
    const { path = {}, query, body, ...options } = (second ?? {}) as WriteOptions & { path?: Parameters; query?: Parameters; body?: unknown };
    const url = first.slice(space + 1).replace(/\{([^}]+)\}/g, (_, name: string) => segment(name, path[name]));
    const write = Object.hasOwn(routeWrites, first) ? routeWrites[first as RawRoute] : method === "GET" ? false : "unkeyed";
    return transport.request(method as Method, url, { ...options, body, query: search(query), write });
  }
  return { request };
}

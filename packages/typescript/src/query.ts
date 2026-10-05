import { AccessSnapshot } from "./access.js";
import type { AccessDecision } from "./access.js";
import { accessTarget, registerAccess } from "./access-target.js";
import type { AccessTarget } from "./access-target.js";
import { ProtocolError } from "./errors.js";
import { decodeField, decodeObject } from "./decode.js";
import type { FieldDescription } from "./decode.js";
import { resources, states as stateTerms } from "./generated.js";
import type { Rows } from "./generated.js";
import { DraftProtocol } from "./protocol.js";
import type { QueryParams } from "./protocol.js";
import { positive } from "./transport.js";
import type { Subscription } from "./subscription.js";
import type { RequestOptions, WriteOptions } from "./types.js";
import { watch } from "./watch.js";
import type { WatchHandlers } from "./watch.js";

/** The resources read with a query (add-ons are a plain list). */
export type QueryResource = Exclude<keyof Rows, "addons">;
export type SortOf<N extends QueryResource> = Extract<keyof (typeof resources)[N]["sorts"], string>;
/** The resources that take an Anki search: cards, notes and reviews. */
export type SearchResource = { [K in QueryResource]: (typeof resources)[K]["search"] extends null ? never : K }[QueryResource];
/** One of Anki's states, for is(): its search term is is:<term> (packages/spec/names.json, states). */
export type CardState = keyof typeof stateTerms;
type Key<T> = Extract<keyof T, string>;
type ScalarKey<T> = { [K in Key<T>]: T[K] extends string | number | boolean | null ? K : never }[Key<T>];
/** Comparisons for numbers; contains/startsWith/endsWith for free text (not named values). */
export type Operator<V> = "eq" | "ne" | "in" | "notIn"
  | (NonNullable<V> extends number ? "gt" | "gte" | "lt" | "lte" : never)
  | (string extends NonNullable<V> ? "contains" | "startsWith" | "endsWith" : never);
type Operand<V, O> = O extends "in" | "notIn" ? readonly V[]
  : O extends "eq" | "ne" ? V : NonNullable<V>;

const symbols = {
  eq: "==", ne: "!=", gt: ">", gte: ">=", lt: "<", lte: "<=",
  contains: "~=", startsWith: "^=", endsWith: "$=", in: " in", notIn: " not in",
} as const;

const scalarKinds = ["number", "string", "boolean"];

function encodeValue(field: FieldDescription, value: unknown): string {
  if (field.values) {
    const code = Object.keys(field.values).find(key => field.values![key] === value);
    if (code !== undefined) return code;
    if (value === null && field.nullable) return "null";
    throw new TypeError(`Unknown value for ${field.wire}`);
  }
  if (value === null) {
    if (!field.nullable) throw new TypeError(`${field.wire} is never null`);
    return "null";
  }
  if (typeof value !== field.kind || (typeof value === "number" && !Number.isFinite(value))) {
    throw new TypeError("Filter value does not match the field type");
  }
  return JSON.stringify(value);
}

interface State {
  readonly select: readonly string[] | null;  // client names; null for every field
  readonly unwatchable?: string;   // why watch() can't run this query, when it can't
  readonly unbrowsable?: string;   // why openBrowser() can't show it, when it can't
  readonly scalar: boolean;
  readonly where: readonly string[];
  readonly search?: string;
  readonly states: readonly string[];  // Anki search terms from is(), in order
  readonly order?: string;
  readonly distinctOn?: string;
}

export interface Page<T> {
  readonly items: readonly T[];
  readonly hasMore: boolean;
  /** How many rows the query matches across all pages, when asked for with `total: true`. */
  readonly total: number | null;
  /** Retains the query, size, and opaque cursor, but not a previous abort signal. */
  next(options?: RequestOptions): Promise<Page<T> | null>;
}
export interface PageOptions extends RequestOptions {
  size?: number;
  /** Also count every row the query matches (include=total). */
  total?: boolean;
}

/**
 * Immutable and lazy: only take/page/iterate/count send a request. Without
 * select, rows have every field, as the server sends them.
 */
/** The resources Tsunagi sends events for. */
export type WatchResource = "notes" | "cards" | "reviews" | "decks" | "noteTypes" | "tags";
const watchable = new Set<string>(["notes", "cards", "reviews", "decks", "noteTypes", "tags"]);
type KeyName<N extends QueryResource> = (typeof resources)[N]["key"] & keyof Rows[N];
/** A watched row: the selected fields and the resource's key. */
export type WatchRow<N extends QueryResource, R> = R & Pick<Rows[N], KeyName<N>>;
export type WatchKey<N extends QueryResource> = Rows[N][KeyName<N>];
declare const canWatch: unique symbol;
declare const canBrowse: unique symbol;
/** Why watch() can't run a query, as the compiler shows it. */
export type NotWatchable = typeof notWatchable[keyof typeof notWatchable];
const notWatchable = {
  orderBy: "orderBy() can't be watched: changes have no order (use onChange() and take())",
  distinctOn: "distinctOn() can't be watched: one row per value can't be kept from changes",
  values: "values() can't be watched: a watch needs each row's key (use select())",
} as const;
/** Why openBrowser() can't show a query, as the compiler shows it. */
export type NotBrowsable = typeof notBrowsable[keyof typeof notBrowsable];
const notBrowsable = {
  where: "where() can't be shown in Anki's Browser, which takes only search() and is()",
  orderBy: "orderBy() can't be shown in Anki's Browser, which takes only search() and is()",
  distinctOn: "distinctOn() can't be shown in Anki's Browser, which takes only search() and is()",
} as const;
/** The resources Anki's Browser shows. */
export type BrowserResource = "cards" | "notes";

/**
 * W and B are true, or the reason watch() or openBrowser() can't take the
 * query: a misuse is a compile error that says why, and a TypeError with the
 * same words at run time.
 */
export class Query<N extends QueryResource, R = Rows[N], W extends true | NotWatchable = true,
  B extends true | NotBrowsable = true> implements AccessTarget {
  declare readonly [accessTarget]: true;
  declare readonly [canWatch]: W;
  declare readonly [canBrowse]: B;
  constructor(
    protected readonly protocol: DraftProtocol,
    protected readonly resource: N,
    private readonly state: State = { select: null, scalar: false, where: [], states: [] },
  ) {
    registerAccess(this, protocol, `GET ${resources[resource].path}`);
  }

  /** Fetch a fresh discovery report without running this query. */
  async checkAccess(options: RequestOptions = {}): Promise<AccessDecision> {
    return new AccessSnapshot(await this.protocol.capabilities(options), this.protocol).check(this);
  }

  private get fields(): Readonly<Record<string, FieldDescription>> { return resources[this.resource].fields; }
  private field(name: string, scalar = false): FieldDescription {
    if (!Object.hasOwn(this.fields, name)) throw new TypeError(`Unknown field: ${name}`);
    const field = this.fields[name]!;
    if (scalar && !scalarKinds.includes(field.kind)) throw new TypeError(`${name} is not a single value`);
    return field;
  }
  private with<T, V extends true | NotWatchable = W, U extends true | NotBrowsable = B>(state: Partial<State>): Query<N, T, V, U> {
    return new Query(this.protocol, this.resource, { ...this.state, ...state });
  }

  /** Anki search, on cards, notes and reviews. Replaces a previous search; is() states stay. */
  search(search: string): Query<N, R, W, B> {
    if (typeof search !== "string") throw new TypeError("search must be a string");
    return this.with({ search });
  }
  /** Rows in one of Anki's states, as Anki's search means it (is:suspended, is:due...). Several must all hold. */
  is(this: Query<N & SearchResource, R, W, B>, state: CardState): Query<N, R, W, B> {
    if (typeof state !== "string" || !Object.hasOwn(stateTerms, state)) throw new TypeError(`Unknown state: ${String(state)}`);
    if (resources[this.resource].search === null) throw new TypeError(`${this.resource} take no Anki search`);
    return this.with({ states: [...this.state.states, `is:${stateTerms[state]}`] }) as unknown as Query<N, R, W, B>;
  }
  /** The search sent: the text, then each is() state, all of which must hold. */
  private get fullSearch(): string | undefined {
    const { search, states } = this.state;
    if (!states.length) return search;
    const terms = [...new Set(states)].join(" ");
    return search === undefined || !search.trim() ? terms : `(${search}) ${terms}`;
  }
  where<K extends ScalarKey<Rows[N]>, O extends Operator<Rows[N][K]>>(field: K, operator: O, value: Operand<NoInfer<Rows[N][K]>, O>): Query<N, R, W, typeof notBrowsable.where> {
    const description = this.field(field, true);
    if (!Object.hasOwn(symbols, operator)) throw new TypeError("Unsupported filter operator");
    const list = operator === "in" || operator === "notIn";
    if (list !== Array.isArray(value)) throw new TypeError(list ? "in and notIn take a list" : "Expected a single value");
    const kind = ["gt", "gte", "lt", "lte"].includes(operator) ? "number"
      : ["contains", "startsWith", "endsWith"].includes(operator) ? "string" : null;
    if (kind && (description.kind !== kind || description.values || value === null)) {
      throw new TypeError(`${operator} does not apply to ${field}`);
    }
    const encoded = list ? `[${(value as readonly unknown[]).map(v => encodeValue(description, v)).join(",")}]`
      : encodeValue(description, value);
    return this.with({ where: [...this.state.where, `${description.wire}${symbols[operator]}${encoded}`],
      unbrowsable: notBrowsable.where });
  }
  orderBy(sort: SortOf<N>, direction: "asc" | "desc" = "asc"): Query<N, R, typeof notWatchable.orderBy, typeof notBrowsable.orderBy> {
    const sorts: Readonly<Record<string, string>> = resources[this.resource].sorts;
    if (!Object.hasOwn(sorts, sort) || !["asc", "desc"].includes(direction)) throw new TypeError("Unsupported sort");
    return this.with({ order: `${sorts[sort]}:${direction}`, unwatchable: notWatchable.orderBy, unbrowsable: notBrowsable.orderBy });
  }
  /** One row per value of the field: the first in orderBy's order. */
  distinctOn(field: ScalarKey<Rows[N]>): Query<N, R, typeof notWatchable.distinctOn, typeof notBrowsable.distinctOn> {
    return this.with({ distinctOn: this.field(field, true).wire, unwatchable: notWatchable.distinctOn,
      unbrowsable: notBrowsable.distinctOn });
  }
  select<const K extends readonly [Key<Rows[N]>, ...Key<Rows[N]>[]]>(...fields: K): Query<N, Pick<Rows[N], K[number]>, W, B> {
    if (!fields.length) throw new TypeError("Select at least one field");
    fields.forEach(field => this.field(field));
    return this.with({ select: [...new Set(fields)], scalar: false });
  }
  /** Each row's value of one field, bare. */
  values<K extends ScalarKey<Rows[N]>>(field: K): Query<N, Rows[N][K], typeof notWatchable.values, B> {
    this.field(field, true);
    return this.with({ select: [field], scalar: true, unwatchable: notWatchable.values });
  }

  async take(count: number, options: RequestOptions = {}): Promise<R[]> {
    if (!Number.isSafeInteger(count) || count < 0) throw new RangeError("count must be a nonnegative safe integer");
    options.signal?.throwIfAborted();
    if (count === 0) return [];
    return [...(await this.readPage(count, false, null, new Set(), options)).items];
  }
  page(options: PageOptions = {}): Promise<Page<R>> {
    return this.readPage(positive(options.size ?? 50, "size"), options.total ?? false, null, new Set(), options);
  }
  async *iterate(options: Omit<PageOptions, "total"> = {}): AsyncGenerator<R> {
    let page: Page<R> | null = await this.page({ ...options, size: options.size ?? 100, total: false });
    while (page) {
      for (const item of page.items) { options.signal?.throwIfAborted(); yield item; }
      options.signal?.throwIfAborted();
      page = await page.next(options);
    }
  }
  /** How many rows the query matches; reads none of them. */
  async count(options: RequestOptions = {}): Promise<number> {
    const response = await this.protocol.query(resources[this.resource].path, this.params(true), 0, null, options);
    if (response.total === null) throw new ProtocolError("Missing total");
    return response.total;
  }

  /**
   * Keep up with every row this query matches: the first load, then each
   * change, as named handlers (packages/spec/behavior.md, Watching a query).
   * Resolves once the first load has been delivered.
   */
  watch(
    this: Query<N, R, true, B>,
    handlers: N extends WatchResource ? WatchHandlers<WatchRow<N, R>, WatchKey<N>> : never,
    options: { signal?: AbortSignal } = {},
  ): Promise<Subscription> {
    const { select, unwatchable } = this.state;
    const search = this.fullSearch;
    if (!watchable.has(this.resource)) throw new TypeError(`Tsunagi sends no events for ${this.resource}`);
    if (unwatchable !== undefined) throw new TypeError(unwatchable);
    const key: string = resources[this.resource].key;
    const selected = select ? [...new Set([...select, key])] : null;
    const query = this.with<R>({ select: selected });
    return watch(handlers as WatchHandlers<unknown, unknown>, {
      protocol: this.protocol,
      connection: this.protocol.connection,
      path: resources[this.resource].path,
      events: resources[this.resource].path.split("/").at(-1)!.replaceAll("-", "_"),
      key,
      keyWire: this.fields[key]!.wire,
      search,
      selected,
      // From the description's x-from: a search follows what it reads, a field what it is built from.
      related: [...new Set([
        ...(search === undefined ? [] : (resources[this.resource].search as { from: readonly string[] } | null)?.from ?? []),
        ...(selected ?? Object.keys(this.fields)).flatMap(name => this.fields[name]!.from ?? []),
      ])],
      params: narrow => {
        const params = query.params(false);
        return { ...params, where: [...params.where, ...narrow.where ?? []], ...(narrow.search === undefined ? {} : { search: narrow.search }) };
      },
      decode: raw => decodeObject(this.fields, raw, selected),
    }, options.signal);
  }

  /**
   * Shows this query's cards or notes in Anki's Browser: its search and is()
   * states, live as the Browser keeps them. Resolves once the Browser shows
   * them; raises as any request does. A query with no search shows every one.
   */
  async openBrowser(this: Query<N & BrowserResource, R, W, true>, options: WriteOptions = {}): Promise<void> {
    if (this.resource !== "cards" && this.resource !== "notes") throw new TypeError(`Anki's Browser shows cards and notes, not ${this.resource}`);
    if (this.state.unbrowsable !== undefined) throw new TypeError(this.state.unbrowsable);
    const search = this.fullSearch;
    await this.protocol.openBrowser(search === undefined || !search.trim() ? "deck:*" : search, options);
  }

  private params(total: boolean): QueryParams {
    const { select, scalar, where, order, distinctOn } = this.state;
    const search = this.fullSearch;
    return {
      ...(select ? { select: select.map(name => this.fields[name]!.wire).join(",") } : {}),
      shape: scalar ? "scalar" : "object",
      where,
      ...(search === undefined ? {} : { search }),
      ...(order === undefined ? {} : { order }),
      ...(distinctOn === undefined ? {} : { distinct_on: distinctOn }),
      ...(total ? { include: "total" } : {}),
    };
  }
  private decode(value: unknown): R {
    const { select, scalar } = this.state;
    // Every property is decoded with its field's description.
    if (scalar) return decodeField(this.fields[select![0]!]!, value) as R;
    return decodeObject(this.fields, value, select) as R;
  }
  private async readPage(size: number, total: boolean, cursor: string | null, seen: ReadonlySet<string>, options: RequestOptions): Promise<Page<R>> {
    options.signal?.throwIfAborted();
    const response = await this.protocol.query(resources[this.resource].path, this.params(total), size, cursor, options);
    if (response.cursor !== null && (response.cursor === cursor || seen.has(response.cursor))) throw new ProtocolError("Server repeated a pagination cursor");
    if (total && response.total === null) throw new ProtocolError("Missing total");
    const visited = new Set(seen);
    if (response.cursor !== null) visited.add(response.cursor);
    return {
      items: response.items.map(item => this.decode(item)),
      hasMore: response.cursor !== null,
      total: response.total,
      next: async (nextOptions = {}) => response.cursor === null ? null : this.readPage(size, total, response.cursor, visited, nextOptions),
    };
  }
}

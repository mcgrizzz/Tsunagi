import { ProtocolError } from "./errors.js";
import { DraftProtocol, filter, object } from "./protocol.js";
import type { FilterOperator, QuerySpec, Resource } from "./protocol.js";
import { positive } from "./transport.js";
import type { RequestOptions } from "./types.js";

type Key<T> = Extract<keyof T, string>;
type ScalarKey<T> = { [K in Key<T>]: T[K] extends string | number | null ? K : never }[Key<T>];
type Operator<V> = "eq" | "ne" | (NonNullable<V> extends number ? "gt" | "gte" | "lt" | "lte" : "contains");

export interface Page<T> {
  readonly items: readonly T[];
  readonly hasMore: boolean;
  /** Retains the query, size, and opaque cursor, but not a previous abort signal. */
  next(options?: RequestOptions): Promise<Page<T> | null>;
}
export interface PageOptions extends RequestOptions { size?: number }

/** Immutable and lazy. Only take/page/iterate execute requests. */
export class Query<T extends object, R, Sort extends string> implements AccessTarget {
  declare readonly [accessTarget]: true;
  constructor(
    protected readonly protocol: DraftProtocol,
    protected readonly resource: Resource<T, Sort>,
    private readonly selected: readonly Key<T>[],
    private readonly spec: QuerySpec,
    private readonly scalar = false,
    private readonly filterFields: readonly Key<T>[] = [],
  ) {
    registerAccess(this, protocol, `GET ${resource.path}`);
  }

  /** Fetch a fresh discovery report without running this query. */
  async checkAccess(options: RequestOptions = {}): Promise<AccessDecision> {
    return new AccessSnapshot(await this.protocol.capabilities(options), this.protocol).check(this);
  }

  private with(spec: QuerySpec, filterFields = this.filterFields): Query<T, R, Sort> {
    return new Query(this.protocol, this.resource, this.selected, spec, this.scalar, filterFields);
  }
  search(search: string): Query<T, R, Sort> {
    if (typeof search !== "string") throw new TypeError("search must be a string");
    return this.with({ ...this.spec, search });
  }
  where<K extends ScalarKey<T>>(field: K, operator: Operator<NoInfer<T[K]>>, value: NoInfer<T[K]>): Query<T, R, Sort> {
    this.checkField(field);
    const description = this.resource.fields[field];
    if (!description.scalar || (value !== null && typeof value !== description.scalar)) throw new TypeError("Filter value does not match the field type");
    if (operator === "contains" && (description.scalar !== "string" || value === null)) throw new TypeError("contains requires a string");
    if (["gt", "gte", "lt", "lte"].includes(operator) && (description.scalar !== "number" || value === null)) throw new TypeError("Comparison requires a number");
    if ((field === "id" || field.endsWith("_id")) && typeof value === "number" && !Number.isSafeInteger(value)) throw new TypeError("ID filter must use a safe integer");
    if (this.spec.distinct_on && !description.column) throw new TypeError("distinctOn requires column filters");
    const clause = filter(field, operator as FilterOperator, value);
    return this.with({ ...this.spec, where: [...this.spec.where, clause] }, [...this.filterFields, field]);
  }
  orderBy(field: Sort, direction: "asc" | "desc" = "asc"): Query<T, R, Sort> {
    if (!this.resource.sorts.includes(field) || !["asc", "desc"].includes(direction)) throw new TypeError("Unsupported sort");
    return this.with({ ...this.spec, order: `${field}:${direction}` });
  }
  distinctOn(field: ScalarKey<T>): Query<T, R, Sort> {
    this.checkField(field);
    if (!this.resource.fields[field].column || this.filterFields.some(key => !this.resource.fields[key].column)) {
      throw new TypeError("distinctOn and its filters must use supported column fields");
    }
    return this.with({ ...this.spec, distinct_on: field });
  }
  select<const K extends readonly [Key<T>, ...Key<T>[]]>(...fields: K): Query<T, Pick<T, K[number]>, Sort> {
    if (!fields.length) throw new TypeError("Select at least one field");
    fields.forEach(field => this.checkField(field));
    const selected = [...new Set(fields)];
    return new Query(this.protocol, this.resource, selected, { ...this.spec, select: selected.join(","), shape: "object" }, false, this.filterFields);
  }
  values<K extends ScalarKey<T>>(field: K): Query<T, T[K], Sort> {
    this.checkField(field);
    // The wire scalar shape only accepts scalar selections.
    if (!this.resource.fields[field].scalar) throw new TypeError("values requires a scalar field");
    return new Query(this.protocol, this.resource, [field], { ...this.spec, select: field, shape: "scalar" }, true, this.filterFields);
  }
  async take(count: number, options: RequestOptions = {}): Promise<R[]> {
    if (!Number.isSafeInteger(count) || count < 0) throw new RangeError("count must be a nonnegative safe integer");
    options.signal?.throwIfAborted();
    if (count === 0) return [];
    return [...(await this.readPage(count, null, new Set(), options)).items];
  }
  page(options: PageOptions = {}): Promise<Page<R>> {
    return this.readPage(positive(options.size ?? 50, "size"), null, new Set(), options);
  }
  async *iterate(options: PageOptions = {}): AsyncGenerator<R> {
    let page: Page<R> | null = await this.page({ ...options, size: options.size ?? 100 });
    while (page) {
      for (const item of page.items) { options.signal?.throwIfAborted(); yield item; }
      options.signal?.throwIfAborted();
      page = await page.next(options);
    }
  }
  private checkField(field: Key<T>): void {
    if (!Object.hasOwn(this.resource.fields, field)) throw new TypeError(`Unsupported field: ${field}`);
  }
  private decode(value: unknown): R {
    if (this.scalar) return this.resource.fields[this.selected[0]!].decode(value) as R;
    const row = object(value);
    const result: Record<string, unknown> = {};
    for (const key of this.selected) result[key] = this.resource.fields[key].decode(row[key]);
    // Every selected property has been decoded using its resource schema.
    return result as R;
  }
  private async readPage(size: number, cursor: string | null, seen: ReadonlySet<string>, options: RequestOptions): Promise<Page<R>> {
    options.signal?.throwIfAborted();
    const response = await this.protocol.query(this.resource.path, this.spec, size, cursor, options);
    if (response.cursor !== null && (response.cursor === cursor || seen.has(response.cursor))) throw new ProtocolError("Server repeated a pagination cursor");
    const visited = new Set(seen);
    if (response.cursor !== null) visited.add(response.cursor);
    return {
      items: response.items.map(item => this.decode(item)),
      hasMore: response.cursor !== null,
      next: async (nextOptions = {}) => response.cursor === null ? null : this.readPage(size, response.cursor, visited, nextOptions),
    };
  }
}
import { AccessSnapshot } from "./access.js";
import type { AccessDecision } from "./access.js";
import { accessTarget, registerAccess } from "./access-target.js";
import type { AccessTarget } from "./access-target.js";

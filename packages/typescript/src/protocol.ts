/** Current HTTP contract. Keep changing endpoint/envelope rules in this module. */
import { ProtocolError, WriteOutcomeUnknownError } from "./errors.js";
import { Transport } from "./transport.js";
import type { JsonResponse } from "./transport.js";
import type { Card, CreationItem, CreationReport, Note, NoteField, NoteInput, NotePatch, Reference, RequestOptions, SyncResult, WriteOptions } from "./types.js";

export type Decoder<T> = (value: unknown) => T;
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ProtocolError("Expected a JSON object");
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== "string") throw new ProtocolError("Expected a string");
  return value;
}
function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new ProtocolError("Expected a finite number");
  return value;
}
function id(value: unknown): number {
  const result = number(value);
  if (!Number.isSafeInteger(result) || result <= 0) throw new ProtocolError("Expected a positive safe integer ID");
  return result;
}
export function inputId(value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw new TypeError("ID must be a positive safe integer");
  return value;
}
function array<T>(value: unknown, decode: Decoder<T>): T[] {
  if (!Array.isArray(value)) throw new ProtocolError("Expected an array");
  return value.map(decode);
}
const nullableString = (value: unknown) => value === null ? null : string(value);
const noteField: Decoder<NoteField> = value => {
  const row = object(value);
  return { name: string(row.name), value: string(row.value), ord: number(row.ord) };
};

export interface Field<T> { decode: Decoder<T>; scalar?: "number" | "string"; column?: boolean }
export interface Resource<T extends object, Sort extends string> {
  path: string;
  fields: { [K in keyof T]: Field<T[K]> };
  sorts: readonly Sort[];
}
export const cards: Resource<Card, "due" | "interval" | "reps" | "lapses"> = {
  path: "/v1/cards",
  fields: {
    id: { decode: id, scalar: "number", column: true },
    note_id: { decode: id, scalar: "number", column: true },
    deck_id: { decode: id, scalar: "number", column: true },
    interval: { decode: number, scalar: "number", column: true },
    due: { decode: number, scalar: "number", column: true },
    queue: { decode: number, scalar: "number", column: true },
    reps: { decode: number, scalar: "number", column: true },
    lapses: { decode: number, scalar: "number", column: true },
    deck_name: { decode: string, scalar: "string" },
    question: { decode: nullableString, scalar: "string" },
    answer: { decode: nullableString, scalar: "string" },
  },
  sorts: ["due", "interval", "reps", "lapses"],
};
export const notes: Resource<Note, "id" | "note_modified" | "sort_field"> = {
  path: "/v1/notes",
  fields: {
    id: { decode: id, scalar: "number", column: true },
    model_id: { decode: id, scalar: "number", column: true },
    model_name: { decode: string, scalar: "string" },
    first_field: { decode: string, scalar: "string" },
    tags: { decode: value => array(value, string) },
    fields: { decode: value => array(value, noteField) },
  },
  sorts: ["id", "note_modified", "sort_field"],
};

export interface QuerySpec {
  select: string;
  shape: "object" | "scalar";
  where: readonly string[];
  search?: string;
  order?: string;
  distinct_on?: string;
}
export interface WirePage { items: unknown[]; cursor: string | null }
export interface JobSnapshot {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "aborted";
  result: unknown;
  error: string | null;
}

const symbols = { eq: "==", ne: "!=", gt: ">", gte: ">=", lt: "<", lte: "<=", contains: "~=" } as const;
export type FilterOperator = keyof typeof symbols;
export function filter(field: string, operator: FilterOperator, value: unknown): string {
  if (!Object.hasOwn(symbols, operator)) throw new TypeError("Unsupported filter operator");
  if (value !== null && typeof value !== "string" && typeof value !== "number") throw new TypeError("Expected a scalar filter value");
  if (typeof value === "number" && !Number.isFinite(value)) throw new TypeError("Expected a finite filter value");
  return `${field}${symbols[operator]}${JSON.stringify(value)}`;
}

function reference(target: Record<string, unknown>, prefix: "deck" | "model", value: Reference): void {
  if (typeof value === "string" && value.length > 0) target[`${prefix}_name`] = value;
  else if (value && typeof value === "object" && Object.keys(value).length === 1 && "id" in value) {
    target[`${prefix}_id`] = inputId(value.id);
  } else throw new TypeError("Use a nonempty name or an { id } reference");
}
function fields(value: Readonly<Record<string, string>>): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.values(value).some(v => typeof v !== "string")) {
    throw new TypeError("fields must map field names to strings");
  }
  return Object.fromEntries(Object.entries(value));
}
function tags(value: readonly string[]): string[] {
  if (!Array.isArray(value) || value.some(v => typeof v !== "string")) throw new TypeError("tags must be strings");
  return [...value];
}
export function encodeNote(input: NoteInput): Record<string, unknown> {
  const result: Record<string, unknown> = { fields: fields(input.fields) };
  reference(result, "deck", input.deck);
  reference(result, "model", input.noteType);
  if (input.tags !== undefined) result.tags = tags(input.tags);
  return result;
}
function encodePatch(input: NotePatch): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (input.fields !== undefined) result.fields = fields(input.fields);
  if (input.tags !== undefined) result.tags = tags(input.tags);
  if (input.addTags !== undefined) result.add_tags = tags(input.addTags);
  if (input.removeTags !== undefined) result.remove_tags = tags(input.removeTags);
  return result;
}

/** Reject incomplete/duplicate positions so an item can never disappear as a success. */
export function decodeCreation(value: unknown, count: number): CreationReport {
  const body = object(value);
  const items = new Map<number, CreationItem>();
  const insert = (row: Record<string, unknown>, item: CreationItem) => {
    if (!Number.isSafeInteger(row.index) || item.index < 0 || item.index >= count || items.has(item.index)) {
      throw new ProtocolError("Invalid or duplicate creation result index");
    }
    items.set(item.index, item);
  };
  for (const row of array(body.created, object)) {
    insert(row, { ok: true, index: number(row.index), value: { id: id(row.id) } });
  }
  for (const row of array(body.failed, object)) {
    const index = number(row.index);
    insert(row, { ok: false, index, error: { index, code: string(row.code), message: string(row.message), details: row } });
  }
  if (items.size !== count) throw new ProtocolError("Missing creation result for a submitted note");
  return { items: [...items.values()].sort((a, b) => a.index - b.index) };
}
export function decodeSync(value: unknown): SyncResult {
  const row = object(value);
  return { status: number(row.status), server_message: string(row.server_message) };
}

/** SDK action names share the server's effective operation states. */
export const accessOperations = {
  "cards.query": "GET /v1/cards",
  "notes.query": "GET /v1/notes",
  "notes.create": "POST /v1/notes",
  "notes.createMany": "POST /v1/notes",
  "notes.update": "PATCH /v1/notes/{id}",
  "collection.sync": "POST /v1/collection:sync",
  "collection.startSync": "POST /v1/collection:sync",
} as const;

function capabilityState(value: unknown): CapabilityState {
  const row = object(value);
  const status = string(row.status);
  if (status !== "available" && status !== "disabled" && status !== "unsupported") {
    throw new ProtocolError("Unknown capability status");
  }
  return Object.freeze({
    status,
    reason: row.reason == null ? null : string(row.reason),
    setting: row.setting == null ? null : string(row.setting),
  });
}

function capabilityMap<T>(value: unknown, decode: Decoder<T>): Readonly<Record<string, T>> {
  return Object.freeze(Object.fromEntries(Object.entries(object(value)).map(([key, item]) => [key, decode(item)])));
}

function decodeCapabilities(value: unknown): Capabilities {
  const row = object(value);
  const caller = object(row.caller);
  const versions = object(row.versions);
  if (typeof caller.this_computer !== "boolean") throw new ProtocolError("Invalid caller location");
  return Object.freeze({
    versions: Object.freeze({ api: string(versions.api), addon: string(versions.addon), anki: string(versions.anki) }),
    caller: Object.freeze({
      name: string(caller.name), role: string(caller.role),
      this_computer: caller.this_computer, host: string(caller.host),
    }),
    operations: capabilityMap<OperationCapability>(row.operations, value => {
      const operation = object(value);
      return Object.freeze({
        ...capabilityState(operation), operation_id: string(operation.operation_id),
        options: capabilityMap(operation.options, capabilityState),
      });
    }),
    features: capabilityMap(row.features, capabilityState),
  });
}

export class DraftProtocol {
  constructor(readonly transport: Transport) {}

  async capabilities(options: RequestOptions): Promise<Capabilities> {
    return decodeCapabilities((await this.transport.request("GET", "/v1/capabilities", options)).data);
  }

  async query(path: string, spec: QuerySpec, limit: number, cursor: string | null, options: RequestOptions): Promise<WirePage> {
    const body = { ...spec, limit, ...(cursor === null ? {} : { cursor }) };
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(body)) {
      if (Array.isArray(value)) for (const clause of value) params.append(key, clause);
      else params.set(key, String(value));
    }
    const response = this.transport.url(path, params).href.length <= this.transport.maxGetUrlLength
      ? await this.transport.request("GET", path, { ...options, query: params })
      : await this.transport.request("POST", `${path}/query`, { ...options, body });
    const data = object(response.data);
    if (!Array.isArray(data.items) || data.items.length > limit) throw new ProtocolError("Invalid page items or result limit exceeded");
    const next = data.next_cursor ?? null;
    if (next !== null && (typeof next !== "string" || !next)) throw new ProtocolError("Invalid next_cursor");
    return { items: data.items, cursor: next };
  }

  async create(input: readonly NoteInput[], options: WriteOptions): Promise<CreationReport> {
    return this.write("POST", "/v1/notes", { ...options, body: input.map(encodeNote), write: "keyed" }, response => decodeCreation(response.data, input.length));
  }

  async update(noteId: number, input: NotePatch, options: WriteOptions): Promise<void> {
    return this.write("PATCH", `/v1/notes/${inputId(noteId)}`, { ...options, body: encodePatch(input), write: "keyed" }, response => {
      if (!Object.hasOwn(object(response.data), "result")) throw new ProtocolError("Missing mutation result");
    });
  }

  async startSync(options: import("./types.js").JobStartOptions): Promise<{ jobId: string } | { result: SyncResult }> {
    return this.write("POST", "/v1/collection:sync", { ...options, write: "keyed" }, response => {
      if (response.status === 202) {
        const jobId = string(object(response.data).job_id);
        if (!jobId) throw new ProtocolError("Missing job ID");
        return { jobId };
      }
      return { result: decodeSync(response.data) };
    });
  }

  private async write<T>(method: "POST" | "PATCH", path: string, options: WriteOptions & { body?: unknown; write: "keyed" | "unkeyed" }, decode: (response: JsonResponse) => T): Promise<T> {
    const response = await this.transport.request(method, path, options);
    try { return decode(response); }
    catch (error) { throw new WriteOutcomeUnknownError(response.idempotencyKey, error); }
  }

  async getJob(jobId: string, options: RequestOptions): Promise<JobSnapshot> {
    const response = await this.transport.request("GET", `/v1/jobs/${encodeURIComponent(jobId)}`, options);
    const row = object(response.data);
    const status = string(row.status);
    if (row.id !== jobId || !["queued", "running", "done", "failed", "aborted"].includes(status)) throw new ProtocolError("Invalid job identity or status");
    return { id: jobId, status: status as JobSnapshot["status"], result: row.result, error: row.error == null ? null : string(row.error) };
  }
}
import type { Capabilities, CapabilityState, OperationCapability } from "./types.js";

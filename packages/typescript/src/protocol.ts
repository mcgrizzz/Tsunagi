/**
 * The HTTP contract: requests through the generated operations, bodies checked
 * against the server's schemas, answers decoded through the generated tables.
 * The friendly inputs (types.ts) map onto the wire bodies here.
 */
import type { AccessSnapshot } from "./access.js";
import { decodeAs, deepFreeze, object, wireValue } from "./decode.js";
import { ProtocolError, WriteOutcomeUnknownError } from "./errors.js";
import type { EventConnection } from "./events.js";
import { operations, resources } from "./generated.js";
import type {
  Answers, Capabilities, CreatedNote, DuplicateScopeOptionsBody, Health, Job, MediaFailure, MediaUploadBody,
  NoteAttachmentBody, NoteCheck, NoteCreateBody, NoteFailure, NotePatchBody, NoteUpsertBody, Requests, SyncResult,
  UpdatedNote, UploadedFile, UpsertFailure,
} from "./generated.js";
import type { Transport } from "./transport.js";
import type {
  Attachment, DuplicateCheck, FileSource, ItemReport, ItemResult, MediaInput, NoteInput, NotePatch,
  NoteUpsert, OpenAddInput, Reference, RequestOptions, UpsertedNote, WriteOptions,
} from "./types.js";

export { object } from "./decode.js";
export type Operation = keyof typeof operations;
/** The capabilities report's name for an operation, e.g. `POST /v1/notes`. */
export const operationName = (operation: Operation) => `${operations[operation].method} ${operations[operation].path}`;

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

export interface QueryParams {
  select?: string;
  shape: "object" | "scalar";
  where: readonly string[];
  search?: string;
  order?: string;
  distinct_on?: string;
  include?: string;
}
export interface WirePage { items: unknown[]; cursor: string | null; total: number | null }

// ----- Request bodies: client names in, the API's names out -----

function deckRef(value: Reference): { deck_name: string } | { deck_id: number } {
  if (typeof value === "string" && value.length > 0) return { deck_name: value };
  if (value && typeof value === "object" && Object.keys(value).length === 1 && "id" in value) return { deck_id: inputId(value.id) };
  throw new TypeError("Use a nonempty name or an { id } reference");
}
function noteTypeRef(value: Reference): { note_type_name: string } | { note_type_id: number } {
  const deck = deckRef(value);
  return "deck_name" in deck ? { note_type_name: deck.deck_name } : { note_type_id: deck.deck_id };
}
function fields(value: Readonly<Record<string, string>>): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.values(value).some(v => typeof v !== "string")) {
    throw new TypeError("fields must map field names to strings");
  }
  return Object.fromEntries(Object.entries(value));
}
function strings(value: readonly string[], name: string): string[] {
  if (!Array.isArray(value) || value.some(v => typeof v !== "string")) throw new TypeError(`${name} must be strings`);
  return [...value];
}
function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
function source(file: FileSource): { data: string } | { url: string } | { path: string } {
  const given = (["data", "url", "path"] as const).filter(key => file[key] !== undefined);
  if (given.length !== 1) throw new TypeError("Give a file exactly one of data, url or path");
  if (file.data !== undefined) {
    if (!(file.data instanceof Uint8Array)) throw new TypeError("data must be a Uint8Array");
    return { data: base64(file.data) };
  }
  return given[0] === "url" ? { url: string(file.url) } : { path: string(file.path) };
}
type Files = Pick<NoteCreateBody, "audio" | "video" | "picture">;
function attachments(input: NoteInput | NotePatch): Files {
  const out: Files = {};
  for (const kind of ["audio", "video", "picture"] as const) {
    const list: readonly Attachment[] | undefined = input[kind];
    if (list === undefined) continue;
    if (!Array.isArray(list)) throw new TypeError(`${kind} must be a list`);
    out[kind] = list.map((file): NoteAttachmentBody => ({
      ...source(file),
      ...(file.filename === undefined ? {} : { filename: string(file.filename) }),
      ...(file.fields === undefined ? {} : { fields: strings(file.fields, "fields") }),
    }));
  }
  return out;
}
function duplicates(check: DuplicateCheck | undefined): Pick<NoteCreateBody, "duplicate_scope" | "duplicate_scope_options"> {
  if (check === undefined) return {};
  if (check.scope !== undefined && check.scope !== "collection" && check.scope !== "deck") throw new TypeError("scope is collection or deck");
  const options: DuplicateScopeOptionsBody = {
    ...(check.deck === undefined ? {} : { deck_name: check.deck }),
    ...(check.includeSubdecks === undefined ? {} : { check_children: check.includeSubdecks }),
    ...(check.allNoteTypes === undefined ? {} : { check_all_note_types: check.allNoteTypes }),
  };
  return {
    ...(check.scope === undefined ? {} : { duplicate_scope: check.scope }),
    ...(Object.keys(options).length ? { duplicate_scope_options: options } : {}),
  };
}
export function encodeNote(input: NoteInput, allowDuplicate = false): NoteCreateBody {
  return {
    ...(allowDuplicate ? { allow_duplicate: true } : {}),
    fields: fields(input.fields),
    ...deckRef(input.deck),
    ...noteTypeRef(input.noteType),
    ...(input.tags === undefined ? {} : { tags: strings(input.tags, "tags") }),
    ...duplicates(input.duplicates),
    ...attachments(input),
  };
}
function encodePatch(input: NotePatch): NotePatchBody {
  return {
    ...(input.fields === undefined ? {} : { fields: fields(input.fields) }),
    ...(input.tags === undefined ? {} : { tags: strings(input.tags, "tags") }),
    ...(input.addTags === undefined ? {} : { add_tags: strings(input.addTags, "addTags") }),
    ...(input.removeTags === undefined ? {} : { remove_tags: strings(input.removeTags, "removeTags") }),
    ...(input.noteType === undefined ? {} : noteTypeRef(input.noteType)),
    ...attachments(input),
  };
}
const fieldRules = { keep: "keep", replace: "replace", replaceIfEmpty: "replace_if_empty", append: "append" } as const;
function encodeUpsert(input: NoteUpsert): NoteUpsertBody {
  const rules = input.fieldRules === undefined ? undefined : Object.fromEntries(Object.entries(input.fieldRules).map(([name, rule]) => {
    if (!Object.hasOwn(fieldRules, rule)) throw new TypeError(`Unknown field rule: ${rule}`);
    return [name, fieldRules[rule]];
  }));
  if (input.tagRule !== undefined && !["union", "replace", "keep"].includes(input.tagRule)) throw new TypeError(`Unknown tag rule: ${input.tagRule}`);
  const onMatch = {
    ...(rules === undefined ? {} : { fields: rules }),
    ...(input.tagRule === undefined ? {} : { tags: input.tagRule }),
    ...(input.separator === undefined ? {} : { separator: string(input.separator) }),
  };
  return {
    ...encodeNote(input),
    ...(input.matchField === undefined ? {} : { match: { field: string(input.matchField) } }),
    ...(Object.keys(onMatch).length ? { on_match: onMatch } : {}),
  };
}
/** Add Cards prefilled: a note as create takes it, without duplicate options. */
function encodeAddCards(input: OpenAddInput): Requests["guiAddCards"] {
  return {
    ...deckRef(input.deck),
    ...noteTypeRef(input.noteType),
    fields: fields(input.fields),
    ...(input.tags === undefined ? {} : { tags: strings(input.tags, "tags") }),
    ...attachments(input),
  };
}
export function encodeMedia(input: MediaInput): MediaUploadBody {
  return { filename: string(input.filename), ...source(input) };
}
/** Named values' wire codes, from the generated row description. */
export const flagCode = (flag: unknown) => wireValue(resources.cards.fields.flag, flag) as number;
export const ratingCode = (rating: unknown) => {
  if (rating === null) throw new TypeError("Unknown value: null");
  return wireValue(resources.reviews.fields.rating, rating) as number;
};

// ----- Answers -----

/** One result per submitted item, in input order; a missing or repeated index is a protocol error. */
function items<T, F extends { index: number }>(count: number, lists: readonly (readonly { index: number; value: T }[])[], failed: readonly F[]): ItemReport<T, F> {
  const results = new Map<number, ItemResult<T, F>>();
  const insert = (index: number, item: ItemResult<T, F>) => {
    if (!Number.isSafeInteger(index) || index < 0 || index >= count || results.has(index)) {
      throw new ProtocolError("Invalid or duplicate item result index");
    }
    results.set(index, item);
  };
  for (const list of lists) for (const { index, value } of list) insert(index, { ok: true, index, value });
  for (const error of failed) insert(error.index, { ok: false, index: error.index, error });
  if (results.size !== count) throw new ProtocolError("Missing result for a submitted item");
  return { items: [...results.values()].sort((a, b) => a.index - b.index) };
}

export function decodeSync(value: unknown): SyncResult {
  return decodeAs<SyncResult>("SyncResult", value);
}

// ----- Requests -----

interface Call<O extends Operation> {
  params?: Readonly<Record<string, string | number>>;
  query?: URLSearchParams | undefined;
  body?: Requests[O];
  options: WriteOptions;
}

export class DraftProtocol {
  /** The client's event connection, for watches and listeners. */
  connection!: EventConnection;
  /** The client's access(), kept current: listeners check their events option with it. */
  access!: () => Promise<AccessSnapshot>;
  constructor(readonly transport: Transport) {}

  /**
   * One operation, its answer decoded by status, then `then` applied to it.
   * A write is keyed; an answer it can't use (a decoding error, a bad item
   * report) leaves the outcome unknown, with the key.
   */
  private async call<O extends Operation, T>(operation: O, { params = {}, query, body, options }: Call<O>,
    then: (status: number, value: Answers[O][keyof Answers[O]]) => T): Promise<T> {
    const { method, path, answers } = operations[operation];
    const url = path.replace(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(String(params[name])));
    const write = method !== "GET" && operation !== "notesCheck" ? "keyed" as const : false as const;
    const response = await this.transport.request(method, url, {
      ...options, write, query, ...(body === undefined ? {} : { body }),
    });
    try {
      const type = (answers as Readonly<Record<string, string | null>>)[String(response.status)];
      if (type === undefined) throw new ProtocolError(`Unexpected status ${response.status}`);
      const value = type === null ? response.data : decodeAs(type as Parameters<typeof decodeAs>[0], response.data);
      return then(response.status, deepFreeze(value) as Answers[O][keyof Answers[O]]);
    } catch (error) {
      if (write) throw new WriteOutcomeUnknownError(response.idempotencyKey, error);
      throw error;
    }
  }

  capabilities(options: RequestOptions): Promise<Capabilities> {
    return this.call("capabilities", { options }, (_, value) => value);
  }
  health(options: RequestOptions): Promise<Health> {
    return this.call("health", { options }, (_, value) => value);
  }

  async query(path: string, spec: QueryParams, limit: number, cursor: string | null, options: RequestOptions): Promise<WirePage> {
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
    const total = data.total == null ? null : number(data.total);
    return { items: data.items, cursor: next, total };
  }

  createNotes(input: readonly NoteInput[], include: readonly string[], options: WriteOptions,
    allowDuplicate = false): Promise<ItemReport<CreatedNote, NoteFailure>> {
    return this.call("notesCreate", { query: withInclude(include), body: input.map(note => encodeNote(note, allowDuplicate)), options },
      (_, value) => items(input.length, [value.created.map(note => ({ index: note.index, value: note }))], value.failed));
  }
  async updateNote(noteId: number, input: NotePatch, options: WriteOptions): Promise<void> {
    await this.call("notesUpdate", { params: { id: inputId(noteId) }, body: encodePatch(input), options }, () => undefined);
  }
  upsertNotes(input: readonly NoteUpsert[], include: readonly string[], options: WriteOptions): Promise<ItemReport<UpsertedNote, UpsertFailure>> {
    return this.call("notesUpsert", { query: withInclude(include), body: input.map(encodeUpsert), options },
      (_, value) => items<UpsertedNote, UpsertFailure>(input.length, [
        value.created.map((note: CreatedNote) => ({ index: note.index, value: { action: "created" as const, ...note } })),
        value.updated.map((note: UpdatedNote) => ({ index: note.index, value: { action: "updated" as const, ...note } })),
      ], value.failed));
  }
  checkNotes(input: readonly NoteInput[], include: readonly string[], options: RequestOptions): Promise<NoteCheck[]> {
    return this.call("notesCheck", { query: withInclude(include), body: input.map(note => encodeNote(note)), options }, (_, value) => {
      if (value.results.length !== input.length || value.results.some((row, i) => row.index !== i)) {
        throw new ProtocolError("Note checks do not match the request");
      }
      return value.results;
    });
  }
  uploadMedia(input: readonly MediaInput[], options: WriteOptions): Promise<ItemReport<UploadedFile, MediaFailure>> {
    return this.call("mediaUpload", { body: input.map(encodeMedia), options },
      (_, value) => items(input.length, [value.created.map(file => ({ index: file.index, value: file }))], value.failed));
  }
  /** Opens a window in Anki; resolves once Anki shows it. */
  async openBrowser(query: string, options: WriteOptions): Promise<void> {
    await this.call("guiBrowse", { body: { query: string(query) }, options }, () => undefined);
  }
  async openEditor(noteId: number, options: WriteOptions): Promise<void> {
    await this.call("guiEditNote", { body: { note_id: inputId(noteId) }, options }, () => undefined);
  }
  async openAdd(input: OpenAddInput, options: WriteOptions): Promise<void> {
    await this.call("guiAddCards", { body: encodeAddCards(input), options }, () => undefined);
  }
  async openDeck(screen: "guiDeckOverview" | "guiDeckReview", deck: Reference, options: WriteOptions): Promise<void> {
    await this.call(screen, { body: deckRef(deck), options }, () => undefined);
  }

  /** A verb on a set of rows: how many it changed. */
  verb<O extends "notesDelete" | Extract<Operation, `cards${string}`>>(operation: O, body: Requests[O], options: WriteOptions): Promise<{ affected: number }> {
    return this.call(operation, { body, options }, (_, value) => ({ affected: (value as { affected: number }).affected }));
  }

  startSync(options: WriteOptions): Promise<{ jobId: string } | { result: SyncResult }> {
    return this.call("sync", { options }, (status, value) => {
      if (status === 202) {
        const { jobId } = value as Answers["sync"][202];
        if (!jobId) throw new ProtocolError("Missing job ID");
        return { jobId };
      }
      return { result: value as SyncResult };
    });
  }
  getJob(jobId: string, options: RequestOptions): Promise<Job> {
    return this.call("job", { params: { job_id: jobId }, options }, (_, value) => {
      if (value.id !== jobId) throw new ProtocolError("Invalid job identity");
      return value;
    });
  }
}

function withInclude(include: readonly string[]): URLSearchParams | undefined {
  return include.length ? new URLSearchParams({ include: include.join(",") }) : undefined;
}

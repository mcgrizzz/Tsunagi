export type {
  Rows, Card, Note, Review, Deck, NoteType, DeckPreset, Tag, MediaFile, Addon, MemoryState, NoteField, NoteTypeField, CardTemplate,
  CreatedNote, UpdatedNote, StoredFile, UploadedFile, NoteFailure, UpsertFailure, MediaFailure, AttachmentRef, NoteCheck,
  VerbReport, SyncResult, Job, JobProgress, Health, CollectionHealth, Caller, Versions, Capabilities, CapabilityState,
  OperationCapability, Answer, DeckCounts, ErrorBody,
} from "./generated.js";
import type { CreatedNote, UpdatedNote } from "./generated.js";

/** A deck or note type by its name, or by `{ id }`. */
export type Reference = string | { readonly id: number };

/** A file sent with a note or to the media folder: its bytes, a URL Anki downloads, or a path on Anki's computer. */
export type FileSource =
  | { readonly data: Uint8Array; readonly url?: never; readonly path?: never }
  | { readonly url: string; readonly data?: never; readonly path?: never }
  | { readonly path: string; readonly data?: never; readonly url?: never };
export type MediaInput = FileSource & { readonly filename: string };
/** A file stored with a note; its reference is appended to `fields` (none: stored only). */
export type Attachment = FileSource & { readonly filename?: string; readonly fields?: readonly string[] };
export interface NoteFiles {
  audio?: readonly Attachment[];
  video?: readonly Attachment[];
  picture?: readonly Attachment[];
}

/** How a new note is checked against existing ones. */
export interface DuplicateCheck {
  /** Add the note even when it duplicates one. */
  allow?: boolean;
  /** Look in the whole collection (default) or in one deck: the note's own, or `deck`. */
  scope?: "collection" | "deck";
  deck?: string;
  includeSubdecks?: boolean;
  /** Compare with notes of every note type, not just the new note's. */
  allNoteTypes?: boolean;
}
export interface NoteInput extends NoteFiles {
  deck: Reference;
  noteType: Reference;
  fields: Readonly<Record<string, string>>;
  tags?: readonly string[];
  duplicates?: DuplicateCheck;
}
export interface NotePatch extends NoteFiles {
  /** Only the named fields change. */
  fields?: Readonly<Record<string, string>>;
  /** Replaces the note's tags. */
  tags?: readonly string[];
  addTags?: readonly string[];
  removeTags?: readonly string[];
  /** Changes the note's type; needs `fields`, since the new type's fields start empty. */
  noteType?: Reference;
}
export type FieldRule = "keep" | "replace" | "replaceIfEmpty" | "append";
export interface NoteUpsert extends NoteInput {
  /** The field that identifies the note, compared exactly within the note type. Default: the duplicate check. */
  matchField?: string;
  /** Per field when a note matches; "*" for the rest. Default replaceIfEmpty. */
  fieldRules?: Readonly<Record<string, FieldRule>>;
  /** union (default) adds the tags, replace sets them, keep leaves them. */
  tagRule?: "union" | "replace" | "keep";
  /** Between the old and new value for append. Default <br>. */
  separator?: string;
}

export type UpsertedNote = ({ action: "created" } & CreatedNote) | ({ action: "updated" } & UpdatedNote);
/** One submitted item's result: its value, or why the server refused it. */
export type ItemResult<T, F> = { ok: true; index: number; value: T } | { ok: false; index: number; error: F };
export interface ItemReport<T, F> { items: readonly ItemResult<T, F>[] }

export interface RequestOptions {
  signal?: AbortSignal | undefined;
  timeoutMs?: number | undefined;
}
export interface WriteOptions extends RequestOptions {
  /** Reuse only for the same logical request with identical input. */
  idempotencyKey?: string | undefined;
}
/** A keyed submission can recover the same accepted job; waiting only polls it. */
export type JobStartOptions = WriteOptions;

export interface WaitOptions extends RequestOptions {
  /** Overall polling deadline, unlike an individual HTTP request timeout. */
  timeoutMs?: number | undefined;
  pollIntervalMs?: number | undefined;
}

export interface ClientOptions {
  /** Server root; an optional reverse-proxy path prefix is preserved. */
  baseUrl: string;
  apiKey?: string | (() => string | undefined | Promise<string | undefined>);
  fetch?: typeof globalThis.fetch;
  requestTimeoutMs?: number;
  maxGetUrlLength?: number;
  makeIdempotencyKey?: () => string;
  /**
   * Keep access() current from Tsunagi's events, answering from the last
   * report until it may have changed. On by default; the client then holds a
   * connection open until close().
   */
  keepAccess?: boolean;
}

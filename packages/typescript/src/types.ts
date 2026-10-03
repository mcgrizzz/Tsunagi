/** A deliberately small public surface while the server's API rules evolve. */
export interface Card {
  id: number;
  note_id: number;
  deck_id: number;
  interval: number;
  due: number;
  queue: number;
  reps: number;
  lapses: number;
  deck_name: string;
  question: string | null;
  answer: string | null;
}

export interface NoteField { name: string; value: string; ord: number }
export interface Note {
  id: number;
  model_id: number;
  model_name: string;
  first_field: string;
  tags: string[];
  fields: NoteField[];
}

export type CardSummary = Pick<Card, "id" | "note_id" | "deck_id" | "interval" | "due">;
export type NoteSummary = Pick<Note, "id" | "model_name" | "first_field" | "tags">;
export type Reference = string | { readonly id: number };
export interface NoteInput {
  deck: Reference;
  noteType: Reference;
  fields: Readonly<Record<string, string>>;
  tags?: readonly string[];
}
export interface NotePatch {
  fields?: Readonly<Record<string, string>>;
  tags?: readonly string[];
  addTags?: readonly string[];
  removeTags?: readonly string[];
}

/** Receipt returned by creation, not a fetched Note. */
export interface CreatedNote { id: number }
export interface ItemFailure {
  index: number;
  code: string;
  message: string;
  details: Readonly<Record<string, unknown>>;
}
export type CreationItem =
  | { ok: true; index: number; value: CreatedNote }
  | { ok: false; index: number; error: ItemFailure };
export interface CreationReport { items: readonly CreationItem[] }

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

export type CapabilityStatus = "available" | "disabled" | "unsupported";
export interface CapabilityState {
  readonly status: CapabilityStatus;
  readonly reason: string | null;
  readonly setting: string | null;
}
export interface OperationCapability extends CapabilityState {
  readonly operation_id: string;
  readonly options: Readonly<Record<string, CapabilityState>>;
}
export interface Capabilities {
  readonly versions: Readonly<{ api: string; addon: string; anki: string }>;
  readonly caller: Readonly<{
    name: string;
    /** Display name only; use effective operation states to decide availability. */
    role: string;
    this_computer: boolean;
    host: string;
  }>;
  readonly operations: Readonly<Record<string, OperationCapability>>;
  readonly features: Readonly<Record<string, CapabilityState>>;
}
export interface SyncResult { status: number; server_message: string }
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
}

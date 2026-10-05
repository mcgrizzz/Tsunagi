import type { AccessSnapshot } from "./access.js";
import { AccessCache } from "./access-cache.js";
import { registerAccess } from "./access-target.js";
import { ItemRejectedError, JobFailedError, JobWaitTimeoutError, PartialWriteError, RequestTimeoutError } from "./errors.js";
import { resources } from "./generated.js";
import type { Answer, Card, CreatedNote, DeckCounts, DecksCounts, MediaFailure, NoteFailure, UploadedFile, UpsertFailure } from "./generated.js";
import { decodeAs } from "./decode.js";
import { decodeSync, DraftProtocol, flagCode, inputId, operationName, ratingCode } from "./protocol.js";
import type { Operation } from "./protocol.js";
import { Query } from "./query.js";
import { deadline, pause, positive, Transport } from "./transport.js";
import type {
  ClientOptions, Health, ItemReport, JobStartOptions, MediaInput, NoteCheck, NoteInput, NotePatch, NoteUpsert,
  Reference, RequestOptions, SyncResult, UpsertedNote, VerbReport, WaitOptions, WriteOptions,
} from "./types.js";
import { EventConnection } from "./events.js";
import { coalescing, listen } from "./listen.js";
import type { WatchResource } from "./query.js";
import type { Subscription } from "./subscription.js";

/** What a batch write does when some items fail: throw PartialWriteError (default), or return the report. */
export type OnError = { onError?: "throw" };
export type Collect = { onError: "collect" };
export interface CreateOptions extends WriteOptions {
  /** Return each note's card ids. */
  cards?: boolean;
  /** For a duplicate, name the notes it duplicates. */
  duplicateIds?: boolean;
}

function settle<T, F extends { index: number; code: string; message: string }>(
  report: ItemReport<T, F>, options: { onError?: "throw" | "collect" }): T[] | ItemReport<T, F> {
  if (options.onError !== undefined && !["throw", "collect"].includes(options.onError)) throw new TypeError("Invalid onError policy");
  if (options.onError === "collect") return report;
  if (report.items.some(item => !item.ok)) throw new PartialWriteError(report);
  return report.items.map(item => {
    if (!item.ok) throw new ItemRejectedError(item.error);
    return item.value;
  });
}
function single<T, F extends { index: number; code: string; message: string }>(report: ItemReport<T, F>): T {
  const item = report.items[0]!;
  if (!item.ok) throw new ItemRejectedError(item.error);
  return item.value;
}
function ids(list: readonly number[]): number[] {
  if (!Array.isArray(list)) throw new TypeError("Expected a list of ids");
  return list.map(inputId);
}
function list<T>(items: readonly T[]): readonly T[] {
  if (!Array.isArray(items)) throw new TypeError("Expected a list");
  return items;
}
const included = (flags: Readonly<Record<string, boolean | undefined>>) =>
  Object.entries(flags).filter(([, on]) => on).map(([name]) => name);
/** Registers a method as the operation it sends, for access checks. */
const sends = <T extends object>(method: T, protocol: DraftProtocol, operation: Operation) => registerAccess(method, protocol, operationName(operation));

/** A resource Tsunagi sends events for: a query, and `onChange`. */
class Resource<N extends WatchResource> extends Query<N> {
  /**
   * Called when something in this resource changed, without saying what (a
   * coarse signal: no request of its own). Changes during a call that is still
   * running (until what it returns settles) make one more call afterwards.
   */
  onChange(listener: () => unknown, options: { signal?: AbortSignal } = {}): Promise<Subscription> {
    const events = resources[this.resource].path.split("/").at(-1)!;
    const fire = coalescing(listener);
    let dropped = false;
    return listen(this.protocol.connection, { resources: [events] }, {
      resource: events,
      hear: (signal, subscription) => {
        if (signal.kind === "down") dropped = true;
        else if (signal.kind === "gap" || (signal.kind === "ready" && dropped)
          || (signal.kind === "message" && String(signal.message.type).startsWith(`${events}.`))) {
          dropped = false;
          fire(subscription);
        }
      },
    }, () => this.protocol.access(), options.signal);
  }
}

class Decks extends Resource<"decks"> {
  /** Called with the decks whose due counts changed (a card answered, cards added, buried...). */
  onCounts(listener: (counts: DeckCounts[]) => void, options: { signal?: AbortSignal } = {}): Promise<Subscription> {
    return listen(this.protocol.connection, { resources: ["decks"] }, {
      resource: "decks",
      hear: signal => {
        if (signal.kind !== "message" || signal.message.type !== "decks.counts") return;
        listener([...decodeAs<DecksCounts>("DecksCounts", signal.message).decks]);
      },
    }, () => this.protocol.access(), options.signal);
  }

  constructor(protocol: DraftProtocol) { super(protocol, "decks"); }
}

class Notes extends Resource<"notes"> {
  readonly create = sends(async (input: NoteInput, options: CreateOptions = {}): Promise<CreatedNote> =>
    single(await this.protocol.createNotes([input], included({ cards: options.cards, duplicate_ids: options.duplicateIds }), options)),
  this.protocol, "notesCreate");

  readonly createMany = sends(this.createManyImpl.bind(this), this.protocol, "notesCreate");
  private createManyImpl(input: readonly NoteInput[], options: CreateOptions & Collect): Promise<ItemReport<CreatedNote, NoteFailure>>;
  private createManyImpl(input: readonly NoteInput[], options?: CreateOptions & OnError): Promise<CreatedNote[]>;
  private async createManyImpl(input: readonly NoteInput[], options: CreateOptions & { onError?: "throw" | "collect" } = {}) {
    options.signal?.throwIfAborted();
    const report = list(input).length
      ? await this.protocol.createNotes(input, included({ cards: options.cards, duplicate_ids: options.duplicateIds }), options)
      : { items: [] };
    return settle(report, options);
  }

  /** Resolves when the PATCH completes: fields, tags and files in one undo step. Does not read the note again. */
  readonly update = sends(async (id: number, patch: NotePatch, options: WriteOptions = {}): Promise<void> =>
    this.protocol.updateNote(id, patch, options), this.protocol, "notesUpdate");

  /**
   * Is the note already saved? By the rules create uses to refuse a duplicate:
   * its first field, among notes of its note type (or the scope `duplicates`
   * gives). A read: nothing changes. Pass a list for one answer per note, in
   * order. A note naming a deck, note type or field that doesn't exist raises
   * ItemRejectedError, as create would.
   */
  readonly exists = sends(this.existsImpl.bind(this) as {
    (note: NoteInput, options?: RequestOptions): Promise<boolean>;
    (notes: readonly NoteInput[], options?: RequestOptions): Promise<boolean[]>;
  }, this.protocol, "notesCheck");
  private async existsImpl(input: NoteInput | readonly NoteInput[], options: RequestOptions = {}): Promise<boolean | boolean[]> {
    options.signal?.throwIfAborted();
    const many = Array.isArray(input);
    const notes = many ? list(input as readonly NoteInput[]) : [input as NoteInput];
    if (!notes.length) return [];
    const found = (await this.protocol.checkNotes(notes, [], options)).map(check => {
      if (check.state === "invalid") throw new ItemRejectedError({ index: check.index, code: "invalid", message: check.reason ?? "invalid" });
      return check.state === "duplicate";
    });
    return many ? found : found[0]!;
  }

  /** Could these notes be added, and if not, why? A read: nothing changes. One result per note, in order. */
  readonly check = sends(async (input: readonly NoteInput[], options: RequestOptions & { duplicateIds?: boolean } = {}): Promise<NoteCheck[]> =>
    this.protocol.checkNotes(list(input), included({ duplicate_ids: options.duplicateIds }), options),
  this.protocol, "notesCheck");

  /** Adds the note, or updates the one it matches. */
  readonly upsert = sends(async (input: NoteUpsert, options: WriteOptions & { cards?: boolean } = {}): Promise<UpsertedNote> =>
    single(await this.protocol.upsertNotes([input], included({ cards: options.cards }), options)),
  this.protocol, "notesUpsert");

  readonly upsertMany = sends(this.upsertManyImpl.bind(this), this.protocol, "notesUpsert");
  private upsertManyImpl(input: readonly NoteUpsert[], options: WriteOptions & { cards?: boolean } & Collect): Promise<ItemReport<UpsertedNote, UpsertFailure>>;
  private upsertManyImpl(input: readonly NoteUpsert[], options?: WriteOptions & { cards?: boolean } & OnError): Promise<UpsertedNote[]>;
  private async upsertManyImpl(input: readonly NoteUpsert[], options: WriteOptions & { cards?: boolean; onError?: "throw" | "collect" } = {}) {
    options.signal?.throwIfAborted();
    const report = list(input).length ? await this.protocol.upsertNotes(input, included({ cards: options.cards }), options) : { items: [] };
    return settle(report, options);
  }

  /** Deletes the notes and their cards, as one undo step. */
  readonly delete = sends(async (notes: readonly number[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("notesDelete", { note_ids: ids(notes) }, options), this.protocol, "notesDelete");

  constructor(protocol: DraftProtocol) { super(protocol, "notes"); }
}

type ForgetOptions = WriteOptions & { restorePosition?: boolean; resetCounts?: boolean };
type RepositionOptions = WriteOptions & { start?: number; step?: number; randomize?: boolean; shiftExisting?: boolean };

class Cards extends Resource<"cards"> {
  /** Called for every card answer, in Anki or through the API (`by`, `app`). Needs a role that allows card answers. */
  onAnswered(listener: (answer: Answer) => void, options: { signal?: AbortSignal } = {}): Promise<Subscription> {
    return listen(this.protocol.connection, { types: ["cards.answered"] }, {
      option: "cards.answered",
      hear: signal => {
        if (signal.kind !== "message" || signal.message.type !== "cards.answered") return;
        listener(decodeAs<Answer>("Answer", signal.message));
      },
    }, () => this.protocol.access(), options.signal);
  }

  readonly suspend = sends(async (cards: readonly number[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsSuspend", { card_ids: ids(cards) }, options), this.protocol, "cardsSuspend");
  readonly unsuspend = sends(async (cards: readonly number[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsUnsuspend", { card_ids: ids(cards) }, options), this.protocol, "cardsUnsuspend");
  readonly bury = sends(async (cards: readonly number[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsBury", { card_ids: ids(cards) }, options), this.protocol, "cardsBury");
  readonly unbury = sends(async (cards: readonly number[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsUnbury", { card_ids: ids(cards) }, options), this.protocol, "cardsUnbury");
  /** Makes the cards new again. */
  readonly forget = sends(async (cards: readonly number[], options: ForgetOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsForget", {
      card_ids: ids(cards), restore_position: options.restorePosition ?? false, reset_counts: options.resetCounts ?? false,
    }, options), this.protocol, "cardsForget");
  /** `days` in Anki's syntax: "0" today, "3" in three days, "3-7" a day in that range, "1!" also sets the interval. */
  readonly setDueDate = sends(async (cards: readonly number[], days: string, options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsSetDueDate", { card_ids: ids(cards), days }, options), this.protocol, "cardsSetDueDate");
  readonly changeDeck = sends(async (cards: readonly number[], deck: Reference, options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsChangeDeck", {
      card_ids: ids(cards), ...(typeof deck === "string" ? { deck_name: deck } : { deck_id: inputId(deck.id) }),
    }, options), this.protocol, "cardsChangeDeck");
  /** Moves new cards in the new queue. */
  readonly reposition = sends(async (cards: readonly number[], options: RepositionOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsReposition", {
      card_ids: ids(cards), starting_from: options.start ?? 0, step_size: options.step ?? 1,
      randomize: options.randomize ?? false, shift_existing: options.shiftExisting ?? false,
    }, options), this.protocol, "cardsReposition");
  readonly setFlag = sends(async (cards: readonly number[], flag: Card["flag"], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsSetFlag", { card_ids: ids(cards), flag: flagCode(flag) }, options), this.protocol, "cardsSetFlag");
  /** Answers the cards as the reviewer would, each with its own rating. */
  readonly answer = sends(async (answers: readonly { cardId: number; rating: "again" | "hard" | "good" | "easy" }[], options: WriteOptions = {}): Promise<VerbReport> =>
    this.protocol.verb("cardsAnswer", {
      answers: list(answers).map(answer => ({ card_id: inputId(answer.cardId), ease: ratingCode(answer.rating) })),
    }, options), this.protocol, "cardsAnswer");

  constructor(protocol: DraftProtocol) { super(protocol, "cards"); }
}

class Media extends Query<"media"> {
  /** Stores a file in Anki's media folder; Anki may rename it (see `filename`). */
  readonly upload = sends(async (file: MediaInput, options: WriteOptions = {}): Promise<UploadedFile> =>
    single(await this.protocol.uploadMedia([file], options)), this.protocol, "mediaUpload");

  readonly uploadMany = sends(this.uploadManyImpl.bind(this), this.protocol, "mediaUpload");
  private uploadManyImpl(files: readonly MediaInput[], options: WriteOptions & Collect): Promise<ItemReport<UploadedFile, MediaFailure>>;
  private uploadManyImpl(files: readonly MediaInput[], options?: WriteOptions & OnError): Promise<UploadedFile[]>;
  private async uploadManyImpl(files: readonly MediaInput[], options: WriteOptions & { onError?: "throw" | "collect" } = {}) {
    options.signal?.throwIfAborted();
    return settle(list(files).length ? await this.protocol.uploadMedia(files, options) : { items: [] }, options);
  }

  constructor(protocol: DraftProtocol) { super(protocol, "media"); }
}

export class SyncOperation {
  /** The current sync endpoint does not support aborting the server job. */
  readonly abortable = false;
  readonly id: string | null;
  private completed: SyncResult | undefined;

  constructor(private readonly protocol: DraftProtocol, submitted: { jobId: string } | { result: SyncResult }) {
    this.id = "jobId" in submitted ? submitted.jobId : null;
    this.completed = "result" in submitted ? submitted.result : undefined;
  }
  async wait(options: WaitOptions = {}): Promise<SyncResult> {
    options.signal?.throwIfAborted();
    if (this.completed) return { ...this.completed };
    let interval = positive(options.pollIntervalMs ?? 500, "pollIntervalMs");
    const scope = deadline(options.timeoutMs ?? 120_000, options.signal);
    try {
      while (true) {
        const job = await this.protocol.getJob(this.id!, { signal: scope.signal });
        if (job.status === "done") {
          this.completed = decodeSync(job.result);
          return { ...this.completed };
        }
        if (job.status === "failed" || job.status === "aborted") throw new JobFailedError(job.id, job.status, job.error);
        await pause(interval, { signal: scope.signal });
        interval = Math.min(interval * 1.5, 5_000);
      }
    } catch (error) {
      if (!options.signal?.aborted && scope.signal.aborted && scope.signal.reason instanceof RequestTimeoutError) {
        throw new JobWaitTimeoutError(this);
      }
      throw error;
    } finally { scope.close(); }
  }
}

export interface SyncOptions extends JobStartOptions {
  waitTimeoutMs?: number;
  pollIntervalMs?: number;
}

/** No I/O until a method is called. Framework-independent and fetch-injectable. */
export class Tsunagi {
  readonly cards: Cards;
  readonly notes: Notes;
  readonly reviews: Resource<"reviews">;
  readonly decks: Decks;
  readonly noteTypes: Resource<"noteTypes">;
  readonly deckPresets: Query<"deckPresets">;
  readonly tags: Resource<"tags">;
  readonly media: Media;
  readonly collection;
  readonly raw;
  private readonly transport: Transport;
  private readonly protocol: DraftProtocol;
  private readonly connection: EventConnection;
  private readonly accessCache: AccessCache;

  constructor(options: ClientOptions) {
    const transport = this.transport = new Transport(options);
    const protocol = this.protocol = new DraftProtocol(transport);
    this.connection = protocol.connection = new EventConnection(transport);
    const cache = this.accessCache = new AccessCache(protocol, this.connection, options.keepAccess ?? true, () => transport.apiKey());
    transport.refused = () => cache.invalidate();
    this.cards = new Cards(protocol);
    this.notes = new Notes(protocol);
    protocol.access = () => this.access();
    this.reviews = new Resource(protocol, "reviews");
    this.decks = new Decks(protocol);
    this.noteTypes = new Resource(protocol, "noteTypes");
    this.deckPresets = new Query(protocol, "deckPresets");
    this.tags = new Resource(protocol, "tags");
    this.media = new Media(protocol);
    const startSync = async (request: JobStartOptions = {}) => new SyncOperation(protocol, await protocol.startSync(request));
    this.collection = {
      startSync: sends(startSync, protocol, "sync"),
      sync: sends(async (request: SyncOptions = {}): Promise<SyncResult> => {
        // Validate waiting options before starting a remote mutation.
        if (request.waitTimeoutMs !== undefined) positive(request.waitTimeoutMs, "waitTimeoutMs");
        if (request.pollIntervalMs !== undefined) positive(request.pollIntervalMs, "pollIntervalMs");
        const operation = await startSync(request);
        return operation.wait({ signal: request.signal, timeoutMs: request.waitTimeoutMs, pollIntervalMs: request.pollIntervalMs });
      }, protocol, "sync"),
      /** Called as each sync starts and finishes, whoever started it. */
      onSync: (handlers: { started?(): void; finished?(): void }, options: { signal?: AbortSignal } = {}): Promise<Subscription> =>
        listen(this.connection, { types: ["sync"] }, {
          option: "sync",
          hear: signal => {
            if (signal.kind !== "message" || signal.message.type !== "sync") return;
            if (signal.message.phase === "started") handlers.started?.();
            else if (signal.message.phase === "finished") handlers.finished?.();
          },
        }, () => this.access(), options.signal),
    };
    this.raw = {
      /** Unknown JSON until the caller validates it. No generic cast to a result type. */
      request(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, request: WriteOptions & { body?: unknown; query?: URLSearchParams } = {}) {
        return transport.request(method, path, { ...request, write: method === "GET" ? false : "unkeyed" });
      },
    };
  }

  async health(request: RequestOptions = {}): Promise<Health> {
    return this.protocol.health(request);
  }

  capabilities(request: RequestOptions = {}) { return this.protocol.capabilities(request); }

  /**
   * What this app may do. Kept current by default (keepAccess): later calls
   * answer from the last report until Tsunagi says access may have changed.
   * A request is never held back by it; each can still be refused.
   */
  access(options: RequestOptions & { fresh?: boolean } = {}): Promise<AccessSnapshot> {
    return this.accessCache.get(options);
  }

  /** Called with the new report whenever access may have changed (a role or key change, add-on actions, FSRS). */
  onAccessChange(listener: (access: AccessSnapshot) => void, options: { signal?: AbortSignal } = {}): Promise<Subscription> {
    return this.accessCache.onChange(listener, options.signal);
  }

  /** Ends the event connection and every listener. The client can't listen again afterwards. */
  close(): void {
    this.accessCache.close();
    this.connection.close();
  }
}

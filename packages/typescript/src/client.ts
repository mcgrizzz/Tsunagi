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
  AddedNote, ClientOptions, Health, IfDuplicate, ItemReport, JobStartOptions, MediaInput, NoteCheck, NoteInput, NotePatch, NoteUpsert, OpenAddInput,
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
  /**
   * A note that duplicates a saved one: "error" (default) refuses it, naming the
   * saved notes; "allow" adds it anyway; "skip" adds nothing and answers the
   * saved note's id (`action: "skipped"`), so it is also find-or-create.
   */
  ifDuplicate?: IfDuplicate;
}
type Skip = { ifDuplicate: "skip" };
type NoSkip = { ifDuplicate?: "error" | "allow" };

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
    const events = resources[this.resource].path.split("/").at(-1)!.replaceAll("-", "_");
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

  /** Shows the deck's overview screen in Anki. A deck that doesn't exist is a 404. */
  readonly openOverview = sends(async (deck: Reference, options: WriteOptions = {}): Promise<void> =>
    this.protocol.openDeck("guiDeckOverview", deck, options), this.protocol, "guiDeckOverview");
  /** Starts reviewing the deck in Anki. A deck that doesn't exist is a 404. */
  readonly openReview = sends(async (deck: Reference, options: WriteOptions = {}): Promise<void> =>
    this.protocol.openDeck("guiDeckReview", deck, options), this.protocol, "guiDeckReview");

  constructor(protocol: DraftProtocol) { super(protocol, "decks"); }
}

class Notes extends Resource<"notes"> {
  /** Adds the note. What happens when it duplicates a saved note is `ifDuplicate`. */
  readonly create = sends(this.createImpl.bind(this) as {
    (input: NoteInput, options?: CreateOptions & NoSkip): Promise<CreatedNote>;
    (input: NoteInput, options: CreateOptions & Skip): Promise<AddedNote>;
  }, this.protocol, "notesCreate");
  private async createImpl(input: NoteInput, options: CreateOptions = {}): Promise<CreatedNote | AddedNote> {
    return single(await this.add([input], options));
  }

  readonly createMany = sends(this.createManyImpl.bind(this) as {
    (input: readonly NoteInput[], options: CreateOptions & NoSkip & Collect): Promise<ItemReport<CreatedNote, NoteFailure>>;
    (input: readonly NoteInput[], options?: CreateOptions & NoSkip & OnError): Promise<CreatedNote[]>;
    (input: readonly NoteInput[], options: CreateOptions & Skip & Collect): Promise<ItemReport<AddedNote, NoteFailure>>;
    (input: readonly NoteInput[], options: CreateOptions & Skip & OnError): Promise<AddedNote[]>;
  }, this.protocol, "notesCreate");
  private async createManyImpl(input: readonly NoteInput[], options: CreateOptions & { onError?: "throw" | "collect" } = {}) {
    options.signal?.throwIfAborted();
    return settle(list(input).length ? await this.add(input, options) : { items: [] }, options);
  }

  /** One request: the duplicate ids come with it unless duplicates are allowed, and a skipped duplicate writes nothing. */
  private async add(input: readonly NoteInput[], options: CreateOptions): Promise<ItemReport<CreatedNote | AddedNote, NoteFailure>> {
    const mode = options.ifDuplicate ?? "error";
    if (!["error", "allow", "skip"].includes(mode)) throw new TypeError("ifDuplicate is error, allow or skip");
    const report = await this.protocol.createNotes(input,
      included({ cards: options.cards, duplicate_ids: mode !== "allow" }), options, mode === "allow");
    if (mode !== "skip") return report;
    return {
      items: report.items.map(item => {
        if (item.ok) return { ok: true, index: item.index, value: { action: "created" as const, ...item.value } };
        const saved = item.error.code === "duplicate" ? item.error.duplicateNoteIds ?? [] : [];
        if (!saved.length) return item;
        return { ok: true, index: item.index, value: { action: "skipped" as const, index: item.index, id: saved[0]!, duplicateIds: [...saved] } };
      }),
    };
  }

  /** Resolves when the PATCH completes: fields, tags and files in one undo step. Does not read the note again. */
  readonly update = sends(async (id: number, patch: NotePatch, options: WriteOptions = {}): Promise<void> =>
    this.protocol.updateNote(id, patch, options), this.protocol, "notesUpdate");

  /**
   * Is the note already saved? By the rules create uses to refuse a duplicate:
   * its first field, among notes of its note type (or the scope `duplicates`
   * gives). A read: nothing changes. A note naming a deck, note type or field
   * that doesn't exist raises ItemRejectedError, as create would.
   */
  readonly exists = sends(async (note: NoteInput, options: RequestOptions = {}): Promise<boolean> =>
    (await this.existing([note], options))[0]!, this.protocol, "notesCheck");

  /** exists for each note, in order. */
  readonly existsMany = sends(async (notes: readonly NoteInput[], options: RequestOptions = {}): Promise<boolean[]> =>
    list(notes).length ? this.existing(notes, options) : [], this.protocol, "notesCheck");

  private async existing(notes: readonly NoteInput[], options: RequestOptions): Promise<boolean[]> {
    options.signal?.throwIfAborted();
    return (await this.protocol.checkNotes(notes, [], options)).map(check => {
      if (check.state === "invalid") throw new ItemRejectedError({ index: check.index, code: "invalid", message: check.reason ?? "invalid" });
      return check.state === "duplicate";
    });
  }

  /** Could this note be added, and if not, why? A read: nothing changes. */
  readonly check = sends(async (note: NoteInput, options: RequestOptions & { duplicateIds?: boolean } = {}): Promise<NoteCheck> =>
    (await this.protocol.checkNotes([note], included({ duplicate_ids: options.duplicateIds }), options))[0]!,
  this.protocol, "notesCheck");

  /** check for each note, in order. */
  readonly checkMany = sends(async (notes: readonly NoteInput[], options: RequestOptions & { duplicateIds?: boolean } = {}): Promise<NoteCheck[]> =>
    list(notes).length ? this.protocol.checkNotes(notes, included({ duplicate_ids: options.duplicateIds }), options) : [],
  this.protocol, "notesCheck");

  /** Opens the note in Anki's Browser, to edit it. A note that doesn't exist is a 404. */
  readonly openEditor = sends(async (id: number, options: WriteOptions = {}): Promise<void> =>
    this.protocol.openEditor(id, options), this.protocol, "guiEditNote");

  /**
   * Opens Add Cards filled with the note, for the user to finish and add: its
   * deck, note type, fields, tags and files (stored now, referenced in their
   * fields). Nothing is added until the user confirms.
   */
  readonly openAdd = sends(async (note: OpenAddInput, options: WriteOptions = {}): Promise<void> =>
    this.protocol.openAdd(note, options), this.protocol, "guiAddCards");

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
      answers: list(answers).map(answer => ({ card_id: inputId(answer.cardId), rating: ratingCode(answer.rating) })),
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

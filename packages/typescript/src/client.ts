import { ItemRejectedError, JobFailedError, JobWaitTimeoutError, PartialWriteError, RequestTimeoutError } from "./errors.js";
import { cards, decodeSync, DraftProtocol, notes, object } from "./protocol.js";
import { Query } from "./query.js";
import { deadline, pause, positive, Transport } from "./transport.js";
import type { ClientOptions, CreatedNote, CreationReport, Note, NoteInput, NotePatch, NoteSummary, RequestOptions, SyncResult, WaitOptions, WriteOptions } from "./types.js";

class Notes extends Query<Note, NoteSummary, "id" | "note_modified" | "sort_field"> {
  readonly create = registerAccess(this.createImpl.bind(this), this.protocol, accessOperations["notes.create"]);
  readonly createMany = registerAccess(this.createManyImpl.bind(this), this.protocol, accessOperations["notes.createMany"]);
  readonly update = registerAccess(this.updateImpl.bind(this), this.protocol, accessOperations["notes.update"]);

  constructor(protocol: DraftProtocol) {
    const selected = ["id", "model_name", "first_field", "tags"] as const;
    super(protocol, notes, selected, { select: selected.join(","), where: [], shape: "object" });
  }
  private async createImpl(input: NoteInput, options: WriteOptions = {}): Promise<CreatedNote> {
    const report = await this.protocol.create([input], options);
    const item = report.items[0]!;
    if (!item.ok) throw new ItemRejectedError(item.error);
    return item.value;
  }
  private createManyImpl(input: readonly NoteInput[], options: WriteOptions & { onError: "collect" }): Promise<CreationReport>;
  private createManyImpl(input: readonly NoteInput[], options?: WriteOptions & { onError?: "throw" }): Promise<CreatedNote[]>;
  private async createManyImpl(input: readonly NoteInput[], options: WriteOptions & { onError?: "collect" | "throw" } = {}): Promise<CreatedNote[] | CreationReport> {
    options.signal?.throwIfAborted();
    if (options.onError !== undefined && !["throw", "collect"].includes(options.onError)) throw new TypeError("Invalid onError policy");
    const report = input.length ? await this.protocol.create(input, options) : { items: [] };
    if (options.onError === "collect") return report;
    if (report.items.some(item => !item.ok)) throw new PartialWriteError(report);
    return report.items.map(item => {
      if (!item.ok) throw new ItemRejectedError(item.error);
      return item.value;
    });
  }
  /** Resolves when the PATCH completes. Does not fetch the note again. */
  private updateImpl(id: number, patch: NotePatch, options: WriteOptions = {}): Promise<void> {
    return this.protocol.update(id, patch, options);
  }
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
  readonly cards;
  readonly notes;
  readonly collection;
  readonly raw;
  private readonly transport: Transport;
  private readonly protocol: DraftProtocol;

  constructor(options: ClientOptions) {
    const transport = this.transport = new Transport(options);
    const protocol = this.protocol = new DraftProtocol(transport);
    const selected = ["id", "note_id", "deck_id", "interval", "due"] as const;
    this.cards = new Query<import("./types.js").Card, import("./types.js").CardSummary, "due" | "interval" | "reps" | "lapses">(
      protocol, cards, selected, { select: selected.join(","), where: [], shape: "object" },
    );
    this.notes = new Notes(protocol);
    const startSync = async (request: JobStartOptions = {}) => new SyncOperation(protocol, await protocol.startSync(request));
    this.collection = {
      startSync: registerAccess(startSync, protocol, accessOperations["collection.startSync"]),
      sync: registerAccess(async (request: SyncOptions = {}): Promise<SyncResult> => {
        // Validate waiting options before starting a remote mutation.
        if (request.waitTimeoutMs !== undefined) positive(request.waitTimeoutMs, "waitTimeoutMs");
        if (request.pollIntervalMs !== undefined) positive(request.pollIntervalMs, "pollIntervalMs");
        const operation = await startSync(request);
        return operation.wait({ signal: request.signal, timeoutMs: request.waitTimeoutMs, pollIntervalMs: request.pollIntervalMs });
      }, protocol, accessOperations["collection.sync"]),
    };
    this.raw = {
      /** Unknown JSON until the caller validates it. No generic cast to a result type. */
      request(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, request: WriteOptions & { body?: unknown; query?: URLSearchParams } = {}) {
        return transport.request(method, path, { ...request, write: method === "GET" ? false : "unkeyed" });
      },
    };
  }

  async health(request: RequestOptions = {}) {
    return object((await this.transport.request("GET", "/v1/health", request)).data);
  }

  capabilities(request: RequestOptions = {}) { return this.protocol.capabilities(request); }

  /**
   * The current access, kept current: fetches the capabilities report again
   * whenever Tsunagi says access may have changed (access.changed). Opens its
   * own event stream; needs no permission. Latest state wins for a slow loop.
   */
  watchAccess(options: WatchAccessOptions = {}): AsyncGenerator<AccessState> {
    return watchAccess(this.transport, this.protocol, options);
  }

  /** Explicit discovery; ordinary operations never perform an automatic preflight. */
  async access(request: RequestOptions = {}): Promise<AccessSnapshot> {
    return new AccessSnapshot(await this.capabilities(request), this.protocol);
  }
}
import type { JobStartOptions } from "./types.js";
import { AccessSnapshot } from "./access.js";
import { registerAccess } from "./access-target.js";
import { accessOperations } from "./protocol.js";
import { watchAccess } from "./watch-access.js";
import type { AccessState, WatchAccessOptions } from "./watch-access.js";

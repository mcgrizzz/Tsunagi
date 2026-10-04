import { AccessSnapshot } from "./access.js";
import type { EventConnection, Listener, Signal } from "./events.js";
import type { DraftProtocol } from "./protocol.js";
import { Subscription } from "./subscription.js";
import type { RequestOptions } from "./types.js";

/**
 * access() kept current by the event connection (packages/spec/behavior.md,
 * Access): the last snapshot is returned without a request while nothing has
 * made it stale.
 */
export class AccessCache {
  private snapshot: AccessSnapshot | null = null;
  private current = false;
  private generation = 0;        // counts invalidations
  private fetching: Promise<AccessSnapshot> | null = null;
  private leave: (() => void) | null = null;
  private connected: Promise<void> | null = null;  // the first ready (or drop) after joining
  private reconnected = false;   // a ready after a drop is a change; the first one isn't
  private firstFailure: { error: unknown } | null = null;  // the first try failed, before any ready
  private key: { value: string | undefined } | null = null;
  private readonly watchers = new Set<{ listener: (access: AccessSnapshot) => void; subscription: Subscription }>();

  constructor(
    private readonly protocol: DraftProtocol,
    private readonly connection: EventConnection,
    private readonly keep: boolean,
    private readonly readKey: () => Promise<string | undefined>,
  ) {}

  async get(options: RequestOptions & { fresh?: boolean } = {}): Promise<AccessSnapshot> {
    options.signal?.throwIfAborted();
    if (!this.keep) return this.fetch(options);
    const key = await this.readKey();
    if (this.key && this.key.value !== key) {
      this.invalidate();
      this.connection.reconnect();
    }
    this.key = { value: key };
    await this.join();
    if (!options.fresh && this.current && this.snapshot) return this.snapshot;
    return this.load(options);
  }

  async onChange(listener: (access: AccessSnapshot) => void, signal?: AbortSignal): Promise<Subscription> {
    const subscription = new Subscription(signal);
    const watcher = { listener, subscription };
    this.watchers.add(watcher);
    subscription.onEnd(() => { this.watchers.delete(watcher); this.release(); });
    await this.join();
    if (this.firstFailure) subscription.end(this.firstFailure.error);  // never connected: don't wait forever
    if (!subscription.active) await subscription.done;  // rejects with the error that ended it
    return subscription;
  }

  /** A 401 or 403 answer to any request. */
  invalidate(): void {
    this.generation++;
    this.current = false;
    this.fetching = null;
  }

  /** The client closed: every watcher ends without an error. */
  close(): void {
    for (const { subscription } of [...this.watchers]) subscription.end();
    this.leave?.();
    this.leave = null;
  }

  private join(): Promise<void> {
    if (this.leave) return this.connected!;
    let arrived!: () => void;
    this.connected = new Promise(resolve => { arrived = resolve; });
    this.reconnected = false;
    const listener: Listener = {
      need: {},
      hear: signal => {
        if (signal.kind === "ready") this.firstFailure = null;
        else if (signal.kind === "down" && !this.reconnected && !signal.deliberate) this.firstFailure = { error: signal.error };
        this.hear(signal);
        if (signal.kind === "ready" || signal.kind === "down") arrived();
      },
      end: error => {
        this.leave = null;
        this.invalidate();
        arrived();
        for (const { subscription } of [...this.watchers]) subscription.end(error);
      },
    };
    this.leave = this.connection.join(listener);
    return this.connected;
  }

  /** Leave the connection when nothing here uses it: access() keeps it while caching. */
  private release(): void {
    if (!this.keep && !this.watchers.size) { this.leave?.(); this.leave = null; }
  }

  private hear(signal: Signal): void {
    if (signal.kind === "message") return;
    this.invalidate();
    if (signal.kind === "down") { this.reconnected = true; return; }
    if (signal.kind === "ready" && !this.reconnected) return;
    if (this.watchers.size) {
      this.load({}).then(access => {
        for (const { listener, subscription } of [...this.watchers]) if (subscription.active) listener(access);
      }, () => { /* the next access() fetches */ });
    }
  }

  private load(options: RequestOptions): Promise<AccessSnapshot> {
    if (this.fetching) return this.fetching;
    const generation = this.generation;
    const up = this.connection.up;
    const fetching = this.fetching = this.fetch(options).then(snapshot => {
      if (generation === this.generation) {
        this.snapshot = snapshot;
        this.current = up;
      }
      return snapshot;
    }).finally(() => { if (this.fetching === fetching) this.fetching = null; });
    return fetching;
  }

  private async fetch(options: RequestOptions): Promise<AccessSnapshot> {
    return new AccessSnapshot(await this.protocol.capabilities(options), this.protocol);
  }
}

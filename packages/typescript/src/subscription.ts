/** A running listener: stop it, or wait for it to end (packages/spec/behavior.md, Subscriptions). */
export class Subscription {
  /** Resolves on stop() or the client's close(); rejects with the error that ended it otherwise. */
  readonly done: Promise<void>;
  private settle!: (error?: unknown) => void;
  private ended = false;
  private cleanup: (() => void) | null = null;

  constructor(signal?: AbortSignal) {
    this.done = new Promise<void>((resolve, reject) => {
      this.settle = error => error === undefined ? resolve() : reject(error);
    });
    // Nobody may wait on `done`; an ending error must not become an unhandled rejection.
    this.done.catch(() => {});
    if (signal?.aborted) this.end();
    signal?.addEventListener("abort", () => this.end(), { once: true });
  }

  get active(): boolean { return !this.ended; }

  /** @internal What to undo when it ends. */
  onEnd(cleanup: () => void): void {
    if (this.ended) cleanup();
    else this.cleanup = cleanup;
  }

  stop(): void { this.end(); }

  /** @internal */
  end(error?: unknown): void {
    if (this.ended) return;
    this.ended = true;
    this.cleanup?.();
    this.settle(error);
  }
}

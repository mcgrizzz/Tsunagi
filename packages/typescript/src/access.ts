import type { Capabilities, CapabilityState } from "./types.js";

export type AccessBatch<T extends Readonly<Record<string, AccessTarget>>> = Readonly<{
  /** True only when every requested check is available. */
  allowed: boolean;
  checks: { readonly [K in keyof T]: AccessDecision };
}>;
export type AccessDecision = Readonly<{
  operation: string;
  option: string | null;
  setting: string | null;
  /** Only supplied when the server identifies a permissions.* setting. */
  permission: string | null;
} & (
  | { allowed: true; status: "available"; reason: string | null }
  | { allowed: false; status: "disabled" | "unsupported" | "unknown"; reason: string }
)>;

/** A point-in-time report, not a guarantee or an automatically refreshed cache. */
export class AccessSnapshot {
  readonly #owner: object | undefined;
  constructor(readonly capabilities: Capabilities, owner?: object) {
    this.#owner = owner;
    Object.freeze(this);
  }

  get caller(): Capabilities["caller"] { return this.capabilities.caller; }

  /** Pass a query or a method, uncalled: `access.check(anki.notes.create)`. */
  check(target: AccessTarget): AccessDecision {
    const description = describeAccess(target);
    if (description.owner !== this.#owner) throw new TypeError("Access snapshot and target must belong to the same Tsunagi client");
    return this.operation(description.operation);
  }

  can(target: AccessTarget): boolean {
    return this.check(target).allowed;
  }

  /** All checks are local and use this same snapshot; no operation is executed. */
  checkMany<const T extends Readonly<Record<string, AccessTarget>>>(targets: T): AccessBatch<T> {
    const entries = Object.entries(targets).map(([name, target]) => [name, this.check(target)] as const);
    const checks = Object.freeze(Object.fromEntries(entries)) as AccessBatch<T>["checks"];
    return Object.freeze({ allowed: entries.every(([, check]) => check.allowed), checks });
  }

  /** Use the server's METHOD /path template, e.g. PATCH /v1/notes/{id}. */
  operation(operation: string, option?: string): AccessDecision {
    const reported = Object.hasOwn(this.capabilities.operations, operation)
      ? this.capabilities.operations[operation] : undefined;
    // A restricted parent operation cannot be enabled by one available option.
    let state: CapabilityState | undefined = reported;
    if (reported?.status === "available" && option !== undefined) {
      state = Object.hasOwn(reported.options, option) ? reported.options[option] : undefined;
    }
    const setting = state?.setting ?? null;
    const permission = setting?.startsWith("permissions.") ? setting.slice("permissions.".length) : null;
    const common = { operation, option: option ?? null, setting, permission };
    if (state?.status === "available") {
      return Object.freeze({ ...common, allowed: true, status: "available", reason: state.reason });
    }
    return Object.freeze({
      ...common, allowed: false, status: state?.status ?? "unknown",
      reason: state?.reason ?? (state === undefined
        ? "The server did not report availability for this operation or option."
        : `This operation or option is ${state.status}.`),
    });
  }
}
import { describeAccess } from "./access-target.js";
import type { AccessTarget } from "./access-target.js";

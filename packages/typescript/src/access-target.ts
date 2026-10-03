// Internal identity metadata, kept off public objects and request payloads.
export const accessTarget: unique symbol = Symbol("Tsunagi access target");
export interface AccessTarget { readonly [accessTarget]: true }
interface TargetDescription { readonly owner: object; readonly operation: string }
const targets = new WeakMap<object, TargetDescription>();

export function registerAccess<T extends object>(target: T, owner: object, operation: string): T & AccessTarget {
  targets.set(target, Object.freeze({ owner, operation }));
  return target as T & AccessTarget;
}

export function describeAccess(target: AccessTarget): TargetDescription {
  const description = targets.get(target);
  if (!description) throw new TypeError("Expected a Tsunagi query or supported method reference");
  return description;
}

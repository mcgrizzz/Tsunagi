/** narrow()'s step: which elements of a list to keep, and which parts of them (packages/spec/behavior.md, Narrowing a list). */
import type { Fields } from "./decode.js";

type Key<T> = Extract<keyof T, string>;
/** The element keys narrow() can keep elements by: text or whole numbers. */
export type ElementKey<E> = { [K in Key<E>]: E[K] extends string | number ? K : never }[Key<E>];

/** Why a step can't be given again, as the compiler shows it. */
export type GivenOnce = typeof givenOnce[keyof typeof givenOnce];
const givenOnce = {
  where: "narrow() takes one where(): the server keeps elements by one key",
  select: "narrow() takes one select(): list every part in it",
} as const;

/** What a step sends: the element key's wire name and its values; the parts in client names. */
export interface ElementState {
  readonly where?: { readonly key: string; readonly values: readonly (string | number)[] };
  readonly parts?: readonly string[];
}

declare const elementRow: unique symbol;
declare const canWhere: unique symbol;
declare const canSelect: unique symbol;

/**
 * E is the element with every part it can have (a note field's text too),
 * P the element as the rows will have it. CanWhere and CanSelect are true, or
 * why that step was already given.
 */
export class ElementQuery<E, P, CanWhere extends true | GivenOnce = true, CanSelect extends true | GivenOnce = true> {
  declare readonly [elementRow]: P;
  declare readonly [canWhere]: CanWhere;
  declare readonly [canSelect]: CanSelect;
  constructor(private readonly fields: Fields, readonly state: ElementState = {}) {}

  /** Keep the elements whose key is the value (eq) or one of the values (in); in [] keeps none. */
  where<K extends ElementKey<E>, O extends "eq" | "in">(
    this: ElementQuery<E, P, true, CanSelect>, key: K, operator: O, value: O extends "in" ? readonly E[K][] : E[K],
  ): ElementQuery<E, P, typeof givenOnce.where, CanSelect> {
    if (this.state.where) throw new TypeError(givenOnce.where);
    if (!Object.hasOwn(this.fields, key)) throw new TypeError(`Unknown element key: ${String(key)}`);
    const field = this.fields[key]!;
    if ((field.kind !== "string" && field.kind !== "number") || field.values) throw new TypeError(`${key} can't choose elements`);
    if (operator !== "eq" && operator !== "in") throw new TypeError("narrow() keeps elements with eq or in");
    if ((operator === "in") !== Array.isArray(value)) throw new TypeError(operator === "in" ? "in takes a list" : "Expected a single value");
    const values = (operator === "in" ? value as readonly unknown[] : [value]).map(item => {
      if (typeof item !== field.kind || (typeof item === "number" && !Number.isSafeInteger(item))) {
        throw new TypeError(`${key} takes ${field.kind === "number" ? "whole numbers" : "text"}`);
      }
      return item as string | number;
    });
    return new ElementQuery(this.fields, { ...this.state, where: { key: field.wire, values } });
  }

  /** Only these parts of each kept element; without it, elements are whole. */
  select<const K extends readonly [Key<E>, ...Key<E>[]]>(
    this: ElementQuery<E, P, CanWhere, true>, ...parts: K
  ): ElementQuery<E, Pick<E, K[number]>, CanWhere, typeof givenOnce.select> {
    if (this.state.parts) throw new TypeError(givenOnce.select);
    if (!parts.length) throw new TypeError("Select at least one part");
    for (const part of parts) if (!Object.hasOwn(this.fields, part)) throw new TypeError(`Unknown part: ${String(part)}`);
    return new ElementQuery(this.fields, { ...this.state, parts: [...new Set(parts)] });
  }
}

/** The select term for a narrowed list: `fields[name in ["Word"]].(name,text)`. */
export function elementTerm(wire: string, fields: Fields, state: ElementState): string {
  const filter = state.where ? `[${state.where.key} in [${state.where.values.map(value => JSON.stringify(value)).join(",")}]]` : "[]";
  return `${wire}${filter}${state.parts ? `.(${state.parts.map(part => fields[part]!.wire).join(",")})` : ""}`;
}

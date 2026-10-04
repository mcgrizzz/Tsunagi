/** Wire values to client values, driven by the generated field tables (packages/spec/behavior.md, Names and values). */
import { ProtocolError } from "./errors.js";
import { objectFields } from "./generated.js";

export interface FieldType {
  readonly kind: "number" | "string" | "boolean" | "array" | "map" | "object" | "unknown";
  readonly item?: FieldType;
  readonly schema?: keyof typeof objectFields;
}
export interface FieldDescription extends FieldType {
  readonly wire: string;
  /** Wire value (a code, or a string) to the client's name. */
  readonly values?: Readonly<Record<string, string | null>>;
  readonly nullable?: boolean;
  /** In an answer, a field the server may leave out. */
  readonly optional?: boolean;
  /** Other resources it is built from (x-from). */
  readonly from?: readonly string[];
}
export type Fields = Readonly<Record<string, FieldDescription>>;

export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ProtocolError("Expected a JSON object");
  return value as Record<string, unknown>;
}

function decodeType(type: FieldType, value: unknown): unknown {
  switch (type.kind) {
    case "number":
      if (typeof value === "number" && Number.isFinite(value)) return value;
      break;
    case "string": case "boolean":
      if (typeof value === type.kind) return value;
      break;
    case "array":
      if (Array.isArray(value)) return value.map(item => decodeType(type.item!, item));
      break;
    case "map":
      return Object.fromEntries(Object.entries(object(value)).map(([key, item]) => [key, decodeType(type.item!, item)]));
    case "object":
      return decodeObject(objectFields[type.schema!], value);
    case "unknown":
      return value;
  }
  throw new ProtocolError(`Expected a ${type.kind}`);
}

export function decodeField(field: FieldDescription, value: unknown): unknown {
  if (value === undefined) {
    if (field.optional && field.nullable) return null;
    throw new ProtocolError(`Missing ${field.wire}`);
  }
  if (value === null && field.nullable) return null;
  if (!field.values) return decodeType(field, value);
  if (typeof value !== field.kind || !Object.hasOwn(field.values, String(value))) throw new ProtocolError(`Unknown ${field.wire} value`);
  return field.values[String(value)];
}

/** An object in client names; `names` limits it to those fields (a query's selection). */
export function decodeObject(fields: Fields, value: unknown, names: readonly string[] | null = null): Record<string, unknown> {
  const row = object(value);
  const result: Record<string, unknown> = {};
  for (const name of names ?? Object.keys(fields)) result[name] = decodeField(fields[name]!, row[fields[name]!.wire]);
  return result;
}

/** A generated answer type, decoded and checked. */
export function decodeAs<T>(type: keyof typeof objectFields, value: unknown): T {
  return decodeObject(objectFields[type], value) as T;
}

/** The wire value for a client value name (a code, or a string). */
export function wireValue(field: FieldDescription, name: unknown): string | number {
  const found = Object.keys(field.values ?? {}).find(key => field.values![key] === name);
  if (found === undefined) throw new TypeError(`Unknown value: ${String(name)}`);
  return field.kind === "number" ? Number(found) : found;
}

export function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const item of Object.values(value)) deepFreeze(item);
  }
  return value;
}

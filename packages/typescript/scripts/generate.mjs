// Writes src/generated.ts from Tsunagi's API description (tests/snapshots/openapi.json)
// and packages/spec/names.json, on every build (npm run build): it is not in git.
//
// Generated: each resource's row type and field table; the client's operations,
// their request bodies (wire names, so an encoder can't send a key the server
// doesn't take) and their answers (client names, with field tables to decode them).
import { readFileSync, writeFileSync } from "node:fs";

const here = path => new URL(path, import.meta.url);
const api = JSON.parse(readFileSync(here("../../../tests/snapshots/openapi.json"), "utf8"));
const names = JSON.parse(readFileSync(here("../../spec/names.json"), "utf8"));
const schemas = api.components.schemas;
const target = here("../src/generated.ts");

/** An entry that may be a reference into components (a shared parameter). */
const resolve = node => node?.$ref ? node.$ref.split("/").slice(1).reduce((at, key) => at[key], api) : node;
const parametersOf = operation => (operation.parameters ?? []).map(resolve);
const camel = name => name.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase());
const ref = node => node?.$ref?.split("/").pop();
const omitted = (schema, wire) => [...names.omit["*"], ...(names.omit[schema] ?? [])].includes(wire);
/** A schema's short name: FastAPI prefixes a module path when two share a name. */
const short = schema => schema.split("__").pop().replace(/_+$/, "");
const typeName = schema => names.typeNames[schema] ?? short(schema).replace(/_/g, "");
const unique = (what, list) => {
  const seen = new Set();
  for (const name of list) {
    if (seen.has(name)) throw new Error(`Two ${what} are named ${name}: fix names.json`);
    seen.add(name);
  }
};

// A wire value's name ("day_learning") as the client's ("dayLearning"); null stays null.
const valueName = text => text === null ? null : camel(text.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_"));

// ----- Client-named objects: rows, the objects inside them, answers -----

const objects = new Set();  // schemas of objects to generate, besides rows
const inner = node => node.anyOf?.find(item => item.type !== "null") ?? node.allOf?.[0] ?? node;
function typeOf(node) {
  const shape = inner(node);
  const schema = ref(shape);
  if (schema) { objects.add(schema); return { ts: typeName(schema), kind: "object", schema }; }
  if (shape.type === "object" && shape.additionalProperties && typeof shape.additionalProperties === "object") {
    const item = typeOf(shape.additionalProperties);
    return { ts: `Record<string, ${item.ts}>`, kind: "map", item };
  }
  switch (shape.type) {
    case "integer": case "number": return { ts: "number", kind: "number" };
    case "string": return { ts: "string", kind: "string" };
    case "boolean": return { ts: "boolean", kind: "boolean" };
    case "array": {
      const item = typeOf(shape.items ?? {});
      return { ts: item.ts.includes(" ") ? `(${item.ts})[]` : `${item.ts}[]`, kind: "array", item };
    }
    default: return { ts: "unknown", kind: "unknown" };
  }
}

/** `answer`: fields the schema doesn't require may be absent, read as null when nullable. */
function fieldsOf(schema, answer = false) {
  const out = [];
  const required = schemas[schema].required ?? [];
  for (const [wire, node] of Object.entries(schemas[schema].properties ?? {})) {
    if (omitted(schema, wire)) continue;
    const type = typeOf(node);
    const nullable = Boolean(node["x-nullable"]);
    const override = names.valueOverrides[`${schema}.${wire}`] ?? {};
    const listed = inner(node).enum;
    const coded = node["x-values"] ?? (listed && Object.fromEntries(listed.map(value => [value, value])));
    const values = coded && Object.fromEntries(Object.entries(coded)
      .map(([code, text]) => [code, Object.hasOwn(override, code) ? override[code] : valueName(text)]));
    const options = values ? [...new Set(Object.values(values))] : [];
    if (nullable && values) options.push(null);
    const ts = values ? [...new Set(options)].map(v => v === null ? "null" : JSON.stringify(v)).join(" | ")
      : type.ts + (nullable ? " | null" : "");
    const optional = answer && !required.includes(wire);
    const from = node["x-from"];
    out.push({ wire, name: camel(wire), ts, type, values, nullable, optional, from, description: node.description });
  }
  unique(`fields of ${schema}`, out.map(f => f.name));
  return out;
}

const comment = (text, indent = "  ") => text ? `${indent}/** ${text.replace(/\*\//g, "*\\/").replace(/\n/g, " ")} */\n` : "";
/** Answers are read-only (the client freezes them); rows are the app's to change. */
function interfaceFor(name, fields, readonly = false) {
  const lines = fields.map(f => `${comment(f.description)}  ${readonly ? "readonly " : ""}${f.name}: ${f.ts};`);
  return `export interface ${name} {\n${lines.join("\n")}\n}`;
}

function describe(type) {
  const parts = [`kind: ${JSON.stringify(type.kind)}`];
  if (type.kind === "object") parts.push(`schema: ${JSON.stringify(typeName(type.schema))}`);
  if (type.kind === "array" || type.kind === "map") parts.push(`item: { ${describe(type.item)} }`);
  return parts.join(", ");
}

function fieldTable(fields) {
  const entries = fields.map(f => {
    const parts = [`wire: ${JSON.stringify(f.wire)}`, describe(f.type)];
    if (f.values) parts.push(`values: ${JSON.stringify(f.values)}`);
    if (f.nullable) parts.push("nullable: true");
    if (f.optional) parts.push("optional: true");
    if (f.from) parts.push(`from: ${JSON.stringify(f.from)}`);
    return `    ${f.name}: { ${parts.join(", ")} },`;
  });
  return `{\n${entries.join("\n")}\n  }`;
}

// ----- Request bodies, in wire names -----

const bodies = new Set();
const bodyName = schema => `${short(schema).replace(/_/g, "")}Body`;
function bodyType(node) {
  if (node.anyOf) return [...new Set(node.anyOf.filter(item => item.type !== "null").map(bodyType))].join(" | ");
  if (node.allOf) return bodyType(node.allOf[0]);
  const schema = ref(node);
  if (schema) { bodies.add(schema); return bodyName(schema); }
  if (node.enum) return node.enum.map(value => JSON.stringify(value)).join(" | ");
  switch (node.type) {
    case "integer": case "number": return "number";
    case "string": return "string";
    case "boolean": return "boolean";
    case "array": { const item = bodyType(node.items ?? {}); return item.includes(" ") ? `(${item})[]` : `${item}[]`; }
    case "object":
      return node.additionalProperties && typeof node.additionalProperties === "object"
        ? `Record<string, ${bodyType(node.additionalProperties)}>` : "Record<string, unknown>";
    default: return "unknown";
  }
}
function bodyInterface(schema) {
  const required = schemas[schema].required ?? [];
  const lines = Object.entries(schemas[schema].properties ?? {}).map(([wire, node]) =>
    `${comment(node.description)}  ${wire}${required.includes(wire) ? "" : "?"}: ${bodyType(node)};`);
  return `export interface ${bodyName(schema)} {\n${lines.join("\n")}\n}`;
}

// ----- Output -----

const out = [
  "// Generated by scripts/generate.mjs from tests/snapshots/openapi.json and",
  "// packages/spec/names.json, on every build. Do not edit.",
  "",
];
const resources = [];
const rows = [];
for (const [path, name] of Object.entries(names.resources)) {
  const get = api.paths[path]?.get;
  if (!get) throw new Error(`${path} is not in the API description`);
  const page = ref(get.responses["200"].content["application/json"].schema);
  const row = ref(schemas[page].properties.items.items);
  const fields = fieldsOf(row);
  const type = names.types[name];
  const order = parametersOf(get).find(p => p.name === "order");
  const sorts = (order?.schema?.["x-sorts"] ?? []).filter(wire => !omitted(row, wire))
    .map(wire => [camel(wire), wire]);
  unique(`sorts of ${path}`, sorts.map(([client]) => client));
  const key = names.keys[name] ?? "id";
  if (!fields.some(f => f.name === key)) throw new Error(`${name} has no key field ${key}`);
  // A search's x-from: the resources whose changes can change what it matches. null: no search.
  const searchParameter = parametersOf(get).find(p => p.name === "search");
  const search = searchParameter ? JSON.stringify({ from: searchParameter.schema?.["x-from"] ?? [] }) : "null";
  out.push(interfaceFor(type, fields), "");
  rows.push(`  ${name}: ${type};`);
  resources.push(`  ${name}: {\n    path: ${JSON.stringify(path)},\n    key: ${JSON.stringify(key)},\n    search: ${search},\n    sorts: ${JSON.stringify(Object.fromEntries(sorts))},\n    fields: ${fieldTable(fields).replace(/\n/g, "\n  ")},\n  },`);
}
const rowObjects = new Set(objects);

// The event stream's messages (x-events on GET /v1/events): each type's schema,
// and the resource or events option that carries it.
const events = [];
for (const [type, entry] of Object.entries(api.paths["/v1/events"].get["x-events"] ?? {})) {
  const schema = entry.schema.split("/").pop();
  objects.add(schema);
  const parts = [`schema: ${JSON.stringify(typeName(schema))}`];
  if (entry.resource) parts.push(`resource: ${JSON.stringify(entry.resource)}`);
  if (entry.option) parts.push(`option: ${JSON.stringify(entry.option)}`);
  events.push(`  ${JSON.stringify(type)}: { ${parts.join(", ")} },`);
}
// Every error's body (the operations' default answer).
objects.add("ErrorBody");

const operations = [];
const requests = [];
const answers = [];
for (const [name, operation] of Object.entries(names.operations)) {
  const [method, path] = operation.split(" ");
  const spec = api.paths[path]?.[method.toLowerCase()];
  if (!spec) throw new Error(`${operation} is not in the API description`);
  const body = spec.requestBody?.content?.["application/json"]?.schema;
  requests.push(`  ${name}: ${body ? bodyType(body) : "never"};`);
  const statuses = Object.entries(spec.responses).filter(([status]) => status.startsWith("2"))
    .map(([status, response]) => [status, ref(response.content?.["application/json"]?.schema)]);
  for (const [, schema] of statuses) if (schema) objects.add(schema);
  answers.push(`  ${name}: { ${statuses.map(([status, schema]) => `${status}: ${schema ? typeName(schema) : "unknown"}`).join("; ")} };`);
  const byStatus = Object.fromEntries(statuses.map(([status, schema]) => [status, schema ? typeName(schema) : null]));
  operations.push(`  ${name}: { method: ${JSON.stringify(method)}, path: ${JSON.stringify(path)}, answers: ${JSON.stringify(byStatus)} },`);
}

// Objects can name further objects; generate until none is new.
const tables = [];
const done = new Set();
for (let pending = [...objects]; pending.length; pending = [...objects].filter(schema => !done.has(schema))) {
  for (const schema of pending.sort()) {
    done.add(schema);
    const answer = !rowObjects.has(schema);
    const fields = fieldsOf(schema, answer);
    out.push(interfaceFor(typeName(schema), fields, answer), "");
    tables.push(`  ${typeName(schema)}: ${fieldTable(fields)},`);
  }
}
unique("object types", [...done].map(typeName));

const bodyLines = [];
for (let pending = [...bodies], seen = new Set(); pending.length; pending = [...bodies].filter(schema => !seen.has(schema))) {
  for (const schema of pending.sort()) { seen.add(schema); bodyLines.push(bodyInterface(schema), ""); }
}
out.push("// Request bodies, as the server takes them.", "", ...bodyLines);

out.push(`/** Each resource's row type. */\nexport interface Rows {\n${rows.join("\n")}\n}`, "");
out.push(`/** Each operation's request body (wire names). */\nexport interface Requests {\n${requests.join("\n")}\n}`, "");
out.push(`/** Each operation's answers by status, in client names. */\nexport interface Answers {\n${answers.join("\n")}\n}`, "");
out.push(`export const objectFields = {\n${tables.join("\n")}\n} as const;`, "");
out.push(`export const operations = {\n${operations.join("\n")}\n} as const;`, "");
out.push(`export const events = {\n${events.join("\n")}\n} as const;`, "");
out.push(`export const resources = {\n${resources.join("\n")}\n} as const;`, "");
const states = Object.fromEntries(Object.entries(names.states).filter(([name]) => name !== "_"));
out.push(`/** Anki's search states as the client names them, and their search terms (is:<term>). */\nexport const states = ${JSON.stringify(states)} as const;`, "");

writeFileSync(target, out.join("\n"));

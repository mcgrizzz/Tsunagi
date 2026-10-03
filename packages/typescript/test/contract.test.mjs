import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { cards, notes } from "../dist/protocol.js";

// Tsunagi's committed API description: the rows each list returns.
const api = JSON.parse(readFileSync(new URL("../../../tests/snapshots/openapi.json", import.meta.url), "utf8"));
const rows = { [cards.path]: "CardRow", [notes.path]: "NoteRow" };

function wireType(field) {
  if (field.scalar === "number") return ["integer", "number"];
  if (field.scalar === "string") return ["string"];
  return ["array"];
}

test("every field the client reads exists in the server's row schema with a matching type", () => {
  for (const resource of [cards, notes]) {
    const schema = api.components.schemas[rows[resource.path]];
    for (const [name, field] of Object.entries(resource.fields)) {
      const property = schema.properties[name];
      assert.ok(property, `${rows[resource.path]} has no ${name}`);
      assert.ok(wireType(field).includes(property.type), `${rows[resource.path]}.${name} is ${property.type}`);
    }
  }
});

test("each resource's list documents the row schema the client checks against", () => {
  for (const resource of [cards, notes]) {
    const page = api.paths[resource.path].get.responses["200"].content["application/json"].schema.$ref.split("/").pop();
    assert.ok(api.components.schemas[page].properties.items.items.$ref.endsWith(`/${rows[resource.path]}`), page);
  }
});

test("every sort the client offers is one the server names", () => {
  for (const resource of [cards, notes]) {
    const order = api.paths[resource.path].get.parameters.find(p => p.name === "order").description;
    for (const sort of resource.sorts) assert.match(order, new RegExp(`\\b${sort}\\b`), `${resource.path} order ${sort}`);
  }
});

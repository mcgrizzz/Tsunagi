import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("every README example is an example file, so npm test compiles it", () => {
  const examples = readdirSync(new URL("../examples/", import.meta.url)).filter(name => name.endsWith(".ts"))
    .map(name => read(`../examples/${name}`));
  const blocks = [...read("../README.md").matchAll(/```ts\n([\s\S]*?)```/g)].map(match => match[1]);
  assert.ok(blocks.length);
  for (const block of blocks) assert.ok(examples.some(example => example.endsWith(block)), block.slice(0, 80));
});

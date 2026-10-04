import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

// Tsunagi's own docs show client code too; each ts block must compile like this README's.
// Only pages in git: docs/ also holds local notes.
const docs = execFileSync("git", ["ls-files", "README.md", "docs/*.md"],
  { cwd: new URL("../../../", import.meta.url), encoding: "utf8" })
  .split("\n").filter(Boolean).map(path => `../../../${path}`);

test("every README and docs example is an example file, so npm test compiles it", () => {
  const examples = readdirSync(new URL("../examples/", import.meta.url)).filter(name => name.endsWith(".ts"))
    .map(name => read(`../examples/${name}`));
  for (const page of ["../README.md", ...docs]) {
    const blocks = [...read(page).matchAll(/```ts\n([\s\S]*?)```/g)].map(match => match[1]);
    if (page === "../README.md") assert.ok(blocks.length);
    for (const block of blocks) assert.ok(examples.some(example => example.endsWith(block)), `${page}: ${block.slice(0, 80)}`);
  }
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRegistry, modelKey, templateVars } from "../server/registry.ts";

const { apps, problems } = loadRegistry();

test("every manifest passes the schema and its bindings resolve", () => {
  const errors = problems.filter((p) => p.severity === "error");
  assert.deepEqual(errors, []);
});

test("ready apps all have a workflow on disk", () => {
  for (const app of apps.filter((a) => a.status === "ready")) {
    assert.ok(app.graph, `${app.id} has no workflow loaded`);
  }
});

test("folder name and id agree, ids are unique", () => {
  const ids = apps.map((a) => a.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const a of apps) assert.ok(a.dir.endsWith(a.id), `${a.id} lives in ${a.dir}`);
});

test("apps that share models produce the same model key, so switching between them does not unload", () => {
  const z = apps.find((a) => a.id === "z-image")!;
  const cinema = apps.find((a) => a.id === "cinema-studio")!;
  const video = apps.find((a) => a.id === "video")!;
  assert.equal(modelKey(z), modelKey(cinema));
  assert.notEqual(modelKey(z), modelKey(video));
});

test("templateVars finds placeholders", () => {
  assert.deepEqual(templateVars("{prompt}, shot on a {camera}"), ["prompt", "camera"]);
});

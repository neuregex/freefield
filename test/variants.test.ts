import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRegistry, modelKey } from "../server/registry.ts";
import { applyInputs, applyVariant, explainSubmitError, type Settable } from "../server/runner.ts";
import { needOf } from "../server/models.ts";
import { hasLite, modelsFor, parseVariant, renames, versionGb, workflowRenames } from "../server/variants.ts";

const { apps, problems } = loadRegistry();
const byId = (id: string) => apps.find((a) => a.id === id)!;

function recorder(): Settable & { sets: Record<string, unknown> } {
  const sets: Record<string, unknown> = {};
  return { sets, setInput: (node: string, field: string, value: unknown) => (sets[`${node}.${field}`] = value) };
}

test("lite/variants.json attaches each copy to the model that loads its full file", () => {
  assert.equal(problems.filter((p) => p.severity === "error").length, 0);
  const krea = byId("styles").models.find((m) => m.file.endsWith("krea2_turbo_int8_convrot.safetensors"))!;
  assert.equal(krea.lite?.file, "diffusion_models/krea2_turbo_nvfp4.safetensors");
  assert.equal(krea.lite?.format, "nvfp4");
  assert.ok(hasLite(byId("styles")));
  assert.ok(!hasLite(byId("smoke")), "an app without models has no lite version");
});

test("the lite version loads the copies, in the same folder and phase, and the shared files as they are", () => {
  const app = byId("styles");
  const full = modelsFor(app, "full");
  const lite = modelsFor(app, "lite");
  assert.equal(full, app.models);
  assert.equal(lite.length, full.length);
  const i = full.findIndex((m) => m.lite);
  assert.equal(lite[i].file, full[i].lite!.file);
  assert.equal(lite[i].dir, full[i].dir);
  assert.equal(lite[i].phase, full[i].phase);
  assert.equal(lite[i].lite, undefined);
  for (const [k, m] of full.entries()) if (!m.lite) assert.equal(lite[k], m);
  assert.ok(versionGb(app, "lite") < versionGb(app, "full"));
  assert.notEqual(modelKey(app, "lite"), modelKey(app, "full"), "the gateway frees the GPU between the two versions");
});

test("the runner writes the copies' names into every loader that names a swapped file", () => {
  const app = byId("angles");   // Qwen-Image-Edit: its text encoder has an nvfp4 copy
  const names = renames(app, "lite");
  assert.equal(names.get("qwen_2.5_vl_7b_fp8_scaled.safetensors"), "qwen_2.5_vl_7b_nvfp4.safetensors");
  assert.equal(renames(app, "full").size, 0);
  const edits = workflowRenames(app.graph, names);
  assert.ok(edits.length >= 1);
  const wf = recorder();
  applyVariant(app, wf, "lite");
  for (const [node, field, value] of edits) assert.equal(wf.sets[`${node}.${field}`], value);
  const none = recorder();
  applyVariant(app, none, "full");
  assert.deepEqual(none.sets, {}, "the full version leaves the workflow as it is");
});

test("an option that names a swapped file gets the copy in the lite version", () => {
  const app = structuredClone(byId("angles"));
  const input = app.inputs.find((i) => i.type === "select" && i.options?.length)!;
  const node = Object.keys(app.graph!)[0];
  input.options![0].sets = [{ node, field: "clip_name", value: "qwen_2.5_vl_7b_fp8_scaled.safetensors" }];
  const wf = recorder();
  applyInputs(app, { [input.id]: input.options![0].value }, wf, () => null, undefined, renames(app, "lite"));
  assert.equal(wf.sets[`${node}.clip_name`], "qwen_2.5_vl_7b_nvfp4.safetensors");
});

test("a lite run asks for the lite pack, and a missing copy points there", () => {
  const app = byId("styles");
  const fullFiles = new Set(modelsFor(app, "full").map((m) => `${m.dir}/${m.file.split("/").pop()}`));
  assert.equal(needOf(app, fullFiles, null, "full"), null);
  const need = needOf(app, fullFiles, null, "lite");
  assert.equal(need?.kind, "pack");
  assert.equal(need && "pack" in need ? need.pack : null, "image-krea2-lite");
  const err = { code: "invalid_workflow", details: { node_errors: { "1": { class_type: "UNETLoader", errors: [
    { type: "value_not_in_list", extra_info: { received_value: "krea2_turbo_nvfp4.safetensors" } }] } } } };
  assert.match(explainSubmitError(app, err, "lite") ?? "", /image-krea2-lite/);
});

test("anything but lite is the full version", () => {
  assert.equal(parseVariant("lite"), "lite");
  for (const v of ["full", "", null, undefined, "LITE", 1]) assert.equal(parseVariant(v), "full");
});

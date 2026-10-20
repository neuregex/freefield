import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRegistry } from "../server/registry.ts";
import { applyInputs, explainSubmitError, InputError, renderTemplate, resolveValues, Runner, type Settable } from "../server/runner.ts";

const { apps } = loadRegistry();
const byId = (id: string) => apps.find((a) => a.id === id)!;

function recorder(): Settable & { sets: Record<string, unknown> } {
  const sets: Record<string, unknown> = {};
  return { sets, setInput: (node: string, field: string, value: unknown) => (sets[`${node}.${field}`] = value) };
}

test("defaults fill in and a -1 seed becomes a real seed", () => {
  const values = resolveValues(byId("z-image"), { prompt: "a cat" });
  assert.equal(values.prompt, "a cat");
  assert.equal(values.steps, 8);
  assert.equal(typeof values.seed, "number");
  assert.ok((values.seed as number) >= 0);
});

test("numbers are coerced and range-checked", () => {
  const app = byId("z-image");
  assert.equal(resolveValues(app, { prompt: "x", steps: "12" }).steps, 12);
  assert.throws(() => resolveValues(app, { prompt: "x", steps: 99 }), InputError);
});

test("select values must be one of the options", () => {
  const app = byId("upscale");
  const file = { bytes: new Uint8Array([1, 2, 3]), name: "a.png" };
  assert.equal(resolveValues(app, { image: file, scale: "4" }).scale, 4);
  assert.throws(() => resolveValues(app, { image: file, scale: 3 }), InputError);
});

test("missing files are rejected", () => {
  assert.throws(() => resolveValues(byId("edit"), { instruction: "x" }), /image: required/);
});

test("cinema studio composes the prompt from every select", () => {
  const app = byId("cinema-studio");
  const values = resolveValues(app, { prompt: "a fox in snow", seed: 1 });
  const wf = recorder();
  applyInputs(app, values, wf, () => null);
  const text = wf.sets["57:27.text"] as string;
  assert.match(text, /^a fox in snow, shot on a full-frame digital cinema camera, using a classic anamorphic lens at 35mm/);
  assert.ok(!text.includes("{"), "no placeholder left behind");
});

test("file inputs go through the asset function", () => {
  const app = byId("edit");
  const file = { bytes: new Uint8Array([1]), name: "me.png" };
  const values = resolveValues(app, { image: file, instruction: "make it night" });
  const wf = recorder();
  applyInputs(app, values, wf, (f) => `asset:${f.name}`);
  assert.equal(wf.sets["11.image"], "asset:me.png");
  assert.equal(wf.sets["4.text"], "make it night");
});

test("a select option writes its extra fields (style → LoRA file)", () => {
  const app = byId("styles");
  const values = resolveValues(app, { prompt: "a fox", style: "monochrome ink wash style", seed: 1 });
  const wf = recorder();
  applyInputs(app, values, wf, () => null);
  assert.equal(wf.sets["30:27.string_b"], "monochrome ink wash style");
  assert.equal(wf.sets["30:15.lora_name"], "krea2_darkbrush.safetensors");
  assert.throws(() => resolveValues(app, { prompt: "a fox", style: "not a style" }), InputError);
});

test("validation errors name the node and, for a missing model file, the pack to download", () => {
  const app = byId("edit");
  // the shape ComfyUI returns (captured from a real /prompt rejection), relayed by comfy-api-proxy
  const nodeErrors = {
    "1": { class_type: "UNETLoader", errors: [{ type: "value_not_in_list", message: "Value not in list",
      details: "unet_name: 'flux3-image-klein-int8-convrot.safetensors' not in (list of length 74)",
      extra_info: { input_name: "unet_name", received_value: "flux3-image-klein-int8-convrot.safetensors" } }] },
    "7": { class_type: "KSampler", errors: [{ type: "value_bigger_than_max", message: "Value bigger than max", details: "steps: 999" }] },
  };
  const msg = explainSubmitError(app, { code: "invalid_workflow", message: "Prompt outputs failed validation", details: { node_errors: nodeErrors } })!;
  assert.match(msg, /UNETLoader \(node 1\): model file flux3-image-klein-int8-convrot\.safetensors is not on the backend/);
  assert.match(msg, /KSampler \(node 7\): Value bigger than max \(steps: 999\)/);
  assert.match(msg, /--pack image-flux3/);
  assert.equal(explainSubmitError(app, new Error("network down")), null);
});

test("renderTemplate tidies empty placeholders", () => {
  assert.equal(renderTemplate("{a}, {b}, {c}", { a: "x", c: "z" }), "x, z");
});

function fakeFetch(status: (url: string) => number, seen: string[] = []): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input instanceof Request ? input.url : input);
    seen.push(url);
    return new Response(status(url) === 200 ? JSON.stringify({ freed: true }) : "{}", { status: status(url) });
  }) as typeof fetch;
}

test("prepare: a backend without the gateway (404) is skipped, auth errors are not", async () => {
  const bare = new Runner({ baseUrl: "http://backend.test", token: "t", fetch: fakeFetch(() => 404) });
  assert.deepEqual(await bare.prepare(byId("z-image")), { freed: false, skipped: true });
  const gateway = new Runner({ baseUrl: "http://backend.test", token: "t", fetch: fakeFetch(() => 200) });
  assert.deepEqual(await gateway.prepare(byId("z-image")), { freed: true });
  const denied = new Runner({ baseUrl: "http://backend.test", token: "bad", fetch: fakeFetch(() => 401) });
  await assert.rejects(denied.prepare(byId("z-image")), /answered 401/);
});

test("drafts run only when allowed", async () => {
  const draft = apps.find((a) => a.status === "draft" && a.workflowPath)!;
  const values = Object.fromEntries(draft.inputs.filter((i) => ["image", "video", "audio"].includes(i.type))
    .map((i) => [i.id, { bytes: new Uint8Array([1]), name: "x.bin" }]));
  const closed = new Runner({ baseUrl: "http://backend.test", fetch: fakeFetch(() => 500), allowDrafts: false });
  await assert.rejects(closed.submit(draft, values), (e: unknown) => e instanceof InputError && /draft/.test((e as Error).message));
  const seen: string[] = [];
  const open = new Runner({ baseUrl: "http://backend.test", fetch: fakeFetch(() => 500, seen), allowDrafts: true });
  await assert.rejects(open.submit(draft, values), (e: unknown) => !(e instanceof InputError));
  assert.ok(seen[0]?.endsWith("/freefield/prepare"), "got past the draft gate and asked the gateway");
});

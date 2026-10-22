import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ComfyEvent } from "@comfyorg/sdk";
import { loadRegistry } from "../server/registry.ts";
import { resolveValues } from "../server/runner.ts";
import { History, type JobLike } from "../server/history.ts";

const { apps } = loadRegistry();
const byId = (id: string) => apps.find((a) => a.id === id)!;
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);

/** A job that runs through queued → running → its end state when wait() is called. */
function fakeJob(end: "succeeded" | "failed", events: ComfyEvent[] = []): JobLike & { canceled: boolean } {
  let status = "queued";
  const started = new Date();
  return {
    id: "job-1",
    canceled: false,
    get status() { return status; },
    get outputs() {
      return status === "succeeded"
        ? [{ name: "ComfyUI_00001_.png", type: "image", nodeId: "9", contentType: "image/png", toBytes: async () => PNG },
           { name: "latent.bin", type: "latent", nodeId: "3", contentType: "application/octet-stream", toBytes: async () => new Uint8Array() }]
        : [];
    },
    get error() { return status === "failed" ? { message: "CUDA out of memory", class_type: "KSampler", node_id: "3" } : null; },
    get startedAt() { return status === "queued" ? null : started; },
    get completedAt() { return status === "succeeded" || status === "failed" ? new Date(started.getTime() + 2500) : null; },
    async *events() { for (const e of events) yield e; },
    async wait() { status = "running"; await new Promise((r) => setTimeout(r, 20)); status = end; },
    async cancel() { this.canceled = true; status = "canceled"; },
  };
}

function tempHistory() {
  const dir = mkdtempSync(join(tmpdir(), "ff-history-"));
  return { dir, history: new History(dir), done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("a run is recorded before it is submitted, with its inputs and the seed that was picked", () => {
  const { dir, history, done } = tempHistory();
  try {
    const app = byId("edit");
    const values = resolveValues(app, { image: { bytes: PNG, name: "me.PNG", type: "image/png" }, instruction: "add a hat" });
    const entry = history.start(app, values);
    assert.equal(entry.status, "starting");
    assert.equal(entry.values.instruction, "add a hat");
    assert.equal(typeof entry.values.seed, "number", "the resolved seed is kept, so the run can be repeated");
    assert.equal(entry.values.image, undefined, "files are not copied into the values");
    assert.deepEqual(entry.inputs.map((i) => i.file), ["input-image.png"]);
    assert.deepEqual([...readFileSync(join(dir, entry.id, "input-image.png"))], [...PNG]);
    assert.equal(history.list("edit")[0].inputs[0].url, `/api/history/${entry.id}/files/input-image.png`);
  } finally { done(); }
});

test("following a job stores its media outputs and timings", async () => {
  const { dir, history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const entry = history.start(app, resolveValues(app, { prompt: "a fox" }));
    const progress: ComfyEvent = { kind: "progress", value: 0.5, message: null, nodesDone: 1, nodesTotal: 3, currentNode: "3",
      currentNodeClass: "KSampler", step: 4, steps: 8 };
    const done1 = await history.follow(entry, fakeJob("succeeded", [progress]));
    assert.equal(done1.status, "succeeded");
    assert.equal(done1.job, "job-1");
    assert.deepEqual(done1.outputs.map((o) => [o.file, o.type]), [["out-01.png", "image"]], "latents are skipped");
    assert.ok(existsSync(join(dir, entry.id, "out-01.png")));
    assert.equal(done1.seconds, 2.5);
    assert.equal(history.get(entry.id)!.progress, null, "live progress is dropped once the run ends");
    assert.equal(JSON.parse(readFileSync(join(dir, entry.id, "meta.json"), "utf-8")).status, "succeeded");
  } finally { done(); }
});

test("a failed job keeps the node and the message", async () => {
  const { history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const entry = await history.follow(history.start(app, resolveValues(app, { prompt: "x" })), fakeJob("failed"));
    assert.equal(entry.status, "failed");
    assert.deepEqual(entry.error, { message: "CUDA out of memory", class_type: "KSampler", node: "3" });
  } finally { done(); }
});

test("a submit that never reached the backend is marked failed with the reason", () => {
  const { history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const entry = history.start(app, resolveValues(app, { prompt: "x" }));
    history.fail(entry, "Set COMFY_BASE_URL to the gateway URL");
    assert.equal(history.get(entry.id)!.status, "failed");
    assert.equal(history.get(entry.id)!.error!.message, "Set COMFY_BASE_URL to the gateway URL");
  } finally { done(); }
});

test("deleting a run that is still being submitted cancels its job once it exists", async () => {
  const { dir, history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const entry = history.start(app, resolveValues(app, { prompt: "x" }));
    assert.ok(history.remove(entry.id));
    assert.ok(!existsSync(join(dir, entry.id)));
    const job = fakeJob("succeeded");
    await history.follow(entry, job);
    assert.ok(job.canceled);
    assert.equal(history.list().length, 0);
  } finally { done(); }
});

test("runs that were going when the server stopped are lost or followed again", async () => {
  const { dir, history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const orphan = history.start(app, resolveValues(app, { prompt: "never submitted" }));
    const pending = history.start(app, resolveValues(app, { prompt: "submitted" }));
    const asFile = JSON.parse(readFileSync(join(dir, pending.id, "meta.json"), "utf-8"));
    asFile.job = "job-1"; asFile.status = "running";
    const { writeFileSync } = await import("node:fs");
    writeFileSync(join(dir, pending.id, "meta.json"), JSON.stringify(asFile));

    const stale = history.start(app, resolveValues(app, { prompt: "submitted yesterday" }));
    const staleFile = JSON.parse(readFileSync(join(dir, stale.id, "meta.json"), "utf-8"));
    staleFile.job = "job-old"; staleFile.status = "running"; staleFile.created = new Date(Date.now() - 864e5).toISOString();
    writeFileSync(join(dir, stale.id, "meta.json"), JSON.stringify(staleFile));

    const restarted = new History(dir);
    const asked: string[] = [];
    restarted.resume(async (id) => { asked.push(id); return fakeJob("succeeded"); });
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(restarted.get(orphan.id)!.status, "lost");
    assert.equal(restarted.get(pending.id)!.status, "succeeded");
    assert.equal(restarted.get(stale.id)!.status, "lost");
    assert.deepEqual(asked, ["job-1"], "an old run is not looked up (that could start a GPU for nothing)");
  } finally { done(); }
});

test("file names are checked before touching the disk", () => {
  const { history, done } = tempHistory();
  try {
    const app = byId("z-image");
    const entry = history.start(app, resolveValues(app, { prompt: "x" }));
    assert.equal(history.file(entry.id, "../meta.json"), null);
    assert.equal(history.file(entry.id, "meta.json"), null);
    assert.equal(history.file("../../etc", "out-01.png"), null);
    assert.equal(history.remove("../x"), false);
  } finally { done(); }
});

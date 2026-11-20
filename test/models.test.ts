import { test } from "node:test";
import assert from "node:assert/strict";
import { needOf, refusal, type Downloads } from "../server/models.ts";

const FLUX = "black-forest-labs/flux-3-image-klein-comfy";
const app = {
  pack: "image-flux3",
  models: [
    { repo: FLUX, file: "diffusion_models/flux3.safetensors", dir: "diffusion_models", gb: 5.8, phase: "denoise" as const, gated: true },
    { repo: FLUX, file: "vae/flux2-vae.safetensors", dir: "vae", gb: 0.3, phase: "decode" as const, gated: true },
    { repo: "Comfy-Org/mediapipe", file: "detection/face.safetensors", dir: "detection", gb: 0.01, phase: "aux" as const, optional: true },
  ],
};
const dl = (over: Partial<Downloads> = {}): Downloads => ({
  enabled: true, packs: { "image-flux3": { gb: 6.1, files: 3, missing: 2, missing_gb: 6.1, gated: [FLUX] } }, failed: {},
  job: null, queued: [], free_gb: 100, licenses: { [FLUX]: "FLUX Kommunity License" },
  token: { source: null, problem: null, can_save: true }, ...over,
});
const fail = (reason: string, at = "2026-11-19T10:00:00Z") => ({ repo: FLUX, file: "x", gated: true, reason, at, error: "GatedRepoError: 403" }) as never;
// the downloader notes every file of the pack it could not get, so both of the app's files carry the same reason
const both = (reason: string, at?: string) => ({ "diffusion_models/flux3.safetensors": fail(reason, at), "vae/flux2-vae.safetensors": fail(reason, at) });

test("nothing to say when the files are there, or when nobody can tell (Modal)", () => {
  assert.equal(needOf(app, new Set(["diffusion_models/flux3.safetensors", "vae/flux2-vae.safetensors"]), dl()), null);
  assert.equal(needOf(app, null, null), null);
});

test("a pack never asked for, a token, a license, a failure: in that order of who has to act", () => {
  const none = new Set<string>();
  assert.deepEqual(needOf(app, none, dl()), { kind: "pack", pack: "image-flux3", gb: 6.1 });
  assert.deepEqual(needOf(app, none, null), { kind: "pack", pack: "image-flux3", gb: null }, "an older gateway: as before");
  assert.deepEqual(needOf(app, none, dl({ failed: both("token_missing") })), { kind: "token", pack: "image-flux3", repos: [FLUX] });
  assert.deepEqual(needOf(app, none, dl({ failed: both("license") })), { kind: "license", pack: "image-flux3", repos: [FLUX] });
  assert.deepEqual(needOf(app, none, dl({ failed: both("failed") })), { kind: "failed", pack: "image-flux3", error: "GatedRepoError: 403" });
  // the token matters more than another file's network error
  assert.equal(needOf(app, none, dl({ failed: { "vae/flux2-vae.safetensors": fail("failed"),
    "diffusion_models/flux3.safetensors": fail("token_invalid") } }))?.kind, "token");
});

test("an app whose own pack was never downloaded says so, even when it shares a file that waits for a license", () => {
  const video = { pack: "video-wan-effects", models: [
    { repo: "Wan-AI/Wan2.2", file: "diffusion_models/wan.safetensors", dir: "diffusion_models", gb: 14, phase: "denoise" as const },
    { repo: FLUX, file: "vae/flux2-vae.safetensors", dir: "vae", gb: 0.3, phase: "decode" as const, gated: true },
  ] };
  const failed = { "vae/flux2-vae.safetensors": fail("token_missing") };
  assert.equal(needOf(video, new Set(), dl({ failed }))?.kind, "pack");
  assert.equal(needOf(video, new Set(["diffusion_models/wan.safetensors"]), dl({ failed }))?.kind, "token");
  assert.equal(needOf(video, new Set(), dl({ failed, queued: ["video-wan-effects"] }))?.kind, "downloading");
});

test("a download on its way, or queued, says so; an old failure of a file it is trying again does not count", () => {
  const none = new Set<string>();
  const job = { state: "running" as const, packs: ["image-flux3"], files: ["diffusion_models/flux3.safetensors", "vae/flux2-vae.safetensors"],
    gb: 6.1, done_gb: 0, started: "2026-11-19T12:00:00Z" };
  assert.equal(needOf(app, none, dl({ job }))?.kind, "downloading");
  assert.equal(needOf(app, none, dl({ queued: ["image-flux3"] }))?.kind, "downloading");
  assert.equal(needOf(app, none, dl({ job, failed: both("license", "2026-11-19T10:00:00Z") }))?.kind, "downloading");
  assert.equal(needOf(app, none, dl({ job, failed: { "vae/flux2-vae.safetensors": fail("license", "2026-11-19T12:00:05Z") } }))?.kind, "license",
    "failed again in this download: it needs the owner");
  assert.equal(needOf(app, none, dl({ job: { ...job, state: "done" } }))?.kind, "pack");
});

test("a run that cannot start yet says what to do", () => {
  assert.match(refusal("create-image", { kind: "token", pack: "image-flux3", repos: [FLUX] }), /accept its license.*Models panel/);
  assert.match(refusal("z-image", { kind: "pack", pack: "image", gb: 12 }), /image pack.*Models panel.*FREEFIELD_PACKS/);
});

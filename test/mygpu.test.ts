import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// mygpu.js keeps the pick in per-viewer storage: a Map stands in for localStorage
const saved = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => saved.set(key, value),
} });
const g = await import(new URL("../web/js/mygpu.js", import.meta.url).href);
const { mygpu, tierOf, gpuName, fitOn, versionFit, countsOn, recommendedVariant, variantFor, setVariant, noteDevice, pickSize } = g;

// rows as server.ts publishes them, from docs/vram-map.json
const map = JSON.parse(readFileSync(new URL("../docs/vram-map.json", import.meta.url), "utf-8"));
const row = (id: string) => {
  const r = map.apps.find((a: { id: string }) => a.id === id);
  return { id, models: [{ optional: false }], lite: r.versions.lite ? {} : null,
    vram: { tiers: r.tiers, ram_gb: r.ram_gb, measured: r.measured } };
};

test("a reported card size counts as the size on its label, never a bigger one", () => {
  assert.equal(tierOf(15.9), 16);    // RTX 5080
  assert.equal(tierOf(23.6), 24);    // RTX 3090 / 4090
  assert.equal(tierOf(31.4), 32);    // RTX 5090
  assert.equal(tierOf(44.4), 48);    // L40S
  assert.equal(tierOf(79.1), 80);    // H100
  assert.equal(tierOf(11.6), 12);
  assert.equal(tierOf(9.8), 8);      // a 10 GB card is not a 12 GB one
  assert.equal(tierOf(10.7), 8);     // nor an 11 GB one
  assert.equal(tierOf(5.8), 8);      // below the smallest size: the smallest
  assert.equal(tierOf(0), null);
  assert.equal(gpuName("cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync"), "RTX 5080");
  assert.equal(gpuName("cuda:0 NVIDIA H100 80GB HBM3 : cudaMallocAsync"), "H100 80GB HBM3");
});

test("each app says what it does on a card: as it is, lite, with RAM, or not for lack of RAM", () => {
  const z = row("z-image"), video = row("video"), sfx = row("sfx");
  assert.deepEqual(fitOn(z, { vram: 16, ram: 32 }), { level: "full", measured: false });
  assert.deepEqual(fitOn(z, { vram: 8, ram: 32 }), { level: "lite", measured: false });
  // no lite version: the full one keeps part of its weights in RAM
  assert.equal(fitOn(sfx, { vram: 8, ram: 32 }).level, "offload");
  assert.equal(fitOn(sfx, { vram: 8, ram: 32 }).variant, "full");
  // the lite version needs less RAM than the full one, so it is the one offered
  const v16 = fitOn(video, { vram: 16, ram: 64 });
  assert.equal(v16.level, "offload");
  assert.equal(v16.variant, "lite");
  assert.equal(v16.ram_gb, video.vram.ram_gb.lite);
  const short = fitOn(video, { vram: 16, ram: 16 });
  assert.equal(short.level, "noram");
  assert.equal(short.variant, "lite");
  assert.equal(fitOn(video, { vram: 24, ram: 16 }).level, "lite");
  assert.equal(fitOn(video, null), null);
});

test("a lab run on a card size that did not finish wins over the estimate", () => {
  const z = row("z-image");
  z.vram = { ...z.vram, tiers: { ...z.vram.tiers, 8: { full: "offload", lite: "no" } }, measured: { 8: { lite: { ok: false } } } };
  assert.deepEqual(versionFit(z, "lite", { vram: 8, ram: 32 }), { state: "no", ram_gb: null, reason: "lab", measured: true });
  const f = fitOn(z, { vram: 8, ram: 32 });
  assert.equal(f.level, "offload");
  assert.equal(f.variant, "full");
});

test("the counts per card add up to every app that loads models", () => {
  const apps = map.apps.filter((a: { whole_gb: number }) => a.whole_gb > 0).map((a: { id: string }) => row(a.id));
  for (const tier of [8, 16, 24, 80]) {
    const c = countsOn(apps, { vram: tier, ram: 128 });
    assert.equal(c.full + c.lite + c.offload + c.noram + c.no, apps.length, `${tier} GB`);
    const fromMap = map.counts.find((x: { tier: number }) => x.tier === tier);
    assert.deepEqual([c.full, c.lite, c.offload], [fromMap.full, fromMap.lite, fromMap.offload], `${tier} GB`);
  }
});

test("the version an app runs follows the card unless the form chose one, and only where lite runs", () => {
  const z = row("z-image");
  mygpu.liteHere = false;
  pickSize({ vram: 8, ram: 32 });
  assert.equal(recommendedVariant(z), "full");   // a backend without the lite packs runs full
  mygpu.liteHere = true;
  assert.equal(recommendedVariant(z), "lite");
  assert.equal(variantFor(z), "lite");
  setVariant(z, "full");
  assert.equal(variantFor(z), "full");
  pickSize({ vram: 24 });
  assert.equal(variantFor(z), "full");
  setVariant(z, "full");                         // the suited one is not stored: a smaller card picks again
  pickSize({ vram: 8 });
  assert.equal(variantFor(z), "lite");
  assert.equal(variantFor(row("sfx")), "full");     // no lite version
});

test("a backend that never sleeps sets the pick, a hand-picked size stays, a Modal GPU is only offered", () => {
  mygpu.set(null);
  let calls = 0;
  const off = mygpu.on(() => { calls++; });
  noteDevice({ always_on: true, device: { name: "cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync", vram_total_gb: 15.9, ram_total_gb: 31.2 } });
  assert.deepEqual(mygpu.pick, { vram: 16, ram: 32, source: "detected", name: "RTX 5080" });
  assert.equal(JSON.parse(saved.get("ff.mygpu")!).vram, 16);
  pickSize({ vram: 12 });
  noteDevice({ always_on: true, device: { name: "RTX 5080", vram_total_gb: 15.9, ram_total_gb: 31.2 } });
  assert.equal(mygpu.pick.vram, 12);
  assert.equal(mygpu.pick.source, "picked");
  mygpu.set(null);
  noteDevice({ always_on: false, device: { name: "NVIDIA L40S", vram_total_gb: 44.4 } });
  assert.equal(mygpu.pick, null);
  assert.equal(mygpu.backend.tier, 48);
  assert.ok(calls >= 3);
  off();
});

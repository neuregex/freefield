// The viewer's GPU: how much VRAM (and RAM) the card has. Picked in the top bar's "My GPU" chip, or read from the
// backend when the backend is this computer or a pod (a GPU you chose). Each app's card, its form and the VRAM map
// follow it: the app fits as it is, fits in its lite version (smaller quantized copies of its models, lite/README.md),
// runs keeping part of its weights in RAM (slower), or does not run (not enough RAM). The verdicts per card size come
// from docs/vram-map.json (tools/catalog.py): estimates from the model sizes until a lab run on that size measures them.
// No DOM here: nav.js draws the chip, views.js and workspace.js the rest.
import { store, api } from "./util.js";

export const TIERS = [8, 12, 16, 24, 32, 48, 80];   // the card sizes of docs/vram-map.json, in GB
export const RAMS = [16, 32, 64, 96, 128];
const DEFAULT_RAM = 32;

/** The size a card counts as: the largest one its memory reaches. ComfyUI reports GiB, a little under the label
 *  (a "16 GB" RTX 5080 says 15.9, a "48 GB" L40S 44.4); a 10 or 11 GB card counts as 8. */
export function tierOf(totalGb, sizes = TIERS) {
  if (!(totalGb > 0)) return null;
  return [...sizes].reverse().find((t) => t <= totalGb * 1.1) ?? sizes[0];
}

/** "cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync" → "RTX 5080" */
export function gpuName(raw) {
  const name = String(raw || "").replace(/^cuda:\d+\s*/, "").replace(/\s+:\s+\S+$/, "").replace(/^NVIDIA\s+/, "").replace(/^GeForce\s+/, "").trim();
  return name || null;
}

const valid = (p) => (p && TIERS.includes(p.vram) && RAMS.includes(p.ram) ? p : null);

export const mygpu = {
  /** { vram: 16, ram: 32, source: "picked" | "detected", name? } or null: nobody said yet */
  pick: valid(store.get("mygpu")),
  /** the backend's GPU once it said (/api/gpu?device=1): { name, vram_gb, ram_gb, tier, ram, always_on } */
  backend: null,
  /** this backend runs the lite versions (/api/apps lite_here: your own GPU, a pod, or Modal with FREEFIELD_LITE=1) */
  liteHere: false,
  listeners: new Set(),
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  set(pick) {
    this.pick = valid(pick);
    store.set("mygpu", this.pick);
    this.emit();
  },
  emit() { for (const fn of this.listeners) fn(this.pick); },
};

/** What the backend says its GPU is. A backend that never sleeps (this computer, a pod) is the card you run on: its
 *  size becomes the pick unless you picked one yourself. A Modal GPU is only offered (it is not yours to keep). */
export function noteDevice(g) {
  const d = g?.device;
  if (!d?.vram_total_gb) return;
  const seen = { name: gpuName(d.name), vram_gb: d.vram_total_gb, ram_gb: d.ram_total_gb ?? null, tier: tierOf(d.vram_total_gb),
    ram: d.ram_total_gb ? tierOf(d.ram_total_gb, RAMS) : null, always_on: Boolean(g.always_on) };
  const was = mygpu.backend;
  mygpu.backend = seen;
  const p = mygpu.pick;
  if (seen.always_on && (!p || p.source === "detected")) {
    const next = { vram: seen.tier, ram: seen.ram ?? p?.ram ?? DEFAULT_RAM, source: "detected", name: seen.name };
    if (!p || p.vram !== next.vram || p.ram !== next.ram || p.name !== next.name) return mygpu.set(next);
  }
  if (!was || was.tier !== seen.tier || was.name !== seen.name || was.ram !== seen.ram) mygpu.emit();
}

let asked = false;
/** Each /api/gpu answer (nav.js): a backend that never sleeps is asked once which GPU it has. Looking at a Modal
 *  backend never wakes it, so it is asked only when someone opens the GPU pill. */
export async function detect(g) {
  if (asked || !g?.configured || !g.always_on || !g.warm) return;
  asked = true;
  try { noteDevice(await api("/api/gpu?device=1")); } catch { /* the chip still offers the sizes */ }
}

/** Use the backend's card as the pick (the chip's "Use it"). */
export function useBackend() {
  const b = mygpu.backend;
  if (b) mygpu.set({ vram: b.tier, ram: b.ram ?? mygpu.pick?.ram ?? DEFAULT_RAM, source: b.always_on ? "detected" : "picked", name: b.name });
}

/** Pick a card size or a RAM size by hand. */
export function pickSize({ vram, ram }) {
  const p = mygpu.pick;
  mygpu.set({ vram: vram ?? p?.vram ?? mygpu.backend?.tier ?? 24, ram: ram ?? p?.ram ?? mygpu.backend?.ram ?? DEFAULT_RAM, source: "picked" });
}

/** How one version of an app runs on a card: { state: "fits" | "offload" | "no", ram_gb, reason, measured }, or null
 *  when there is no pick or no such version. "offload" turns into "no" (reason "ram") when it needs more RAM than the
 *  pick has; a lab run on that card size that did not finish is "no" too (reason "lab"). */
export function versionFit(app, variant, pick = mygpu.pick) {
  const v = app?.vram;
  const state = pick ? v?.tiers?.[String(pick.vram)]?.[variant] : null;
  if (!state) return null;
  const measured = Boolean(v.measured?.[String(pick.vram)]?.[variant]);
  if (state === "no") return { state, ram_gb: null, reason: "lab", measured };
  const ram_gb = state === "offload" ? v.ram_gb?.[variant] ?? null : null;
  if (ram_gb && ram_gb > pick.ram) return { state: "no", ram_gb, reason: "ram", measured };
  return { state, ram_gb, reason: null, measured };
}

/** What an app does on the chosen card, the version that does best first:
 *    { level: "full" }                      fits as it is
 *    { level: "lite" }                      fits in its lite version
 *    { level: "offload", variant, ram_gb }  runs with part of its weights in RAM (slower), lite when there is one
 *    { level: "noram", variant, ram_gb }    would run that way, but needs more RAM than the pick has (an estimate)
 *    { level: "no", variant }               a lab run on that card size did not finish
 *  null without a pick or a VRAM row. */
export function fitOn(app, pick = mygpu.pick) {
  if (!pick || !app?.vram?.tiers) return null;
  const full = versionFit(app, "full", pick);
  if (!full) return null;
  const lite = app.lite ? versionFit(app, "lite", pick) : null;
  if (full.state === "fits") return { level: "full", measured: full.measured };
  if (lite?.state === "fits") return { level: "lite", measured: lite.measured };
  // part of the weights in RAM: the lite version needs less of it. Neither runs: say why for the smaller one
  const [variant, f] = lite?.state === "offload" ? ["lite", lite] : full.state === "offload" ? ["full", full]
    : lite?.reason === "ram" ? ["lite", lite] : full.reason === "ram" ? ["full", full] : [lite ? "lite" : "full", lite ?? full];
  return { level: f.state === "offload" ? "offload" : f.reason === "ram" ? "noram" : "no", variant, ram_gb: f.ram_gb, measured: f.measured };
}

/** Per level, how many of `apps` (the ones that load models) do it on a card. */
export function countsOn(apps, pick = mygpu.pick) {
  const c = { full: 0, lite: 0, offload: 0, noram: 0, no: 0 };
  for (const a of apps) {
    if (!a.models?.some((m) => !m.optional)) continue;
    const f = fitOn(a, pick);
    if (f) c[f.level]++;
  }
  return c;
}

/** The version that suits the chosen card: lite when only it fits, or when part of the weights go to RAM anyway. */
export function recommendedVariant(app) {
  if (!app?.lite || !mygpu.liteHere) return "full";
  const f = fitOn(app);
  return f && (f.level === "lite" || (f.level !== "full" && f.variant === "lite")) ? "lite" : "full";
}

/** The version an app runs: the one chosen in its form, else the one that suits the card. */
export function variantFor(app) {
  if (!app?.lite || !mygpu.liteHere) return "full";
  const chosen = store.get(`variant.${app.id}`);
  return chosen === "lite" || chosen === "full" ? chosen : recommendedVariant(app);
}

/** Choose a version in an app's form. The suited one is not stored, so a card picked later still decides. */
export function setVariant(app, variant) {
  store.set(`variant.${app.id}`, variant === recommendedVariant(app) ? null : variant);
}

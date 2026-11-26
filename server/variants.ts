// The two versions of an app: "full" runs the files app.json names; "lite" swaps some of them for smaller copies of
// the same models, in quantized formats ComfyUI loads with the same node (lite/README.md). lite/variants.json says
// which file replaces which; the registry attaches each copy to its model as `lite`, and these helpers pick the files
// of a version and the renames the runner writes into the workflow.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ApiWorkflow, Model } from "./registry.ts";

export type Variant = "full" | "lite";
export type Lite = {
  repo: string;
  file: string;
  gb: number;
  /** nvfp4, mxfp8, w4a8, w6a8… (lite/README.md) */
  format: string;
  /** official: published by the model's makers or Comfy-Org; freefield: made by tools/quantize.py */
  source: "official" | "freefield";
  license?: string;
  gated?: boolean;
};

const base = (file: string) => file.split("/").pop() ?? file;

export function parseVariant(raw: unknown): Variant {
  return raw === "lite" ? "lite" : "full";
}

/** lite/variants.json as base name of the full file → its lite copy. A repo without the file has no lite versions. */
export function loadLite(root: string): Map<string, Lite> {
  const file = join(root, "lite", "variants.json");
  if (!existsSync(file)) return new Map();
  const doc = JSON.parse(readFileSync(file, "utf-8")) as { variants?: Record<string, Lite> };
  return new Map(Object.entries(doc.variants ?? {}));
}

/** True when the app loads at least one file that has a lite copy. */
export function hasLite(app: { models: Model[] }): boolean {
  return app.models.some((m) => !m.optional && m.lite);
}

/** The models a version loads: in lite, each model with a copy is that copy (same folder, same phase). */
export function modelsFor(app: { models: Model[] }, variant: Variant): Model[] {
  if (variant !== "lite") return app.models;
  return app.models.map((m) => {
    if (!m.lite) return m;
    const { lite, ...rest } = m;
    return { ...rest, repo: lite.repo, file: lite.file, gb: lite.gb, license: lite.license ?? m.license,
      gated: lite.gated ?? (lite.repo === m.repo ? m.gated : false) };
  });
}

/** Base name of a full file → base name of its lite copy, for the files this version swaps (none in full). */
export function renames(app: { models: Model[] }, variant: Variant): Map<string, string> {
  const out = new Map<string, string>();
  if (variant !== "lite") return out;
  for (const m of app.models) if (m.lite) out.set(base(m.file), base(m.lite.file));
  return out;
}

/** The node inputs of a workflow that name a file this version swaps: [node, field, new value]. */
export function workflowRenames(graph: ApiWorkflow | undefined, names: Map<string, string>): [string, string, string][] {
  const out: [string, string, string][] = [];
  if (!graph || !names.size) return out;
  for (const [node, n] of Object.entries(graph)) {
    for (const [field, v] of Object.entries(n.inputs)) {
      if (typeof v === "string" && names.has(v)) out.push([node, field, names.get(v)!]);
    }
  }
  return out;
}

/** GB a version keeps on disk: every required file, each counted once. */
export function versionGb(app: { models: Model[] }, variant: Variant): number {
  const seen = new Map<string, number>();
  for (const m of modelsFor(app, variant)) if (!m.optional) seen.set(`${m.dir}/${base(m.file)}`, m.gb);
  return Math.round([...seen.values()].reduce((a, b) => a + b, 0) * 100) / 100;
}

// The recipe box: loads every apps/<id>/app.json, validates it against the schema,
// and checks that each binding points at a real node and input of its workflow.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Ajv2020 } from "ajv/dist/2020.js";

export type Bind = { node: string; field: string; template?: string };
export type SetField = { node: string; field: string; value: unknown };
export type Option = { value: unknown; label: string; sets?: SetField[] };
export type Input = {
  id: string;
  type: "text" | "textarea" | "number" | "slider" | "select" | "toggle" | "seed" | "image" | "video" | "audio";
  label: string;
  help?: string;
  default?: unknown;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: Option[];
  gallery?: boolean;
  limits?: { max_mb?: number; seconds?: [number, number] };
  bind?: Bind[];
};
export type Preset = { id: string; label: string; sets: SetField[] };
export type Output = { node: string; type: "image" | "video" | "audio"; label?: string };
export type Model = {
  repo: string;
  file: string;
  dir: string;
  gb: number;
  phase: "encode" | "denoise" | "denoise2" | "decode" | "aux" | "all";
  gated?: boolean;
  license?: string;
  optional?: boolean;
};
export type ApiNode = { class_type: string; inputs: Record<string, unknown>; _meta?: { title?: string } };
export type ApiWorkflow = Record<string, ApiNode>;

export type AppManifest = {
  id: string;
  name: string;
  section: "image" | "video" | "audio" | "utility";
  summary?: string;
  higgsfield_feature?: string;
  pack: string;
  status: "draft" | "ready";
  workflow?: string;
  inputs: Input[];
  presets?: Preset[];
  outputs: Output[];
  models: Model[];
  credits?: string[];
  vram?: { peak_gb?: number | null; measured_on?: string | null };
  test?: Record<string, unknown>;
  notes?: string;
};

export type App = AppManifest & { dir: string; workflowPath?: string; graph?: ApiWorkflow };
export type Problem = { app: string; severity: "error" | "warning"; message: string };

const FILE_TYPES = new Set(["image", "video", "audio"]);

export function repoRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "..");
}

export function isFileInput(input: Input): boolean {
  return FILE_TYPES.has(input.type);
}

/** Names of the {placeholders} a template uses. */
export function templateVars(template: string): string[] {
  return [...template.matchAll(/\{([a-z][a-z0-9_]*)\}/g)].map((m) => m[1]);
}

/**
 * The base models this app keeps on the GPU, as dir/basename, sorted. The gateway unloads
 * everything when this changes. LoRAs are left out: ComfyUI re-patches them without
 * reloading the base model, so switching LoRAs is no reason to empty the GPU.
 */
export function modelKey(app: AppManifest): string {
  return app.models
    .filter((m) => !m.optional && m.dir !== "loras")
    .map((m) => `${m.dir}/${basename(m.file)}`)
    .sort()
    .join("|");
}

function checkGraph(app: App, problems: Problem[], severity: Problem["severity"]): void {
  const g = app.graph!;
  const say = (message: string) => problems.push({ app: app.id, severity, message });
  const has = (node: string, field: string, where: string) => {
    const n = g[node];
    if (!n) return say(`${where}: node "${node}" is not in ${app.workflow}`);
    if (!(field in n.inputs)) say(`${where}: node "${node}" (${n.class_type}) has no input "${field}"`);
  };
  const ids = new Set(app.inputs.map((i) => i.id));
  const fileIds = new Set(app.inputs.filter(isFileInput).map((i) => i.id));
  const usedInTemplates = new Set<string>();
  const checkTemplate = (template: string, where: string) => {
    for (const v of templateVars(template)) {
      if (!ids.has(v)) say(`${where}: template uses {${v}}, which is not an input`);
      else if (fileIds.has(v)) say(`${where}: template uses {${v}}, a file input`);
      usedInTemplates.add(v);
    }
  };
  for (const input of app.inputs) {
    for (const b of input.bind ?? []) {
      has(b.node, b.field, `input "${input.id}"`);
      if (b.template) checkTemplate(b.template, `input "${input.id}"`);
      if (isFileInput(input) && b.template) say(`input "${input.id}": file inputs cannot use templates`);
    }
    // string values an option writes may be templates too (an effect's prompt written around {subject})
    for (const o of input.options ?? []) {
      for (const s of o.sets ?? []) if (typeof s.value === "string") checkTemplate(s.value, `input "${input.id}" option "${o.label}"`);
    }
  }
  for (const p of app.presets ?? []) for (const s of p.sets) if (typeof s.value === "string") checkTemplate(s.value, `preset "${p.id}"`);
  for (const input of app.inputs) {
    const writes = Boolean(input.bind?.length) || (input.options ?? []).some((o) => o.sets?.length);
    if (!writes && !usedInTemplates.has(input.id)) {
      say(`input "${input.id}" is not bound to any node and no template uses it`);
    }
  }
  for (const p of app.presets ?? []) for (const s of p.sets) has(s.node, s.field, `preset "${p.id}"`);
  for (const input of app.inputs) {
    for (const o of input.options ?? []) for (const s of o.sets ?? []) has(s.node, s.field, `input "${input.id}" option "${o.label}"`);
  }
  for (const o of app.outputs) if (!g[o.node]) say(`output node "${o.node}" is not in ${app.workflow}`);
  // a math expression that names a variable with no input fails only when it runs, after validation passed
  for (const [id, n] of Object.entries(g)) {
    if (n.class_type !== "ComfyMathExpression" || typeof n.inputs.expression !== "string") continue;
    const used = new Set(n.inputs.expression.match(/\b[a-z]\b/g) ?? []);
    const missing = [...used].filter((v) => !(`values.${v}` in n.inputs));
    if (missing.length) say(`node "${id}" (ComfyMathExpression): "${n.inputs.expression}" uses ${missing.join(", ")} but has no input for it`);
  }
  // every model file the manifest declares should be referenced by some loader in the graph
  const referenced = new Set<string>();
  for (const n of Object.values(g)) for (const v of Object.values(n.inputs)) if (typeof v === "string") referenced.add(v);
  for (const m of app.models) {
    if (!m.optional && !referenced.has(basename(m.file))) {
      problems.push({ app: app.id, severity: "warning", message: `model ${basename(m.file)} is declared but no node loads it` });
    }
  }
}

export function loadRegistry(root = repoRoot()): { apps: App[]; problems: Problem[] } {
  const schema = JSON.parse(readFileSync(join(root, "schema", "app.schema.json"), "utf-8"));
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validate = ajv.compile(schema);
  const apps: App[] = [];
  const problems: Problem[] = [];
  const appsDir = join(root, "apps");
  const folders = readdirSync(appsDir).filter((d) => statSync(join(appsDir, d)).isDirectory()).sort();
  for (const folder of folders) {
    const dir = join(appsDir, folder);
    const manifestPath = join(dir, "app.json");
    if (!existsSync(manifestPath)) {
      problems.push({ app: folder, severity: "error", message: "missing app.json" });
      continue;
    }
    let manifest: AppManifest;
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
    } catch (e) {
      problems.push({ app: folder, severity: "error", message: `app.json is not valid JSON: ${(e as Error).message}` });
      continue;
    }
    if (!validate(manifest)) {
      for (const err of validate.errors ?? []) {
        problems.push({ app: folder, severity: "error", message: `schema: ${err.instancePath || "/"} ${err.message}` });
      }
      continue;
    }
    if (manifest.id !== folder) {
      problems.push({ app: folder, severity: "error", message: `id "${manifest.id}" must match its folder name` });
    }
    const app: App = { ...manifest, dir };
    const severity: Problem["severity"] = manifest.status === "ready" ? "error" : "warning";
    if (manifest.workflow) {
      const wp = join(dir, manifest.workflow);
      if (existsSync(wp)) {
        app.workflowPath = wp;
        try {
          app.graph = JSON.parse(readFileSync(wp, "utf-8"));
        } catch (e) {
          problems.push({ app: folder, severity, message: `${manifest.workflow} is not valid JSON: ${(e as Error).message}` });
        }
      } else {
        problems.push({ app: folder, severity, message: `workflow ${manifest.workflow} not found` });
      }
    } else if (manifest.status === "ready") {
      problems.push({ app: folder, severity: "error", message: "ready apps need a workflow" });
    }
    if (app.graph) checkGraph(app, problems, severity);
    apps.push(app);
  }
  return { apps, problems };
}

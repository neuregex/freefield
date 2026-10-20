// The waiter: turns form values into a filled workflow using only what app.json says,
// asks the gateway to clear the GPU when the app's models change, and submits with the Comfy SDK.
import { Comfy } from "@comfyorg/sdk";
import type { App, Input } from "./registry.ts";
import { isFileInput, modelKey } from "./registry.ts";

export type FileValue = { bytes: Uint8Array; name: string; type?: string };
export type Values = Record<string, unknown>;

/** Anything with setInput, so tests can pass a fake instead of the SDK's Workflow. */
export type Settable = { setInput(node: string, field: string, value: unknown): unknown };

export class InputError extends Error {}

function isFileValue(v: unknown): v is FileValue {
  return typeof v === "object" && v !== null && (v as FileValue).bytes instanceof Uint8Array;
}

function coerce(input: Input, raw: unknown): unknown {
  switch (input.type) {
    case "number":
    case "slider":
    case "seed": {
      const n = typeof raw === "number" ? raw : Number(raw);
      if (!Number.isFinite(n)) throw new InputError(`${input.id}: expected a number`);
      if (input.min !== undefined && n < input.min) throw new InputError(`${input.id}: must be ≥ ${input.min}`);
      if (input.max !== undefined && n > input.max) throw new InputError(`${input.id}: must be ≤ ${input.max}`);
      return input.type === "seed" ? Math.trunc(n) : n;
    }
    case "toggle":
      return raw === true || raw === "true" || raw === "1" || raw === "on";
    case "select": {
      const opts = input.options ?? [];
      const hit = opts.find((o) => o.value === raw || String(o.value) === String(raw));
      if (!hit) throw new InputError(`${input.id}: "${String(raw)}" is not one of the options`);
      return hit.value;
    }
    default:
      return raw;
  }
}

/** Fill defaults, coerce types, check required fields. File inputs pass through as FileValue. */
export function resolveValues(app: App, values: Values): Values {
  const out: Values = {};
  for (const input of app.inputs) {
    let v = values[input.id];
    if (v === undefined || v === "") v = input.default;
    if (input.type === "seed" && (v === undefined || v === -1 || v === "-1")) {
      v = Math.floor(Math.random() * 2 ** 48);
    }
    if (v === undefined) {
      if (input.required || isFileInput(input)) throw new InputError(`${input.id}: required`);
      continue;
    }
    if (isFileInput(input)) {
      if (!isFileValue(v)) throw new InputError(`${input.id}: expected a file`);
      const maxMb = input.limits?.max_mb;
      if (maxMb && v.bytes.byteLength > maxMb * 1e6) throw new InputError(`${input.id}: file is over ${maxMb} MB`);
      out[input.id] = v;
    } else {
      out[input.id] = coerce(input, v);
    }
  }
  return out;
}

export function renderTemplate(template: string, values: Values): string {
  return template
    .replace(/\{([a-z][a-z0-9_]*)\}/g, (_, k: string) => (values[k] === undefined ? "" : String(values[k])))
    .replace(/\s+,/g, ",")
    .replace(/,\s*,+/g, ",")
    .replace(/\s{2,}/g, " ")
    .trim()
    .replace(/,$/, "");
}

/**
 * Apply resolved values and an optional preset to a workflow.
 * `asset` turns a FileValue into whatever the workflow expects (an SDK asset handle).
 */
export function applyInputs(
  app: App,
  values: Values,
  wf: Settable,
  asset: (f: FileValue) => unknown,
  presetId?: string,
): void {
  for (const input of app.inputs) {
    const v = values[input.id];
    if (v === undefined) continue;
    for (const b of input.bind ?? []) {
      if (b.template) wf.setInput(b.node, b.field, renderTemplate(b.template, values));
      else wf.setInput(b.node, b.field, isFileValue(v) ? asset(v) : v);
    }
    // a select option can carry extra fields (the LoRA that goes with a style)
    const chosen = input.type === "select" ? input.options?.find((o) => o.value === v) : undefined;
    for (const s of chosen?.sets ?? []) wf.setInput(s.node, s.field, s.value);
  }
  if (presetId) {
    const preset = (app.presets ?? []).find((p) => p.id === presetId);
    if (!preset) throw new InputError(`preset "${presetId}" does not exist in ${app.id}`);
    for (const s of preset.sets) wf.setInput(s.node, s.field, s.value);
  }
}

type NodeError = { type?: string; message?: string; details?: string; extra_info?: { input_name?: string; received_value?: unknown } };
type NodeErrors = Record<string, { class_type?: string; errors?: NodeError[] } | NodeError[]>;

/**
 * Turn ComfyUI's validation errors (relayed by the proxy as details.node_errors) into lines a
 * person can act on. When a loader asks for a model file the backend does not have, say which
 * pack to download. Returns null for errors that are not workflow validation errors.
 */
export function explainSubmitError(app: App, e: unknown): string | null {
  const err = e as { code?: string; details?: { node_errors?: NodeErrors } | null; message?: string };
  if (err?.code !== "invalid_workflow") return null;
  const modelFiles = new Set(app.models.map((m) => m.file.split("/").pop()));
  const lines: string[] = [];
  let missingModel = false;
  for (const [node, entry] of Object.entries(err.details?.node_errors ?? {})) {
    const errors = Array.isArray(entry) ? entry : entry.errors ?? [];
    const cls = Array.isArray(entry) ? "" : entry.class_type ?? "";
    for (const x of errors) {
      const received = x.extra_info?.received_value ?? /'([^']+)' not in/.exec(x.details ?? "")?.[1];
      if (x.type === "value_not_in_list" && typeof received === "string" && modelFiles.has(received)) {
        missingModel = true;
        lines.push(`${cls || "node"} (node ${node}): model file ${received} is not on the backend`);
      } else {
        const detail = (x.details ?? "").replace(/ not in \[.*$/s, " is not one of the allowed values");
        lines.push(`${cls || "node"} (node ${node}): ${x.message ?? x.type ?? "invalid"}${detail ? ` (${detail.slice(0, 200)})` : ""}`);
      }
    }
  }
  if (!lines.length) lines.push(err.message ?? "workflow rejected");
  if (missingModel) {
    lines.push(`Download the "${app.pack}" pack first:  modal run infra/modal_app.py::download --pack ${app.pack}`);
  }
  return `ComfyUI rejected the workflow:\n${lines.map((l) => `  ${l}`).join("\n")}`;
}

export type RunnerOptions = {
  /** Gateway in front of comfy-api-proxy, e.g. https://you--freefield-serve.modal.run */
  baseUrl?: string;
  /** Token the gateway expects; sent by the SDK as a bearer token. */
  token?: string;
  /** Let draft apps run too (default: FREEFIELD_DRAFTS=1). Drafts have a workflow nobody has run on a GPU yet. */
  allowDrafts?: boolean;
  fetch?: typeof fetch;
};

export class Runner {
  readonly baseUrl: string;
  readonly token?: string;
  readonly allowDrafts: boolean;
  private comfy: Comfy;
  private doFetch: typeof fetch;

  constructor(opts: RunnerOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? process.env.COMFY_BASE_URL ?? "").replace(/\/$/, "");
    if (!this.baseUrl) throw new Error("Set COMFY_BASE_URL to the gateway URL");
    this.token = opts.token ?? process.env.FREEFIELD_TOKEN ?? undefined;
    this.allowDrafts = opts.allowDrafts ?? process.env.FREEFIELD_DRAFTS === "1";
    process.env.COMFY_BASE_URL = this.baseUrl; // the SDK reads its base URL from the environment
    this.doFetch = opts.fetch ?? fetch;
    this.comfy = new Comfy({ apiKey: this.token, clientInfo: "freefield", fetch: opts.fetch });
  }

  /**
   * Ask the gateway to make room for this app. It compares the model set with the one
   * loaded last and unloads everything from VRAM when they differ. A backend without the
   * Freefield gateway (a bare comfy-api-proxy, a hosted Comfy API) answers 404 and manages
   * its own memory, so that is not an error.
   */
  async prepare(app: App): Promise<{ freed: boolean; skipped?: boolean }> {
    const res = await this.doFetch(`${this.baseUrl}/freefield/prepare`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(this.token ? { authorization: `Bearer ${this.token}` } : {}),
      },
      body: JSON.stringify({ app: app.id, models: modelKey(app) }),
    });
    if (res.status === 404 || res.status === 405) return { freed: false, skipped: true };
    if (!res.ok) throw new Error(`gateway /freefield/prepare answered ${res.status}`);
    return (await res.json()) as { freed: boolean };
  }

  async submit(app: App, rawValues: Values, presetId?: string) {
    if (!app.workflowPath) throw new InputError(`${app.id} has no workflow yet`);
    if (app.status !== "ready" && !this.allowDrafts) {
      throw new InputError(`${app.id} is a draft; set FREEFIELD_DRAFTS=1 (or pass --draft) to run it anyway`);
    }
    const values = resolveValues(app, rawValues);
    await this.prepare(app);
    const wf = await this.comfy.workflows.fromFile(app.workflowPath);
    applyInputs(
      app,
      values,
      wf,
      (f) => this.comfy.assets.fromBytes(f.bytes, { filename: f.name, contentType: f.type || undefined }),
      presetId,
    );
    return this.comfy.submit(wf);
  }

  jobs() {
    return this.comfy.jobs;
  }
}

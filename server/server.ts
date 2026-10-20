// Minimal HTTP API for the web UI. Node's built-in http plus the Fetch API types; no framework.
//   GET  /api/apps                         catalog (what the UI needs to draw cards and forms)
//   POST /api/apps/:id/run                 multipart form: one field per input id, optional "preset"
//   GET  /api/jobs/:id                     status and outputs
//   GET  /api/jobs/:id/outputs/:outputId   output bytes
// Everything else is served from web/ when it exists (with byte ranges, so videos seek everywhere).
// web/examples/ holds one example per app, written by lab/publish.py; /api/apps carries it along.
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { loadRegistry, repoRoot, isFileInput, type App } from "./registry.ts";
import { explainSubmitError, InputError, Runner, type Values } from "./runner.ts";

const root = repoRoot();
const { apps, problems } = loadRegistry(root);
for (const p of problems.filter((x) => x.severity === "error")) console.error(`[registry] ${p.app}: ${p.message}`);
const byId = new Map(apps.map((a) => [a.id, a]));

// VRAM verdicts from tools/catalog.py (optional: the UI just shows less without it)
type VramRow = { id: string; whole_gb: number; largest_phase_gb: number; verdict_24gb: string; measured_peak_gb: number | null };
const vramFile = join(root, "docs", "vram-map.json");
const vram = new Map<string, VramRow>(
  existsSync(vramFile) ? (JSON.parse(readFileSync(vramFile, "utf-8")).apps as VramRow[]).map((r) => [r.id, r]) : [],
);
let runner: Runner | null = null;
const getRunner = () => (runner ??= new Runner());
const draftsAllowed = process.env.FREEFIELD_DRAFTS === "1";

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg",
};

// one example per app (lab/publish.py); read on every catalog request so a new publish shows up without a restart
const examplesFile = join(root, "web", "examples", "index.json");
function loadExamples(): Record<string, unknown> {
  try {
    return existsSync(examplesFile) ? (JSON.parse(readFileSync(examplesFile, "utf-8")).apps ?? {}) : {};
  } catch {
    return {};
  }
}

function publicApp(a: App) {
  return {
    id: a.id, name: a.name, section: a.section, summary: a.summary ?? "", status: a.status, pack: a.pack,
    runnable: Boolean(a.workflowPath) && (a.status === "ready" || draftsAllowed),
    higgsfield_feature: a.higgsfield_feature ?? null,
    inputs: a.inputs.map(({ bind: _bind, options, ...rest }) => ({
      ...rest, ...(options ? { options: options.map(({ sets: _sets, ...o }) => o) } : {}),
    })),
    presets: (a.presets ?? []).map((p) => ({ id: p.id, label: p.label })),
    outputs: a.outputs.map((o) => ({ type: o.type, label: o.label ?? null })),
    models: a.models.map((m) => ({
      name: m.file.split("/").pop(), repo: m.repo, gb: m.gb, license: m.license ?? null,
      gated: Boolean(m.gated), optional: Boolean(m.optional),
    })),
    vram: vram.has(a.id) ? {
      whole_gb: vram.get(a.id)!.whole_gb, largest_phase_gb: vram.get(a.id)!.largest_phase_gb,
      verdict: vram.get(a.id)!.verdict_24gb, measured_gb: vram.get(a.id)!.measured_peak_gb,
    } : null,
    credits: a.credits ?? [],
    notes: a.notes ?? null,
  };
}

function send(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

async function toRequest(req: IncomingMessage): Promise<Request> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  return new Request(`http://local${req.url}`, {
    method: req.method,
    headers: req.headers as Record<string, string>,
    body: chunks.length ? Buffer.concat(chunks) : undefined,
  });
}

async function readValues(app: App, request: Request): Promise<{ values: Values; preset?: string }> {
  const form = await request.formData();
  const values: Values = {};
  for (const input of app.inputs) {
    const v = form.get(input.id);
    if (v === null) continue;
    if (isFileInput(input)) {
      if (typeof v === "string") throw new InputError(`${input.id}: expected a file upload`);
      values[input.id] = { bytes: new Uint8Array(await v.arrayBuffer()), name: v.name, type: v.type };
    } else {
      values[input.id] = v;
    }
  }
  const preset = form.get("preset");
  return { values, preset: typeof preset === "string" && preset ? preset : undefined };
}

async function jobView(id: string) {
  const job = await getRunner().jobs().get(id);
  return {
    id: job.id,
    status: job.status,
    error: job.error ?? null,
    outputs: job.outputs.map((o) => ({ id: o.id, node: o.nodeId, name: o.name, type: o.type, url: `/api/jobs/${job.id}/outputs/${o.id}` })),
  };
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://local");
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts[0] === "api") {
      if (req.method === "GET" && parts[1] === "apps" && parts.length === 2) {
        const order = { image: 0, video: 1, audio: 2, utility: 3 } as Record<string, number>;
        const sorted = [...apps].sort((a, b) => order[a.section] - order[b.section]
          || Number(b.status === "ready") - Number(a.status === "ready") || a.name.localeCompare(b.name));
        const examples = loadExamples();
        return send(res, 200, { apps: sorted.map((a) => ({ ...publicApp(a), example: examples[a.id] ?? null })) });
      }
      if (req.method === "POST" && parts[1] === "apps" && parts[3] === "run") {
        const app = byId.get(parts[2]);
        if (!app) return send(res, 404, { error: "unknown app" });
        const { values, preset } = await readValues(app, await toRequest(req));
        try {
          const job = await getRunner().submit(app, values, preset);
          return send(res, 202, { id: job.id, status: job.status });
        } catch (e) {
          const explained = explainSubmitError(app, e);
          if (!explained) throw e;
          console.error(`[${app.id}] ${explained}`);
          return send(res, 422, { error: explained });
        }
      }
      if (req.method === "GET" && parts[1] === "jobs" && parts.length === 3) {
        return send(res, 200, await jobView(parts[2]));
      }
      if (req.method === "GET" && parts[1] === "jobs" && parts[3] === "outputs" && parts[4]) {
        const job = await getRunner().jobs().get(parts[2]);
        const out = job.outputs.find((o) => o.id === parts[4]);
        if (!out) return send(res, 404, { error: "unknown output" });
        const bytes = await out.toBytes();
        res.writeHead(200, { "content-type": out.contentType || "application/octet-stream", "content-length": bytes.byteLength });
        return res.end(bytes);
      }
      return send(res, 404, { error: "not found" });
    }
    // static web/
    const webRoot = join(root, "web");
    const rel = normalize(url.pathname === "/" ? "index.html" : url.pathname.slice(1)).replace(/^(\.\.[/\\])+/, "");
    const file = join(webRoot, rel);
    if (file.startsWith(webRoot) && existsSync(file) && statSync(file).isFile()) {
      const size = statSync(file).size;
      const type = MIME[extname(file).toLowerCase()] ?? "application/octet-stream";
      const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
      if (range && (range[1] || range[2])) {
        const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
        const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
        if (start > end || start >= size) {
          res.writeHead(416, { "content-range": `bytes */${size}` });
          return res.end();
        }
        res.writeHead(206, { "content-type": type, "content-length": end - start + 1, "content-range": `bytes ${start}-${end}/${size}`, "accept-ranges": "bytes" });
        return createReadStream(file, { start, end }).pipe(res);
      }
      res.writeHead(200, { "content-type": type, "content-length": size, "accept-ranges": "bytes" });
      return createReadStream(file).pipe(res);
    }
    return send(res, 404, { error: "not found" });
  } catch (e) {
    const status = e instanceof InputError ? 400 : 500;
    if (status === 500) console.error(e);
    return send(res, status, { error: (e as Error).message });
  }
});

const port = Number(process.env.PORT ?? 3000);
server.listen(port, "127.0.0.1", () => console.log(`freefield on http://127.0.0.1:${port} (${apps.length} apps)`));

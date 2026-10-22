// The history: every run started from the web UI, kept on disk so results outlive the backend's
// retention, a closed tab and a server restart.
//   out/history/<id>/meta.json        what ran: app, values, preset, status, timings, outputs, error
//   out/history/<id>/input-<x>.<ext>  the files it was given
//   out/history/<id>/out-<n>.<ext>    what it made
// A run is recorded before it is submitted, because submitting to a cold GPU can take minutes:
// the UI shows it as "starting" right away instead of a spinner on a button.
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { extname, join } from "node:path";
import { randomBytes } from "node:crypto";
import type { ComfyEvent } from "@comfyorg/sdk";
import { isFileInput, type App } from "./registry.ts";
import type { FileValue, Values } from "./runner.ts";

export type Status = "starting" | "queued" | "running" | "succeeded" | "failed" | "canceled" | "expired" | "lost";
const TERMINAL = new Set<Status>(["succeeded", "failed", "canceled", "expired", "lost"]);
const MEDIA = new Set(["image", "video", "audio"]);

export type Entry = {
  id: string;
  app: string;
  status: Status;
  job: string | null;
  created: string;
  started: string | null;
  finished: string | null;
  /** execution time on the GPU (started → finished), when the backend reports both */
  seconds: number | null;
  /** wall time from pressing Generate to the result, cold starts and queueing included */
  total: number | null;
  values: Record<string, unknown>;
  preset: string | null;
  inputs: { id: string; type: string; file: string; name: string }[];
  outputs: { file: string; type: string; name: string; node: string }[];
  error: { message: string; class_type?: string | null; node?: string | null } | null;
};

/** The part of the SDK's Job the history uses (tests pass a fake). */
export type JobLike = {
  readonly id: string;
  readonly status: string;
  readonly outputs: readonly { name: string; type: string; nodeId: string; contentType: string; toBytes(): Promise<Uint8Array> }[];
  readonly error: { message?: string; class_type?: string | null; node_id?: string | null } | null | undefined;
  readonly startedAt: Date | null;
  readonly completedAt: Date | null;
  readonly progress?: { value: number; step: number | null; steps: number | null; currentNodeClass: string | null } | null;
  readonly queuePosition?: number | null;
  events(signal?: AbortSignal): AsyncIterable<ComfyEvent>;
  wait(timeoutMs?: number, signal?: AbortSignal): Promise<unknown>;
  cancel(signal?: AbortSignal): Promise<unknown>;
};

type Live = {
  job?: JobLike;
  cancelRequested?: boolean;
  progress: { value: number; step: number | null; steps: number | null; node: string | null } | null;
  queue: number | null;
  preview: { bytes: Uint8Array; type: string; n: number } | null;
};

const ID = /^\d{8}-\d{9}-[0-9a-f]{4}$/;
const EXT: Record<string, string> = {
  "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
  "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
  "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
};

function newId(now = new Date()): string {
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  const day = `${now.getUTCFullYear()}${p(now.getUTCMonth() + 1)}${p(now.getUTCDate())}`;
  const time = `${p(now.getUTCHours())}${p(now.getUTCMinutes())}${p(now.getUTCSeconds())}${p(now.getUTCMilliseconds(), 3)}`;
  return `${day}-${time}-${randomBytes(2).toString("hex")}`;
}

/** A short lowercase extension we are willing to put on disk. */
function safeExt(name: string | undefined, type: string | undefined): string {
  const fromName = extname(name ?? "").toLowerCase();
  if (/^\.[a-z0-9]{1,5}$/.test(fromName)) return fromName;
  return EXT[(type ?? "").split(";")[0].trim()] ?? ".bin";
}

function normStatus(s: string): Status {
  if (s === "canceling") return "running";
  return (["queued", "running", "succeeded", "failed", "canceled", "expired"] as string[]).includes(s) ? (s as Status) : "running";
}

const secondsBetween = (a: string | Date | null | undefined, b: string | Date | null | undefined) =>
  a && b ? Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 100) / 10) : null;

export class History {
  private live = new Map<string, Live>();
  private removed = new Set<string>();

  readonly dir: string;
  private onContact: () => void;

  constructor(dir: string, onContact: () => void = () => {}) {
    this.dir = dir;
    this.onContact = onContact;
    mkdirSync(dir, { recursive: true });
  }

  /** Record a run before it is submitted. `values` are the resolved values (defaults filled, seed picked). */
  start(app: App, values: Values, preset?: string): Entry {
    const id = newId();
    const folder = join(this.dir, id);
    mkdirSync(folder);
    const inputs: Entry["inputs"] = [];
    const shown: Record<string, unknown> = {};
    for (const input of app.inputs) {
      const v = values[input.id];
      if (v === undefined) continue;
      if (isFileInput(input)) {
        const f = v as FileValue;
        const file = `input-${input.id}${safeExt(f.name, f.type)}`;
        writeFileSync(join(folder, file), f.bytes);
        inputs.push({ id: input.id, type: input.type, file, name: f.name || file });
      } else {
        shown[input.id] = v;
      }
    }
    const entry: Entry = {
      id, app: app.id, status: "starting", job: null, created: new Date().toISOString(), started: null, finished: null,
      seconds: null, total: null, values: shown, preset: preset ?? null, inputs, outputs: [], error: null,
    };
    this.save(entry);
    this.live.set(id, { progress: null, queue: null, preview: null });
    return entry;
  }

  /** The submit failed (bad workflow, backend unreachable, missing models): keep the reason with the run. */
  fail(entry: Entry, message: string, status: Status = "failed"): void {
    entry.status = status;
    entry.finished = new Date().toISOString();
    entry.total = secondsBetween(entry.created, entry.finished);
    entry.error = { message };
    this.save(entry);
    this.live.delete(entry.id);
  }

  /** Follow a submitted job to the end, then copy its outputs next to the record. */
  async follow(entry: Entry, job: JobLike): Promise<Entry> {
    if (this.removed.has(entry.id)) {   // deleted while it was being submitted
      await job.cancel().catch(() => {});
      return entry;
    }
    const live = this.live.get(entry.id) ?? { progress: null, queue: null, preview: null };
    this.live.set(entry.id, live);
    live.job = job;
    entry.job = job.id;
    entry.status = normStatus(job.status);
    this.save(entry);
    if (live.cancelRequested) await job.cancel().catch(() => {});

    const setStatus = (s: Status) => {
      if (TERMINAL.has(s) || s === entry.status) return;
      entry.status = s;
      if (s === "running") entry.started ??= new Date().toISOString();
      this.save(entry);
    };
    const stop = new AbortController();
    // live progress from the event stream; the poll in wait() below stays the source of truth
    const stream = (async () => {
      try {
        for await (const ev of job.events(stop.signal)) {
          this.onContact();
          if (ev.kind === "progress") {
            live.progress = { value: Number(ev.value) || 0, step: ev.step, steps: ev.steps, node: ev.currentNodeClass };
            setStatus("running");
          } else if (ev.kind === "preview") {
            live.preview = { bytes: ev.data, type: ev.contentType || "image/jpeg", n: (live.preview?.n ?? 0) + 1 };
          } else if (ev.kind === "statusChange") {
            live.queue = ev.queuePosition;
            setStatus(normStatus(ev.status));
          }
        }
      } catch {
        /* streams drop; polling decides */
      }
    })();
    // the handle's own state moves while wait() polls; mirror it for backends without events
    const tick = setInterval(() => {
      setStatus(normStatus(job.status));
      if (job.queuePosition !== undefined) live.queue = job.queuePosition ?? live.queue;
      const p = job.progress;
      if (p && (!live.progress || p.value > live.progress.value)) {
        live.progress = { value: p.value, step: p.step, steps: p.steps, node: p.currentNodeClass };
      }
    }, 1000);

    let waitError: unknown = null;
    try {
      await job.wait(6 * 3600 * 1000);
      this.onContact();
    } catch (e) {
      waitError = e;
    } finally {
      clearInterval(tick);
      stop.abort();
      await stream;
    }

    entry.started = job.startedAt?.toISOString() ?? entry.started;
    entry.finished = (job.completedAt ?? new Date()).toISOString();
    // backends that do not report timings: fall back to when this server saw it start running
    entry.seconds = secondsBetween(job.startedAt, job.completedAt) ?? (entry.started ? secondsBetween(entry.started, entry.finished) : null);
    entry.total = secondsBetween(entry.created, entry.finished);
    if (this.removed.has(entry.id)) {
      this.live.delete(entry.id);
      return entry;
    }
    if (waitError) {
      entry.status = "lost";
      entry.error = { message: `lost track of the job: ${(waitError as Error).message}` };
    } else {
      entry.status = normStatus(job.status);
      if (entry.status === "succeeded") {
        const folder = join(this.dir, entry.id);
        let n = 0;
        for (const out of job.outputs) {
          if (!MEDIA.has(out.type)) continue;
          try {
            const bytes = await out.toBytes();
            const file = `out-${String(++n).padStart(2, "0")}${safeExt(out.name, out.contentType)}`;
            writeFileSync(join(folder, file), bytes);
            entry.outputs.push({ file, type: out.type, name: out.name, node: out.nodeId });
          } catch (e) {
            entry.error = { message: `could not download ${out.name}: ${(e as Error).message}` };
          }
        }
        if (!entry.outputs.length && !entry.error) entry.error = { message: "the job finished without an image, video or audio output" };
      } else {
        const err = job.error;
        entry.error = {
          message: (err?.message || entry.status).trim(), class_type: err?.class_type ?? null, node: err?.node_id ?? null,
        };
      }
    }
    this.save(entry);
    this.live.delete(entry.id);
    return entry;
  }

  /**
   * After a restart: recent runs that were still going get followed again (a job is rehydratable
   * from its id). Runs that never got a job id, or are too old for the backend to still hold them,
   * are marked lost without asking it: asking would start a GPU just to hear the job is gone.
   */
  resume(getJob: (id: string) => Promise<JobLike>, maxAgeMs = 60 * 60 * 1000): void {
    for (const entry of this.entries()) {
      if (TERMINAL.has(entry.status)) continue;
      if (!entry.job) {
        this.fail(entry, "the server stopped before this run reached the backend", "lost");
        continue;
      }
      if (Date.now() - new Date(entry.started ?? entry.created).getTime() > maxAgeMs) {
        this.fail(entry, "the server stopped while this run was going, too long ago to pick it up again", "lost");
        continue;
      }
      this.live.set(entry.id, { progress: null, queue: null, preview: null });
      getJob(entry.job)
        .then((job) => this.follow(entry, job))
        .catch((e) => this.fail(entry, `could not pick this run up again: ${(e as Error).message}`, "lost"));
    }
  }

  async cancel(id: string): Promise<boolean> {
    const entry = this.read(id);
    if (!entry || TERMINAL.has(entry.status)) return false;
    const live = this.live.get(id);
    if (!live) return false;
    live.cancelRequested = true;
    if (live.job) await live.job.cancel().catch(() => {});
    return true;
  }

  remove(id: string): boolean {
    if (!ID.test(id) || !existsSync(join(this.dir, id))) return false;
    const live = this.live.get(id);
    if (live?.job) live.job.cancel().catch(() => {});
    this.removed.add(id);
    this.live.delete(id);
    rmSync(join(this.dir, id), { recursive: true, force: true });
    return true;
  }

  /** Absolute path of a file that belongs to a run, or null. */
  file(id: string, name: string): string | null {
    if (!ID.test(id) || !/^(input|out)-[a-z0-9_-]+\.[a-z0-9]{1,5}$/.test(name)) return null;
    const path = join(this.dir, id, name);
    return existsSync(path) ? path : null;
  }

  preview(id: string): { bytes: Uint8Array; type: string } | null {
    return this.live.get(id)?.preview ?? null;
  }

  list(app?: string, limit = 300) {
    return this.entries().filter((e) => !app || e.app === app).slice(0, limit).map((e) => this.view(e));
  }

  get(id: string) {
    const e = this.read(id);
    return e ? this.view(e) : null;
  }

  /** What the UI gets: the record plus URLs and live progress. */
  view(e: Entry) {
    const base = `/api/history/${e.id}`;
    const live = this.live.get(e.id);
    return {
      ...e,
      inputs: e.inputs.map((i) => ({ ...i, url: `${base}/files/${i.file}` })),
      outputs: e.outputs.map((o) => ({ ...o, url: `${base}/files/${o.file}` })),
      progress: live?.progress ?? null,
      queue: live?.queue ?? null,
      preview: live?.preview ? `${base}/preview?n=${live.preview.n}` : null,
    };
  }

  private entries(): Entry[] {
    if (!existsSync(this.dir)) return [];
    return readdirSync(this.dir)
      .filter((d) => ID.test(d))
      .sort()
      .reverse()
      .map((d) => this.read(d))
      .filter((e): e is Entry => e !== null);
  }

  private read(id: string): Entry | null {
    if (!ID.test(id)) return null;
    try {
      return JSON.parse(readFileSync(join(this.dir, id, "meta.json"), "utf-8")) as Entry;
    } catch {
      return null;
    }
  }

  private save(entry: Entry): void {
    const folder = join(this.dir, entry.id);
    if (!existsSync(folder)) return;   // deleted while running
    const tmp = join(folder, "meta.json.tmp");
    writeFileSync(tmp, JSON.stringify(entry, null, 2) + "\n");
    renameSync(tmp, join(folder, "meta.json"));
  }
}

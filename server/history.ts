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
import type { FileValue, Frame, Values } from "./runner.ts";

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


/** What the history needs to know about an app: its declared output nodes, how many nodes its workflow
 * has (for the progress bar) and the class of a node id (for the "KSampler 4/8" label). */
export type AppInfo = { outputs: string[]; nodes: number; classOf: (id: string) => string | null };

export type HistoryOptions = {
  onContact?: () => void;
  appInfo?: (appId: string) => AppInfo | undefined;
  /** The raw event stream of a job, read without the SDK (see Meter). Absent: job.events() is used. */
  frames?: (jobId: string, signal: AbortSignal) => AsyncIterable<Frame>;
};

type Live = {
  job?: JobLike;
  cancelRequested?: boolean;
  progress: { value: number; step: number | null; steps: number | null; node: string | null } | null;
  queue: number | null;
  preview: { bytes: Uint8Array; type: string; n: number } | null;
};

/**
 * Our own progress figure, because the stream's `value` cannot be shown as it comes. comfy-api-proxy derives it
 * from ComfyUI's progress_state, which only lists the nodes touched so far: after the first node finishes and
 * before the next starts the frame says 1/1 = 1.0. The SDK's job.events() then drops every later frame as
 * "going backwards" (first web runs through the gateway, 23 oct: the bar sat at 100 % for two minutes). So the
 * bar is (nodes finished + the running node's step fraction) / the workflow's node count, never backwards and
 * never full before the job ends. Per-node `progress` frames (nodes_total 0) carry the sampler steps.
 */
export class Meter {
  private done = 0;
  private total: number;
  private classOf: (id: string) => string | null;
  value = 0;
  step: number | null = null;
  steps: number | null = null;
  node: string | null = null;

  constructor(expectedNodes: number, classOf: (id: string) => string | null = () => null) {
    this.total = Math.max(1, expectedNodes);
    this.classOf = classOf;
  }

  /** Feed one progress snapshot (an SSE frame's data or the SDK's Progress); returns the figure to show. */
  feed(d: { value?: unknown; nodes_done?: unknown; nodes_total?: unknown; step?: unknown; steps?: unknown; current_node?: unknown }) {
    const n = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : null);
    const nodesTotal = n(d.nodes_total) ?? 0;
    if (nodesTotal > 0) {
      this.done = Math.max(this.done, n(d.nodes_done) ?? 0);
      this.total = Math.max(this.total, nodesTotal);
    }
    const step = n(d.step), steps = n(d.steps);
    const inNode = steps && steps > 0 && step !== null ? Math.min(1, Math.max(0, step / steps)) : 0;
    this.value = Math.max(this.value, Math.min(0.99, (this.done + inNode) / this.total));
    if (steps && steps > 1) { this.step = step; this.steps = steps; } else if (nodesTotal > 0) { this.step = null; this.steps = null; }
    const id = typeof d.current_node === "string" ? d.current_node : null;
    if (id) this.node = this.classOf(id) ?? this.node;
    return { value: this.value, step: this.step, steps: this.steps, node: this.node };
  }
}

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

const VIDEO_EXT = new Set([".mp4", ".webm", ".mov", ".mkv", ".gif"]);
const AUDIO_EXT = new Set([".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"]);

/** What the file is, by its extension first: core SaveVideo and CreateVideo report their mp4 under
 * `images` (with `animated: true`), so the SDK calls it an image and the web would draw it in an <img>.
 * (First web run of morph, 23 oct: a blank card for a good video.) */
function mediaKind(ext: string, sdkType: string): "image" | "video" | "audio" {
  if (VIDEO_EXT.has(ext)) return "video";
  if (AUDIO_EXT.has(ext)) return "audio";
  return sdkType === "video" || sdkType === "audio" ? sdkType : "image";
}

function normStatus(s: string): Status {
  if (s === "canceling") return "running";
  return (["queued", "running", "succeeded", "failed", "canceled", "expired"] as string[]).includes(s) ? (s as Status) : "running";
}

/** A poll that failed to reach the backend, as opposed to the backend answering that the job is gone or the request is
 * wrong: node's fetch says "fetch failed" (connection reset, DNS, TLS), a proxy answers 502/503/504 while the GPU
 * container starts, or nothing answers in time. */
export function isTransient(e: unknown): boolean {
  const err = e as { message?: string; httpStatus?: number; name?: string; cause?: { code?: string } };
  if (typeof err?.httpStatus === "number") return err.httpStatus >= 500 || err.httpStatus === 429;
  if (/not terminal after/.test(err?.message ?? "")) return false;   // the SDK's own wait timeout
  return /fetch failed|ECONN|ETIMEDOUT|EAI_AGAIN|socket hang up|network|timed? ?out|aborted/i.test(`${err?.message ?? ""} ${err?.cause?.code ?? ""}`);
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** job.wait() stops at the first poll that fails to reach the backend; a backend waking up (the Modal container's cold
 * start) drops one or two, so the wait is picked up again, for up to `patience` of continuous failures, before the
 * run is called lost. */
export async function waitPatiently(job: { wait(timeoutMs?: number): Promise<unknown> }, timeoutMs: number, patience = 10 * 60 * 1000,
  log: (msg: string) => void = () => {}): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let firstFailure: number | null = null;
  let failures = 0;
  for (;;) {
    try {
      await job.wait(Math.max(1000, deadline - Date.now()));
      return;
    } catch (e) {
      if (!isTransient(e) || Date.now() >= deadline) throw e;
      firstFailure ??= Date.now();
      if (Date.now() - firstFailure > patience) throw e;
      failures++;
      const pause = Math.min(15_000, 2_000 * failures);
      log(`poll failed (${(e as Error).message}); trying again in ${pause / 1000}s`);
      await sleep(pause);
    }
  }
}

/** The media outputs worth keeping: those of the app's declared output nodes, in the declared order (the first one
 * is the card's thumbnail), and only when none of them produced anything, every media output of the job. The
 * backend lists more than the results: core LoadVideo reports the clip it was given (mixed-media's first web run,
 * 23 oct: the card showed the input clip, the result was out-02). */
export function pickOutputs<T extends { type: string; nodeId: string }>(outputs: readonly T[], wanted: readonly string[]): T[] {
  const media = outputs.filter((o) => MEDIA.has(o.type));
  const declared = wanted.flatMap((node) => media.filter((o) => o.nodeId === node));
  return declared.length ? declared : media;
}

const secondsBetween = (a: string | Date | null | undefined, b: string | Date | null | undefined) =>
  a && b ? Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 100) / 10) : null;

export class History {
  private live = new Map<string, Live>();
  private removed = new Set<string>();

  readonly dir: string;
  private onContact: () => void;
  private appInfo: (appId: string) => AppInfo | undefined;
  private frames?: (jobId: string, signal: AbortSignal) => AsyncIterable<Frame>;

  constructor(dir: string, opts: HistoryOptions = {}) {
    this.dir = dir;
    this.onContact = opts.onContact ?? (() => {});
    this.appInfo = opts.appInfo ?? (() => undefined);
    this.frames = opts.frames;
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
    const info = this.appInfo(entry.app);
    const meter = new Meter(info?.nodes ?? 0, info?.classOf);
    const stop = new AbortController();
    // live progress from the event stream; the poll in wait() below stays the source of truth
    const stream = (async () => {
      try {
        if (this.frames) {
          for await (const f of this.frames(job.id, stop.signal)) {
            this.onContact();
            if (f.event === "progress") {
              live.progress = meter.feed(f.data);
              setStatus("running");
            } else if (f.event === "preview" && typeof f.data.data_base64 === "string") {
              live.preview = { bytes: Buffer.from(f.data.data_base64, "base64"), type: String(f.data.content_type || "image/jpeg"), n: (live.preview?.n ?? 0) + 1 };
            } else if (f.event === "status") {
              live.queue = typeof f.data.queue_position === "number" ? f.data.queue_position : null;
              setStatus(normStatus(String(f.data.status ?? "")));
            }
          }
        } else {
          for await (const ev of job.events(stop.signal)) {
            this.onContact();
            if (ev.kind === "progress") {
              live.progress = meter.feed({ nodes_done: ev.nodesDone, nodes_total: ev.nodesTotal, step: ev.step, steps: ev.steps, current_node: ev.currentNode });
              if (ev.currentNodeClass) live.progress.node = ev.currentNodeClass;
              setStatus("running");
            } else if (ev.kind === "preview") {
              live.preview = { bytes: ev.data, type: ev.contentType || "image/jpeg", n: (live.preview?.n ?? 0) + 1 };
            } else if (ev.kind === "statusChange") {
              live.queue = ev.queuePosition;
              setStatus(normStatus(ev.status));
            }
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
      if (p && (p.step !== null || (p.value > 0 && p.value > meter.value))) {
        // a backend whose poll carries a live snapshot (comfy-api-proxy's does not: 0, 0/0)
        live.progress = meter.feed({ nodes_done: p.value * (info?.nodes ?? 0), nodes_total: info?.nodes ?? 0, step: p.step, steps: p.steps });
        if (p.currentNodeClass) live.progress.node = p.currentNodeClass;
      }
    }, 1000);

    let waitError: unknown = null;
    try {
      await waitPatiently(job, 6 * 3600 * 1000, 10 * 60 * 1000, (msg) => console.warn(`[history] ${entry.id}: ${msg}`));
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
        for (const out of pickOutputs(job.outputs, info?.outputs ?? [])) {
          try {
            const bytes = await out.toBytes();
            const ext = safeExt(out.name, out.contentType);
            const file = `out-${String(++n).padStart(2, "0")}${ext}`;
            writeFileSync(join(folder, file), bytes);
            entry.outputs.push({ file, type: mediaKind(ext, out.type), name: out.name, node: out.nodeId });
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
      const entry = JSON.parse(readFileSync(join(this.dir, id, "meta.json"), "utf-8")) as Entry;
      // entries saved before mediaKind() and pickOutputs() carry the SDK's type and every output the backend
      // listed, the given clip first: fix them as they are read (the files stay on disk)
      for (const o of entry.outputs ?? []) o.type = mediaKind(extname(o.file).toLowerCase(), o.type);
      if (entry.outputs?.length > 1) {
        entry.outputs = pickOutputs(entry.outputs.map((o) => ({ ...o, nodeId: o.node })), this.appInfo(entry.app)?.outputs ?? [])
          .map(({ nodeId: _, ...o }) => o);
      }
      return entry;
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

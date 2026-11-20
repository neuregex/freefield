// What a backend that downloads its own models (a pod on RunPod or Vast, your own GPU) still lacks for each app, and
// why: the studio marks the app's card and form, and its Models panel offers the fix (accept a license and paste a
// Hugging Face token, download a pack, try again). The gateway knows (infra/gateway.py, /freefield/downloads); Modal
// is never asked, since it has every pack and asking would wake a GPU.
import type { App, Model } from "./registry.ts";

export type Failure = {
  repo: string; file: string; gated: boolean;
  /** token_missing: no token yet; token_invalid: Hugging Face refused it; license: not accepted by that account */
  reason: "token_missing" | "token_invalid" | "license" | "failed";
  error?: string; at?: string;
};
export type Job = {
  state: "running" | "done" | "stopped"; packs: string[]; files: string[]; gb: number; done_gb: number;
  current?: { file: string; gb: number } | null; started?: string; ended?: string | null; failed?: number; waiting?: number;
};
export type PackState = { gb: number; files: number; missing: number; missing_gb: number; gated: string[] };
export type Downloads = {
  enabled: boolean;
  packs: Record<string, PackState>;
  /** dir/name of a file → why it is not there (only files still missing) */
  failed: Record<string, Failure>;
  job: Job | null;
  queued: string[];
  free_gb: number;
  /** gated repo → its license's name */
  licenses: Record<string, string | null>;
  token: { source: "studio" | "env" | "login" | null; problem: string | null; can_save: boolean };
};

/** downloading: on its way; token/license: waits for the owner on Hugging Face; failed: tried and did not come;
 *  pack: never asked for (FREEFIELD_PACKS left it out). */
export type Need =
  | { kind: "downloading"; pack: string }
  | { kind: "token" | "license"; pack: string; repos: string[] }
  | { kind: "failed"; pack: string; error: string | null }
  | { kind: "pack"; pack: string; gb: number | null };

export const fileKey = (m: Pick<Model, "dir" | "file">) => `${m.dir}/${m.file.split("/").pop()}`;
const uniq = <T>(xs: T[]) => [...new Set(xs)];

/** Why `app` cannot run on this backend yet, or null when it can (or when nobody can tell: files === null). */
export function needOf(app: Pick<App, "models" | "pack">, files: Set<string> | null, dl: Downloads | null): Need | null {
  if (!files) return null;
  const lacking = app.models.filter((m) => !m.optional && !files.has(fileKey(m))).map(fileKey);
  if (!lacking.length) return null;
  const pack = app.pack ?? "?";
  const job = dl?.job?.state === "running" ? dl.job : null;
  // a failure from before the download running now, which is trying that file again, no longer counts
  const failure = (k: string) => {
    const f = dl?.failed[k];
    return f && !(job && job.files.includes(k) && (f.at ?? "") < (job.started ?? "")) ? f : null;
  };
  const why = lacking.map(failure).filter((f): f is Failure => Boolean(f));
  const coming = (k: string) => Boolean(job?.files.includes(k));
  // a file nobody asked for yet: the app's pack was never downloaded. That comes first, even when it shares a file
  // with a pack that waits for a license (a video app that prepares its frame with FLUX 3 Klein)
  const unasked = lacking.some((k) => !dl?.failed[k] && !coming(k));
  if (unasked) return dl?.queued?.includes(pack) ? { kind: "downloading", pack } : { kind: "pack", pack, gb: dl?.packs[pack]?.missing_gb ?? null };
  // then what needs the owner: one file waiting for a license matters more than another on its way
  const token = why.filter((f) => f.reason === "token_missing" || f.reason === "token_invalid");
  if (token.length) return { kind: "token", pack, repos: uniq(token.map((f) => f.repo)) };
  const license = why.filter((f) => f.reason === "license");
  if (license.length) return { kind: "license", pack, repos: uniq(license.map((f) => f.repo)) };
  if (why.length) return { kind: "failed", pack, error: why[0].error ?? null };
  return { kind: "downloading", pack };
}

/** The answer to a run of an app that cannot run yet (the UI disables Generate first; this is for scripts). */
export function refusal(id: string, need: Need): string {
  switch (need.kind) {
    case "downloading": return `${id}: its models are still downloading; it runs as soon as they are in`;
    case "token": return `${id} uses ${need.repos.join(", ")}, which asks you to accept its license on Hugging Face: `
      + "accept it, then paste a read token in the studio's Models panel (or set HF_TOKEN)";
    case "license": return `${id} uses ${need.repos.join(", ")}: this Hugging Face account has not accepted the license yet `
      + "(then Check again in the studio's Models panel)";
    case "failed": return `${id}: a model file did not download (${need.error ?? "see the log"}); the studio's Models panel tries again`;
    case "pack": return `${id} needs the ${need.pack} pack, which this backend has not downloaded: download it from the studio's `
      + "Models panel, or add it to FREEFIELD_PACKS and restart";
  }
}

// What a hosted Freefield allows: a passcode at the door and a cap on runs. Off unless configured.
//   FREEFIELD_PASSCODE          every request needs it: once as ?key=… (it becomes a cookie), or the form at /
//   FREEFIELD_MAX_RUNS_PER_DAY  runs started per UTC day across all visitors (counted in <out>/limits.json)
//   FREEFIELD_MAX_ACTIVE        runs going at the same time
// Running locally with none of these set, nothing changes.
import { createHmac, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export type GuardOptions = {
  passcode?: string;
  maxRunsPerDay?: number;
  maxActive?: number;
  stateFile?: string;
  now?: () => Date;
};

const COOKIE = "ff_key";

export class Guard {
  readonly passcode?: string;
  readonly maxRunsPerDay?: number;
  readonly maxActive?: number;
  private readonly stateFile?: string;
  private readonly now: () => Date;
  private readonly cookieValue?: string;
  private state: { day: string; runs: number };

  constructor(opts: GuardOptions = {}) {
    this.passcode = opts.passcode || undefined;
    this.maxRunsPerDay = opts.maxRunsPerDay && opts.maxRunsPerDay > 0 ? opts.maxRunsPerDay : undefined;
    this.maxActive = opts.maxActive && opts.maxActive > 0 ? opts.maxActive : undefined;
    this.stateFile = opts.stateFile;
    this.now = opts.now ?? (() => new Date());
    // the cookie holds a keyed hash of the passcode, never the passcode itself
    this.cookieValue = this.passcode ? createHmac("sha256", this.passcode).update("freefield-visitor").digest("hex") : undefined;
    this.state = this.load();
  }

  static fromEnv(stateFile: string, env: NodeJS.ProcessEnv = process.env): Guard {
    const num = (v?: string) => (v && /^\d+$/.test(v) ? Number(v) : undefined);
    return new Guard({ passcode: env.FREEFIELD_PASSCODE, maxRunsPerDay: num(env.FREEFIELD_MAX_RUNS_PER_DAY),
      maxActive: num(env.FREEFIELD_MAX_ACTIVE), stateFile });
  }

  get hosted(): boolean {
    return Boolean(this.passcode || this.maxRunsPerDay || this.maxActive);
  }

  /** Does this request carry the passcode (as the cookie)? Always true without a passcode. */
  admits(cookieHeader: string | undefined): boolean {
    if (!this.cookieValue) return true;
    const got = parseCookies(cookieHeader)[COOKIE];
    return Boolean(got) && same(got, this.cookieValue);
  }

  /** A correct ?key= becomes the cookie; the caller redirects to the same URL without it. */
  login(key: string | null): string | null {
    if (!this.passcode || !key || !same(key, this.passcode)) return null;
    return `${COOKIE}=${this.cookieValue}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`;
  }

  /** Why a new run may not start now, or null when it may. `active` = runs still going. */
  refuse(active: number): string | null {
    this.roll();
    if (this.maxActive && active >= this.maxActive) {
      return `${active} run(s) are still going on this demo (it allows ${this.maxActive} at a time); try again when one finishes`;
    }
    if (this.maxRunsPerDay && this.state.runs >= this.maxRunsPerDay) {
      return `this demo's ${this.maxRunsPerDay} runs for today (UTC) are used up; it resets at 00:00 UTC`;
    }
    return null;
  }

  /** Count one run that was accepted. */
  record(): void {
    this.roll();
    this.state.runs += 1;
    this.save();
  }

  status(active: number) {
    this.roll();
    return {
      runs_today: this.state.runs, max_runs_per_day: this.maxRunsPerDay ?? null, max_active: this.maxActive ?? null,
      runs_left: this.maxRunsPerDay ? Math.max(0, this.maxRunsPerDay - this.state.runs) : null, active,
    };
  }

  private today(): string {
    return this.now().toISOString().slice(0, 10);
  }

  private roll(): void {
    if (this.state.day !== this.today()) this.state = { day: this.today(), runs: 0 };
  }

  private load(): { day: string; runs: number } {
    try {
      if (this.stateFile && existsSync(this.stateFile)) {
        const s = JSON.parse(readFileSync(this.stateFile, "utf-8"));
        if (typeof s.day === "string" && Number.isInteger(s.runs)) return { day: s.day, runs: s.runs };
      }
    } catch { /* a damaged file starts the count again */ }
    return { day: this.today(), runs: 0 };
  }

  private save(): void {
    if (!this.stateFile) return;
    mkdirSync(dirname(this.stateFile), { recursive: true });
    const tmp = `${this.stateFile}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.state) + "\n");
    renameSync(tmp, this.stateFile);
  }
}

export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (header ?? "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

function same(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** The page a visitor without the cookie gets: one field for the passcode. */
export const DOOR_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Freefield</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='1' y='1' width='30' height='30' rx='9' fill='%23e8ff5a'/%3E%3Cpath d='M8 11.5h16M8 16.5h9M8 21.5h12' stroke='%2311140a' stroke-width='3' stroke-linecap='round'/%3E%3Ccircle cx='22.5' cy='16.5' r='1.9' fill='%2311140a'/%3E%3C/svg%3E">
<style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#09090a;color:#f4f4f2;font:15px/1.5 system-ui,sans-serif}
form{display:grid;gap:12px;width:min(320px,calc(100vw - 32px))}h1{margin:0;font-size:22px}p{margin:0;color:#9b9ba3}
input,button{font:inherit;padding:10px 12px;border-radius:8px;border:1px solid #2e2e33;background:#151517;color:inherit}
button{background:#e8ff5a;color:#11140a;border:0;font-weight:600;cursor:pointer}</style></head>
<body><form method="get" action="/"><h1>Freefield</h1><p>This demo is private. Enter the passcode you were given.</p>
<input name="key" type="password" autocomplete="current-password" aria-label="Passcode" required autofocus><button>Open</button></form></body></html>`;

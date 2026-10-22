// "Mediocre" marks on the lab examples, set from the web UI and kept in lab/flags.json so whoever
// runs the lab can read them and look for a better model, LoRA or prompt of the same kind.
//   key "<app>"                   the app's main example (web/examples/<app>/)
//   key "<app>/<input>/<option>"  one option of a gallery select (the effects picker)
// lab/publish.py drops the mark of an example it replaces: a new example starts unmarked.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { App } from "./registry.ts";

export type Mark = { at: string; note?: string };
export type FlagsFile = { about: string; mediocre: Record<string, Mark> };

const ABOUT = "Lab examples marked mediocre in the web UI. Keys: <app> for the app's example, <app>/<input>/<option> for one option " +
  "of a gallery select. lab/publish.py removes the mark of an example it replaces.";

export class Flags {
  private marks: Record<string, Mark> = {};
  private file: string;
  private apps: App[];

  constructor(file: string, apps: App[]) {
    this.file = file;
    this.apps = apps;
    this.marks = Flags.read(file);
  }

  static read(file: string): Record<string, Mark> {
    try {
      if (!existsSync(file)) return {};
      const parsed = JSON.parse(readFileSync(file, "utf-8")) as Partial<FlagsFile>;
      return typeof parsed.mediocre === "object" && parsed.mediocre ? parsed.mediocre : {};
    } catch {
      return {};
    }
  }

  /** Every mark, keyed as above. */
  list(): Record<string, Mark> {
    return { ...this.marks };
  }

  /** Throws when the key names no app, input or option of the catalog. */
  check(key: string): void {
    const [appId, inputId, value, ...rest] = key.split("/");
    const app = this.apps.find((a) => a.id === appId);
    if (!app || rest.length || (inputId !== undefined) !== (value !== undefined)) throw new Error(`unknown example "${key}"`);
    if (inputId === undefined) return;
    const input = app.inputs.find((i) => i.id === inputId && i.type === "select" && i.gallery);
    if (!input) throw new Error(`${appId} has no gallery input "${inputId}"`);
    if (!(input.options ?? []).some((o) => String(o.value) === value)) throw new Error(`${appId}/${inputId} has no option "${value}"`);
  }

  set(key: string, mediocre: boolean, note?: string): Record<string, Mark> {
    this.check(key);
    if (mediocre) this.marks[key] = { at: new Date().toISOString(), ...(note?.trim() ? { note: note.trim() } : {}) };
    else delete this.marks[key];
    this.save();
    return this.list();
  }

  /** Forget the marks of examples that are gone (an app or option removed from the catalog). */
  prune(): void {
    let changed = false;
    for (const key of Object.keys(this.marks)) {
      try { this.check(key); } catch { delete this.marks[key]; changed = true; }
    }
    if (changed) this.save();
  }

  private save(): void {
    mkdirSync(dirname(this.file), { recursive: true });
    const sorted = Object.fromEntries(Object.entries(this.marks).sort(([a], [b]) => a.localeCompare(b)));
    writeFileSync(this.file, JSON.stringify({ about: ABOUT, mediocre: sorted } satisfies FlagsFile, null, 2) + "\n");
  }
}

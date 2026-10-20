// Command line for the registry and the runner.
//   npm run validate                          check every app.json and its bindings
//   npm run apps                              list apps with status and pack
//   npm run app -- <id> [--set k=v] [--file k=path] [--preset id] [--out dir] [--draft]
import { mkdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { loadRegistry } from "./registry.ts";
import { explainSubmitError, Runner, type Values } from "./runner.ts";

const [cmd, ...rest] = process.argv.slice(2);
const { apps, problems } = loadRegistry();

function printProblems(): number {
  let errors = 0;
  for (const p of problems) {
    if (p.severity === "error") errors++;
    console.log(`${p.severity === "error" ? "✗" : "!"} ${p.app}: ${p.message}`);
  }
  return errors;
}

if (cmd === "validate") {
  const errors = printProblems();
  const ready = apps.filter((a) => a.status === "ready").length;
  console.log(`${apps.length} apps (${ready} ready, ${apps.length - ready} draft) · ${errors} errors · ${problems.length - errors} warnings`);
  process.exit(errors ? 1 : 0);
} else if (cmd === "apps") {
  for (const a of apps) console.log(`${a.status.padEnd(5)}  ${a.section.padEnd(7)}  ${a.pack.padEnd(14)}  ${a.id}`);
} else if (cmd === "app") {
  const id = rest[0];
  const app = apps.find((a) => a.id === id);
  if (!app) {
    console.error(`unknown app "${id}". Try: npm run apps`);
    process.exit(2);
  }
  const values: Values = {};
  let preset: string | undefined;
  let out = "out";
  let allowDrafts: boolean | undefined;
  for (let i = 1; i < rest.length; i++) {
    const flag = rest[i];
    if (flag === "--draft") {
      allowDrafts = true;
      continue;
    }
    const arg = rest[++i] ?? "";
    if (flag === "--set") {
      const [k, ...v] = arg.split("=");
      values[k] = v.join("=");
    } else if (flag === "--file") {
      const [k, ...v] = arg.split("=");
      const path = v.join("=");
      values[k] = { bytes: new Uint8Array(readFileSync(path)), name: basename(path) };
    } else if (flag === "--preset") preset = arg;
    else if (flag === "--out") out = arg;
  }
  const runner = new Runner({ allowDrafts });
  const t0 = Date.now();
  let job;
  try {
    job = await runner.submit(app, values, preset);
  } catch (e) {
    console.error(`could not submit ${app.id}: ${explainSubmitError(app, e) ?? (e as Error).message}`);
    process.exit(1);
  }
  console.log(`submitted ${app.id} → job ${job.id}`);
  try {
    await job.wait();
  } catch (e) {
    console.error(`job ${job.id} ended ${job.status}:`, (e as Error).message);
    process.exit(1);
  }
  if (job.status !== "succeeded") {
    const err = job.error as { message?: string; class_type?: string; node_id?: string } | null | undefined;
    const where = err?.class_type ? ` in ${err.class_type} (node ${err.node_id})` : "";
    console.error(`job ${job.id} ended ${job.status}${err ? `${where}: ${(err.message ?? JSON.stringify(err)).trim()}` : ""}`);
    process.exit(1);
  }
  console.log(`status ${job.status} in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  mkdirSync(out, { recursive: true });
  for (const o of app.outputs) {
    for (const output of job.getOutputs(o.node)) {
      const path = join(out, `${app.id}-${output.name}`);
      await output.toFile(path);
      console.log(`saved ${path}`);
    }
  }
} else {
  console.log("usage: cli.ts validate | apps | app <id> [--set k=v] [--file k=path] [--preset id] [--out dir] [--draft]");
  process.exit(cmd ? 2 : 0);
}

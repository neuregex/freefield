import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadRegistry } from "../server/registry.ts";
import { Flags } from "../server/flags.ts";

const { apps } = loadRegistry();

test("mediocre marks: an app's example and a gallery option, kept in lab/flags.json", () => {
  const dir = mkdtempSync(join(tmpdir(), "ff-flags-"));
  const file = join(dir, "flags.json");
  try {
    const flags = new Flags(file, apps);
    assert.deepEqual(flags.list(), {});
    flags.set("video", true);
    flags.set("effects/effect/crush", true, "the press barely dents it");
    assert.deepEqual(Object.keys(flags.list()).sort(), ["effects/effect/crush", "video"]);
    assert.equal(flags.list()["effects/effect/crush"].note, "the press barely dents it");

    const saved = JSON.parse(readFileSync(file, "utf-8"));
    assert.ok(saved.about.includes("lab/publish.py"), "the file says who clears the marks");
    assert.deepEqual(Object.keys(saved.mediocre), ["effects/effect/crush", "video"], "sorted on disk");

    const again = new Flags(file, apps);   // a server restart reads them back
    assert.equal(again.list().video.at, flags.list().video.at);
    again.set("video", false);
    assert.deepEqual(Object.keys(again.list()), ["effects/effect/crush"]);

    assert.throws(() => flags.set("no-such-app", true), /unknown example/);
    assert.throws(() => flags.set("effects/effect/painting", true), /no option/, "an option that left the app");
    assert.throws(() => flags.set("effects/aspect/portrait", true), /no gallery input/, "only gallery selects have examples per option");
    assert.throws(() => flags.set("effects/effect", true), /unknown example/, "half a key");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

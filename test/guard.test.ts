import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Guard, parseCookies } from "../server/guard.ts";

test("without settings the guard lets everything through", () => {
  const g = new Guard();
  assert.equal(g.hosted, false);
  assert.equal(g.admits(undefined), true);
  assert.equal(g.login("anything"), null);
  assert.equal(g.refuse(99), null);
});

test("the passcode becomes a cookie that holds a hash, not the passcode", () => {
  const g = new Guard({ passcode: "open-sesame" });
  assert.equal(g.admits(undefined), false);
  assert.equal(g.login("wrong"), null);
  assert.equal(g.login(null), null);
  const cookie = g.login("open-sesame")!;
  assert.match(cookie, /HttpOnly; Secure; SameSite=Lax/);
  assert.ok(!cookie.includes("open-sesame"));
  const pair = cookie.split(";")[0];
  assert.equal(g.admits(`other=1; ${pair}`), true);
  assert.equal(g.admits("ff_key=deadbeef"), false);
  assert.equal(new Guard({ passcode: "another" }).admits(pair), false);
});

test("runs are capped per UTC day and at the same time, and the count survives a restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "ff-guard-"));
  const file = join(dir, "limits.json");
  let now = new Date("2026-10-28T23:50:00Z");
  const g = new Guard({ maxRunsPerDay: 2, maxActive: 1, stateFile: file, now: () => now });
  assert.equal(g.refuse(0), null);
  g.record();
  assert.match(g.refuse(1)!, /1 at a time/);
  assert.equal(g.refuse(0), null);
  g.record();
  assert.match(g.refuse(0)!, /2 runs for today/);
  assert.deepEqual(JSON.parse(readFileSync(file, "utf-8")), { day: "2026-10-28", runs: 2 });
  const again = new Guard({ maxRunsPerDay: 2, stateFile: file, now: () => now });
  assert.equal(again.status(0).runs_left, 0);
  now = new Date("2026-10-29T00:01:00Z");
  assert.equal(again.refuse(0), null);
  assert.equal(again.status(0).runs_left, 2);
});

test("cookies parse with spaces and values that hold '='", () => {
  assert.deepEqual(parseCookies(" a=1;b=x=y ; c="), { a: "1", b: "x=y", c: "" });
  assert.deepEqual(parseCookies(undefined), {});
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { foreign, Guard, parseCookies } from "../server/guard.ts";

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

test("with a passcode each browser gets its own visitor id; without one there is none", () => {
  assert.deepEqual(new Guard().visitor(undefined), {});
  const g = new Guard({ passcode: "open-sesame" });
  const fresh = g.visitor(undefined);
  assert.match(fresh.id!, /^[0-9a-f]{32}$/);
  assert.match(fresh.setCookie!, new RegExp(`^ff_vid=${fresh.id}; Path=/; HttpOnly; Secure; SameSite=Lax`));
  assert.deepEqual(g.visitor(`ff_key=x; ff_vid=${fresh.id}`), { id: fresh.id }, "a known id is kept, no new cookie");
  assert.notEqual(g.visitor(undefined).id, fresh.id, "two browsers, two ids");
  assert.ok(g.visitor("ff_vid=../../etc").setCookie, "a malformed id is replaced");
});

test("requests from other sites are refused: rebound DNS names, cross-site writes", () => {
  const local = { loopbackOnly: true, allowedHosts: ["studio.lan"] };
  const req = (method: string, headers: Record<string, string>) => ({ method, headers: { host: "127.0.0.1:3000", ...headers } });
  assert.equal(foreign(req("GET", {}), local), null);
  assert.equal(foreign(req("GET", { host: "localhost:3000" }), local), null);
  assert.equal(foreign(req("GET", { host: "[::1]:3000" }), local), null);
  assert.equal(foreign(req("GET", { host: "studio.lan:3000" }), local), null, "FREEFIELD_ALLOWED_HOSTS");
  assert.match(foreign(req("GET", { host: "evil.example:3000" }), local)!, /only answers to localhost/);
  // the web UI's own calls, from a current browser and from one without Sec-Fetch-Site
  assert.equal(foreign(req("POST", { "sec-fetch-site": "same-origin", origin: "http://127.0.0.1:3000" }), local), null);
  assert.equal(foreign(req("DELETE", { origin: "http://127.0.0.1:3000" }), local), null);
  assert.equal(foreign(req("POST", {}), local), null, "the CLI and scripts send no Origin");
  // another site's form or fetch
  assert.match(foreign(req("POST", { "sec-fetch-site": "cross-site", origin: "https://evil.example" }), local)!, /other sites/);
  assert.match(foreign(req("POST", { origin: "https://evil.example" }), local)!, /other sites/);
  assert.match(foreign(req("POST", { "sec-fetch-site": "same-site", origin: "http://localhost:8080" }), local)!, /other sites/);
  assert.match(foreign(req("POST", { origin: "null" }), local)!, /other sites/, "a sandboxed frame");
  // hosted (listening on 0.0.0.0): any Host, writes still same-origin only
  const hosted = { loopbackOnly: false };
  const demo = { host: "me--freefield-demo.modal.run" };
  assert.equal(foreign({ method: "POST", headers: { ...demo, "sec-fetch-site": "same-origin" } }, hosted), null);
  assert.match(foreign({ method: "POST", headers: { ...demo, origin: "https://evil.example" } }, hosted)!, /other sites/);
});

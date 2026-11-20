import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DesktopIcon } from "../server/desktop.ts";

test("no launcher, no question: RunPod, Vast.ai and the demo never see the card", () => {
  const icon = DesktopIcon.fromEnv({});
  assert.equal(icon.state(), null);
  assert.equal(icon.answer(true), null);
});

test("the launcher's studio asks once, keeps the answer in the volume, and a made icon stays made", () => {
  const data = mkdtempSync(join(tmpdir(), "ff-icon-"));
  const icon = DesktopIcon.fromEnv({ FREEFIELD_DESKTOP_ICON: "1", FREEFIELD_DATA: data });
  assert.equal(icon.state(), "ask");
  assert.equal(icon.answer(true), "wanted");
  assert.equal(icon.state(), "wanted");
  writeFileSync(join(data, "desktop-icon"), "created\n");   // what start.ps1 writes once the icon is there
  assert.equal(icon.state(), "created");
  assert.equal(icon.answer(false), "created", "no taking back an icon that is already on the desktop");
  writeFileSync(join(data, "desktop-icon"), "nonsense");
  assert.equal(icon.state(), "ask");
  assert.equal(icon.answer(false), "declined");
  assert.equal(icon.state(), "declined");
});

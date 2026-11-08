import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
const { localizeApp, RU_APP_TEXT } = await import(new URL("../web/js/app-locale.js", import.meta.url).href);

function freeze(value: any): any {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

// Remove only display fields at their documented paths, not arbitrary nested
// "name" or "label" fields inside source, bindings, defaults or model metadata.
function executionData(app: any) {
  const copy = structuredClone(app);
  for (const key of ["name", "summary", "higgsfield_feature", "mode_label", "notes", "credits"]) delete copy[key];
  for (const input of copy.inputs) {
    for (const key of ["label", "help", "placeholder"]) delete input[key];
    for (const option of input.options ?? []) delete option.label;
  }
  for (const output of copy.outputs) delete output.label;
  for (const preset of copy.presets ?? []) delete preset.label;
  return copy;
}

test("every app preserves all execution data and its frozen source through locale changes", (context) => {
  const root = new URL("../apps/", import.meta.url);
  const missing: string[] = [];
  let count = 0;
  for (const folder of readdirSync(root)) {
    const original = freeze(JSON.parse(readFileSync(new URL(`${folder}/app.json`, root), "utf8")));
    const before = JSON.stringify(original);
    let language = "en";
    const localized = localizeApp(original, () => language);
    for (const next of ["ru", "es", "en", "ru"]) {
      language = next;
      assert.deepEqual(executionData(localized), executionData(original), `${folder}: ${next}`);
      assert.equal(JSON.stringify(original), before, folder);
      if (next !== "ru") assert.equal(localized.name, original.name, folder);
    }
    for (let i = 0; i < original.inputs.length; i++) {
      const input = original.inputs[i];
      if (["text", "textarea"].includes(input.type) && typeof input.default === "string" && input.default) {
        const translated = Object.hasOwn(RU_APP_TEXT, input.default);
        if (!translated) missing.push(`${folder}.${input.id}: ${input.default}`);
        assert.equal(localized.inputs[i].displayDefault, translated ? RU_APP_TEXT[input.default] : input.default);
        assert.equal(localized.inputs[i].default, input.default);
        assert.equal(Object.keys(localized.inputs[i]).includes("displayDefault"), false);
      }
    }
    if (original.id === "ai-influencer") assert.equal(localized.inputs.find((i: any) => i.id === "stature").label, "Рост");
    count++;
  }
  assert.ok(count >= 120);
  if (missing.length) context.diagnostic(`Missing Russian prompt hints (English fallback):\n${missing.join("\n")}`);
});

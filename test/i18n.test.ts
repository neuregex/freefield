import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

// Browser modules need only the language attribute and per-viewer storage here.
const saved = new Map<string, string>();
Object.defineProperty(globalThis, "document", { configurable: true, value: { documentElement: { lang: "en" } } });
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => saved.set(key, value),
} });
const { DICT, LANGS, resolveLanguage, setLang, t } = await import(new URL("../web/js/i18n.js", import.meta.url).href);
const { RU_APP_TEXT, appText, localizeApp } = await import(new URL("../web/js/app-locale.js", import.meta.url).href);
const { fmtSeconds, fmtShort } = await import(new URL("../web/js/util.js", import.meta.url).href);

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("Russian UI reports missing translations and preserves every translated interpolation placeholder", (context) => {
  const missing: string[] = [];
  assert.ok(LANGS.some(([code, label]: string[]) => code === "ru" && label === "Русский"));
  for (const [key, original] of Object.entries(DICT.en)) {
    if (!Object.hasOwn(DICT.ru, key)) {
      missing.push(`${key}: ${original}`);
      continue;
    }
    const translation = DICT.ru[key];
    const forms: string[] = typeof translation === "string" ? [translation] : Object.values(translation);
    for (const form of forms) {
      assert.ok(form || original === "", key);
      assert.deepEqual(placeholders(form), placeholders(original as string), key);
    }
  }
  if (missing.length) context.diagnostic(`Missing Russian UI translations (English fallback):\n${missing.join("\n")}`);
});

test("supported stored language wins; regional browser locales and invalid storage are safe", () => {
  assert.equal(resolveLanguage("es", ["ru-RU", "en-US"]), "es");
  assert.equal(resolveLanguage(null, ["ru-RU", "en-US"]), "ru");
  assert.equal(resolveLanguage(null, "RU-ru"), "ru");
  assert.equal(resolveLanguage("invalid", ["fr-FR", "es-MX"]), "es");
  assert.equal(resolveLanguage({ unexpected: true }, ["ru"]), "ru");
  assert.equal(resolveLanguage(null, ["fr-FR"]), "en");
  assert.equal(resolveLanguage(null, []), "en");
});

test("Russian plurals, interpolation and persisted switching do not regress English or Spanish", () => {
  setLang("ru");
  assert.match(t("explore.apps", { n: 1 }), /1 приложение$/);
  assert.match(t("explore.apps", { n: 2 }), /2 приложения$/);
  assert.match(t("explore.apps", { n: 5 }), /5 приложений$/);
  assert.match(t("explore.apps", { n: 11 }), /11 приложений$/);
  assert.match(t("explore.apps", { n: 21 }), /21 приложение$/);
  assert.match(t("explore.apps", { n: 1.5 }), /1.5 приложения$/);
  assert.equal(document.documentElement.lang, "ru");
  assert.equal(saved.get("ff.lang"), '"ru"');
  assert.equal(t("not.a.key"), "not.a.key");
  assert.equal(t("ws.need", { label: "Фото" }).includes("Фото"), true);
  setLang("en");
  assert.equal(t("ws.generate"), "Generate");
  setLang("es");
  assert.equal(t("ws.generate"), "Generar");
  setLang("invalid");
  assert.equal(document.documentElement.lang, "es");
});

test("catalog translations preserve placeholders and report missing display strings and attribution", (context) => {
  // Validate existing translations even when their English source is no longer
  // in a manifest; missing translations alone must not block new apps or text.
  for (const [original, translation] of Object.entries(RU_APP_TEXT)) {
    assert.equal(typeof translation, "string", original);
    assert.deepEqual(placeholders(translation as string), placeholders(original), original);
  }
  const missing = new Set<string>();
  const root = new URL("../apps/", import.meta.url);
  const fields = new Set(["name", "summary", "higgsfield_feature", "mode_label", "label", "help", "placeholder", "notes"]);
  const skipped = new Set(["source", "models", "bind", "sets", "default", "workflow"]);
  let count = 0;
  function visit(value: unknown, context: string) {
    if (Array.isArray(value)) { value.forEach((v) => visit(v, context)); return; }
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (skipped.has(key)) continue;
      if (fields.has(key) && typeof child === "string") {
        if (!Object.hasOwn(RU_APP_TEXT, child)) missing.add(`${context}.${key}: ${child}`);
        count++;
      } else if (key === "credits" && Array.isArray(child)) {
        for (const credit of child) {
          if (!Object.hasOwn(RU_APP_TEXT, credit)) missing.add(`${context}.credits: ${credit}`);
        }
      } else visit(child, `${context}.${key}`);
    }
  }
  for (const name of readdirSync(root)) visit(JSON.parse(readFileSync(new URL(`${name}/app.json`, root), "utf8")), name);
  assert.ok(count > 1000, `checked ${count} catalog strings`);
  if (missing.size) context.diagnostic(`Missing Russian catalog translations (English fallback):\n${[...missing].join("\n")}`);
});

test("catalog localization follows language live without changing submission data or the API object", () => {
  const original = {
    id: "edit", name: "Edit Image", summary: "Unknown future summary", section: "image", pack: "image-flux3", status: "ready",
    inputs: [{ id: "prompt", label: "Scene", type: "textarea", default: "A detective in the rain", help: "Unknown future help" },
      { id: "genre", label: "Genre", default: " from a drama", options: [{ label: "Drama", value: " from a drama", sets: { "1.text": "Do not translate" } }] }],
    outputs: [{ type: "image", label: "Image" }],
    presets: [{ id: "fast", label: "Fast", values: { steps: 4 } }],
    models: [{ name: "FLUX 3 Image Klein", license: "FLUX Kommunity License", repo: "black-forest-labs/FLUX.3-klein" }],
    credits: ["Workflow: ComfyUI official template"],
    example: { values: { prompt: "Keep the example prompt" } },
  };
  const snapshot = JSON.stringify(original);
  let language = "en";
  const localized = localizeApp(original, () => language);
  assert.equal(localized.inputs[0].label, "Scene");
  language = "ru";
  assert.notEqual(localized.name, original.name);
  assert.notEqual(localized.inputs[0].label, original.inputs[0].label);
  assert.notEqual(localized.inputs[1].options[0].label, "Drama");
  assert.notEqual(localized.credits[0], original.credits[0]);
  assert.equal(localized.summary, original.summary);
  assert.equal(localized.inputs[0].help, original.inputs[0].help);
  assert.equal(localized.inputs[0].default, original.inputs[0].default);
  assert.equal(localized.inputs[1].options[0].value, " from a drama");
  assert.deepEqual(localized.inputs[1].options[0].sets, { "1.text": "Do not translate" });
  assert.deepEqual(localized.example, original.example);
  assert.deepEqual(localized.models, original.models);
  assert.deepEqual(localized.presets[0].values, { steps: 4 });
  assert.equal(JSON.stringify(original), snapshot);
  language = "es";
  assert.equal(localized.name, original.name);
  language = "en";
  assert.equal(localized.inputs[1].options[0].label, "Drama");
  assert.equal(appText("Unknown new label", "ru"), "Unknown new label");
});

test("duration units track the selected locale without a circular import", () => {
  setLang("ru");
  assert.equal(fmtSeconds(5), "5 с");
  assert.equal(fmtSeconds(125), "2 мин 05 с");
  assert.equal(fmtShort(120), "~2 мин");
  setLang("en");
  assert.equal(fmtSeconds(5), "5 s");
  assert.equal(fmtSeconds(125), "2 min 05 s");
  assert.equal(fmtShort(120), "~2 min");
});

// Localize presentation only: workflow IDs, option values, prompts, files and licenses
// must stay exactly as the backend expects them. Getters follow language changes
// without refetching the catalog or mutating the API response.
import { ruApps } from "./locales/ru-apps.js";
import { ruCredits } from "./locales/ru-credits.js";
import { ruPrompts } from "./locales/ru-prompts.js";

export const RU_APP_TEXT = { ...ruApps, ...ruCredits, ...ruPrompts };

export function appText(text, locale) {
  return locale === "ru" && typeof text === "string" && Object.hasOwn(RU_APP_TEXT, text) ? RU_APP_TEXT[text] : text;
}

function displayFields(source, getLanguage, keys, russian = {}) {
  const result = { ...source };
  for (const key of keys) {
    if (!(key in source)) continue;
    Object.defineProperty(result, key, {
      enumerable: true,
      get: () => getLanguage() === "ru" && key in russian ? russian[key] : appText(source[key], getLanguage()),
    });
  }
  return result;
}

export function localizeApp(app, getLanguage) {
  const result = displayFields(app, getLanguage, ["name", "summary", "higgsfield_feature", "mode_label", "notes"]);
  result.inputs = app.inputs.map((input) => {
    // Human stature is "Рост"; pixel and camera height elsewhere is "Высота".
    const russian = app.id === "ai-influencer" && input.id === "stature" ? { label: "Рост" } : {};
    const localized = displayFields(input, getLanguage, ["label", "help", "placeholder"], russian);
    // A translated hint must never replace the actual generation default.
    if (["text", "textarea"].includes(input.type) && typeof input.default === "string") Object.defineProperty(localized, "displayDefault", {
      get: () => appText(input.default, getLanguage()),
    });
    if (input.options) localized.options = input.options.map((option) => displayFields(option, getLanguage, ["label"]));
    return localized;
  });
  result.outputs = app.outputs.map((output) => displayFields(output, getLanguage, ["label"]));
  if (app.presets) result.presets = app.presets.map((preset) => displayFields(preset, getLanguage, ["label"]));
  if (app.credits) Object.defineProperty(result, "credits", {
    enumerable: true,
    get: () => app.credits.map((credit) => appText(credit, getLanguage())),
  });
  return result;
}

# Web UI localization

The globe menu offers English, Spanish and Russian. A supported saved preference
wins over the browser's preferred supported language (`ru-RU` selects `ru`).
Unsupported or invalid preferences fall back safely, ultimately to English.
Selection is stored per browser as `ff.lang`; switching does not require a reload.

## Translation layers

- `web/js/i18n.js`: interface strings, placeholders such as `{n}`, locale
  selection and Russian `Intl.PluralRules` forms (`one`, `few`, `many`, `other`).
- `web/js/catalog.js`: localized app taglines and model menu descriptions.
- `web/js/locales/ru-apps.js`: exact English display strings from the app
  manifests mapped to Russian. This also covers input help, option labels,
  presets, summaries and consent notes. Identical strings share translations.
- `web/js/locales/ru-credits.js`: attribution prose, preserving author names and
  the original model/license identifiers.
- `web/js/locales/ru-prompts.js`: Russian display-only hints for sample prompts.
  A non-enumerable `displayDefault` getter is used only for input placeholders;
  the actual `default` and any submitted prompt remain unchanged.
- `web/js/app-locale.js`: a presentation-only catalog wrapper. Live getters
  follow the selected language without changing the raw API response. A small
  contextual override distinguishes human stature (`Рост`) from image height
  (`Высота`). New untranslated strings fall back to their English source.

English and Spanish catalog metadata retain their existing English source text;
this change does not rewrite either locale's existing translations.

## Do not translate execution data

Keep app/input/preset IDs, option `value` and `sets`, default generation prompts,
workflow bindings, paths, model names, repository names, license identifiers and
lab example values unchanged. In particular, an English prompt shown in an
editable field or in a lab example is generation data, not a missing UI label.
Changing a locale must never change what is submitted to ComfyUI.

## Maintaining a translation

When adding a UI key, add its translations where available and keep interpolation
placeholders equal to the English key. For catalog display strings, use the exact
manifest string as the key; do not edit generated manifests merely to translate them. Keep
proper names and numeric camera/format values recognizable. Where an English
label has different meanings, use a narrowly scoped presentation override.

Run:

```sh
npm test
npm run validate
npm run typecheck
```

`npm test` lists missing Russian UI keys, catalog display strings, attribution
and sample-prompt hints as non-failing diagnostics, including the source text
and its key or manifest location. Missing translations fall back to English at
runtime, so adding an app or changing English text does not require a Russian
translation to pass CI. Existing translations must still preserve interpolation
placeholders such as `{n}` and `{label}`; mismatches fail the tests.

`test/i18n.test.ts` also checks Russian count forms, browser and saved-locale
resolution, live switching and safe fallback. `test/app-locale.test.ts` keeps
submission-data preservation, frozen-source checks and translated-or-English
prompt hints strict across all apps. These tests need no backend,
GPU or model downloads. Browser checks should additionally cover the globe menu,
reload persistence, app search, workspace options, How it works, the library,
VRAM map and a mobile viewport. Do not generate media just to test a translation.

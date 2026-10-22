// An app's workspace. Two layouts, both built from app.json alone:
//   composer: prompt-first apps (image, audio): results fill the page, a floating prompt bar sits at the bottom
//   sidebar:  upload-first apps (video, tools): controls in a left column, results and examples on the right
import { el, icon, store, toast, popover, closePopover, fmtSeconds, fmtShort, isMedia, extOf, masonry } from "./util.js";
import { t } from "./i18n.js";
import {
  byId, layoutOf, familyOf, VIDEO_TABS, videoTabOf, tagline, iconOf, promptInput, estimate, fitOf, rememberApp, categoryOf, CATEGORIES, apps,
} from "./catalog.js";
import { exampleItem, thumb, hoverPlay, fullMedia, playWhenVisible, optionTile, optionThumb } from "./media.js";
import { flags, flagButton } from "./flags.js";
import { feed, feedView, hooks } from "./feed.js";

// ------------------------------------------------------------------ form state (per app, kept while the page is open)
const forms = new Map();

function validValue(inp, v) {
  if (v === undefined || v === null) return false;
  if (inp.type === "select") return (inp.options || []).some((o) => String(o.value) === String(v));
  if (inp.type === "slider" || inp.type === "number") return Number.isFinite(Number(v)) && (inp.min === undefined || v >= inp.min) && (inp.max === undefined || v <= inp.max);
  return true;
}

export function formFor(app) {
  let f = forms.get(app.id);
  if (f) return f;
  const saved = store.get(`values.${app.id}`) || {};
  const values = {};
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) continue;
    const fallback = inp.type === "textarea" || inp.type === "text" ? "" : inp.type === "seed" ? -1 : inp.default ?? "";
    values[inp.id] = validValue(inp, saved[inp.id]) ? saved[inp.id] : fallback;
  }
  f = { values, files: {}, preset: (app.presets || []).some((p) => p.id === saved.__preset) ? saved.__preset : "", count: 1 };
  forms.set(app.id, f);
  return f;
}
function persist(app) {
  const f = formFor(app);
  store.set(`values.${app.id}`, { ...f.values, __preset: f.preset });
}

const ACCEPT = { image: "image/*", video: "video/*", audio: "audio/*" };
function fileMatches(type, file) {
  if (file.type) return file.type.startsWith(`${type}/`);
  const ext = extOf(file.name);
  return { image: ["png", "jpg", "jpeg", "webp", "gif"], video: ["mp4", "mov", "webm", "mkv"], audio: ["mp3", "wav", "flac", "ogg", "m4a"] }[type]?.includes(ext);
}

function setFile(app, inp, file) {
  if (!fileMatches(inp.type, file)) {
    toast(`${inp.label}: ${file.name}?`, { error: true });
    return false;
  }
  const maxMb = inp.limits?.max_mb;
  if (maxMb && file.size > maxMb * 1e6) {
    toast(`${inp.label}: ${t("ws.drop.mb", { mb: maxMb })}`, { error: true });
    return false;
  }
  const f = formFor(app);
  if (f.files[inp.id]) URL.revokeObjectURL(f.files[inp.id].url);
  f.files[inp.id] = { file, url: URL.createObjectURL(file) };
  return true;
}
function clearFile(app, id) {
  const f = formFor(app);
  if (f.files[id]) URL.revokeObjectURL(f.files[id].url);
  delete f.files[id];
}

/** Put dropped or pasted files into the first matching slots. */
function assignFiles(app, files) {
  const slots = app.inputs.filter((i) => isMedia(i.type));
  const f = formFor(app);
  let used = 0;
  for (const file of files) {
    const free = slots.find((s) => fileMatches(s.type, file) && !f.files[s.id]) || slots.find((s) => fileMatches(s.type, file));
    if (free && setFile(app, free, file)) used++;
  }
  return used;
}

async function fileFromUrl(url, name) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type || res.headers.get("content-type") || "" });
}

// ------------------------------------------------------------------ submitting
function missingInputs(app) {
  const f = formFor(app);
  const out = [];
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) { if (inp.required && !f.files[inp.id]) out.push(inp); continue; }
    if (inp.required && inp.type === "textarea" && !String(f.values[inp.id] ?? "").trim() && !inp.default) out.push(inp);
  }
  return out;
}

function buildForm(app, { randomSeed = false } = {}) {
  const f = formFor(app);
  const fd = new FormData();
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) { const x = f.files[inp.id]; if (x) fd.append(inp.id, x.file, x.file.name); continue; }
    const v = f.values[inp.id];
    if (inp.type === "toggle") { fd.append(inp.id, v ? "true" : "false"); continue; }
    if (inp.type === "seed" && (randomSeed || v === -1 || v === "-1" || v === "" || v === null)) continue;
    if (v === "" || v === null || v === undefined) continue;
    fd.append(inp.id, String(v));
  }
  if (f.preset) fd.append("preset", f.preset);
  return fd;
}

/** Validate, then submit `count` runs. Returns false when something is missing (and shows what). */
async function submit(app, ui) {
  const missing = missingInputs(app);
  ui.clearMissing?.();
  if (missing.length) {
    for (const inp of missing) ui.markMissing?.(inp.id);
    const first = missing[0];
    toast(isMedia(first.type) ? t("ws.need", { label: first.label }) : t("ws.needtext", { label: first.label }), { error: true });
    return false;
  }
  const f = formFor(app);
  const n = Math.max(1, Math.min(4, f.count || 1));
  persist(app);
  try {
    for (let k = 0; k < n; k++) await feed.run(app.id, buildForm(app, { randomSeed: n > 1 }));
    toast(t("toast.started", { app: app.name }));
    return true;
  } catch (err) {
    toast(err.message, { error: true });
    return false;
  }
}

/** Open an app with one option already chosen (a card on the Explore page's effects wall). */
export function pickOption(app, inputId, value) {
  formFor(app).values[inputId] = value;
  persist(app);
  if (location.hash !== `#/app/${app.id}`) location.hash = `#/app/${app.id}`;
  else hooks.rerender?.();
}

/** Load a result's settings and input files into its app's form (and optionally run it again). */
export async function recreate(item, { run = false } = {}) {
  const app = byId.get(item.app);
  if (!app) return;
  const f = formFor(app);
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) continue;
    if (item.values?.[inp.id] !== undefined) f.values[inp.id] = item.values[inp.id];
    if (inp.type === "seed" && item.seed !== null && item.seed !== undefined) f.values[inp.id] = item.seed;
  }
  f.preset = item.preset || "";
  try {
    await Promise.all(item.inputs.map(async (i) => {
      const inp = app.inputs.find((x) => x.id === i.id);
      if (!inp || !i.file) return;
      const name = i.name || `${i.id}.${extOf(i.file) || "bin"}`;
      setFile(app, inp, await fileFromUrl(i.file, name));
    }));
  } catch (err) {
    toast(err.message, { error: true });
  }
  persist(app);
  if (run) wsTab = "history";
  if (location.hash !== `#/app/${app.id}`) location.hash = `#/app/${app.id}`;
  else hooks.rerender?.();
  if (run) await submit(app, {});
  else toast(t("toast.loaded", { app: app.name }));
}

// ------------------------------------------------------------------ small parts
function appThumb(a) {
  const ex = a.example;
  if (!ex) return el("span", { style: { display: "grid", placeItems: "center", width: "100%", height: "100%", color: "#55555c" } }, icon(iconOf(a)));
  const src = ex.type === "video" ? ex.poster : ex.card || ex.full;
  return el("img", { src, alt: "", loading: "lazy", class: ex.type === "audio" ? "contain" : null, style: ex.type === "audio" ? { objectFit: "contain" } : null });
}

function switcher(app) {
  const family = familyOf(app);
  return el("div", {},
    el("h4", {}, t("ws.change")),
    ...family.map((a) => el("button", { class: "opt", type: "button", "aria-selected": String(a.id === app.id),
      onclick: () => { closePopover(); location.hash = `#/app/${a.id}`; } },
      el("span", { class: "thumb" }, appThumb(a)),
      el("span", { class: "two" }, el("b", {}, a.name), el("small", {}, a.summary)),
      el("span", { class: "chk" }, icon("check")))),
    el("a", { class: "opt", href: "#/apps", onclick: closePopover }, icon("layers"), t("explore.seeall")));
}

function optionLabel(inp, v) {
  const o = (inp.options || []).find((x) => String(x.value) === String(v));
  return o ? o.label : String(v ?? "");
}

/** A select marked "gallery" (the effects picker): cards with each option's lab example, and the chosen one playing. */
function galleryField(app, inp, f, set, help) {
  const shots = app.example?.options?.[inp.id] || {};
  const val = el("span", { class: "v" }, optionLabel(inp, f.values[inp.id]));
  const now = el("div", { class: "fx-now" });
  const drawNow = () => {
    const shot = shots[String(f.values[inp.id])];
    now.hidden = !shot;
    now.replaceChildren(...(shot ? [optionThumb(shot, { play: "visible" })] : []));
  };
  drawNow();
  const row = el("button", { class: "selrow", type: "button", "aria-haspopup": "dialog", "aria-label": inp.label }, val, icon("chevD"));
  row.onclick = () => popover(row, el("div", {}, el("h4", {}, inp.label), el("div", { class: "fx-grid" }, ...(inp.options || []).map((o) =>
    optionTile(o, shots[String(o.value)], { selected: String(o.value) === String(f.values[inp.id]), flagKey: flags.key(app.id, inp.id, o.value),
      onPick: () => { set(o.value); val.textContent = o.label; drawNow(); closePopover(); } })))), { width: 640, cls: "wide" });
  return el("div", { class: "field" }, el("span", { class: "lbl" }, inp.label), row, now, help);
}

function rangeInput(inp, value, onChange) {
  const out = el("b", {}, String(value));
  const r = el("input", { type: "range", min: inp.min ?? 0, max: inp.max ?? 100, step: inp.step ?? 1, value: value, "aria-label": inp.label });
  const paint = () => r.style.setProperty("--p", `${((r.value - r.min) / (r.max - r.min || 1)) * 100}%`);
  paint();
  r.addEventListener("input", () => { out.textContent = r.value; paint(); onChange(Number(r.value)); });
  return el("div", { class: "range" }, el("div", { class: "top" }, el("span", {}, inp.label), out), r);
}

function seedEditor(app, inp, f, onChange) {
  const box = el("input", { type: "number", min: inp.min ?? 0, placeholder: t("ws.seed.random"), value: f.values[inp.id] === -1 ? "" : f.values[inp.id] ?? "" });
  box.addEventListener("input", () => { f.values[inp.id] = box.value === "" ? -1 : Math.trunc(Number(box.value)); onChange(); });
  const last = feed.list(app.id).find((e) => e.values?.[inp.id] !== undefined);
  return el("div", { class: "pad" },
    el("div", { class: "row" }, box,
      el("button", { class: "btn small ghost", type: "button", title: t("ws.seed.random"), onclick: () => { box.value = ""; f.values[inp.id] = -1; onChange(); } }, icon("dice"))),
    last ? el("button", { class: "btn small ghost", type: "button", onclick: () => { box.value = last.values[inp.id]; f.values[inp.id] = last.values[inp.id]; onChange(); } },
      `${t("ws.seed.reuse")} · ${last.values[inp.id]}`) : null,
    el("p", { class: "help" }, t("ws.seed.help")));
}

function genButton(app, onClick, { wide = false } = {}) {
  const est = estimate(app);
  const b = el("button", { class: `generate${wide ? " wide" : ""}`, type: "button", disabled: !app.runnable,
    title: !app.runnable ? (app.status === "draft" ? t("ws.draft") : t("ws.noworkflow")) : est ? t("ws.est", { gpu: est.gpu }) : null },
    t("ws.generate"), est ? el("span", { class: "cost" }, icon("spark"), fmtShort(est.seconds)) : el("span", { class: "cost" }, icon("spark")));
  b.addEventListener("click", async () => {
    if (b.dataset.busy) return;
    b.dataset.busy = "1";
    try { await onClick(); } finally { delete b.dataset.busy; }
  });
  return b;
}

function countControl(f) {
  const label = el("span", {});
  const minus = el("button", { type: "button", "aria-label": "−" }, "−");
  const plus = el("button", { type: "button", "aria-label": "+" }, "+");
  const draw = () => {
    label.replaceChildren(String(f.count), el("small", {}, "/4"));
    minus.disabled = f.count <= 1;
    plus.disabled = f.count >= 4;
  };
  minus.onclick = () => { f.count = Math.max(1, f.count - 1); draw(); };
  plus.onclick = () => { f.count = Math.min(4, f.count + 1); draw(); };
  draw();
  return el("div", { class: "count", title: t("ws.count") }, minus, label, plus);
}

// ------------------------------------------------------------------ composer layout
function composerBar(app, rerenderBar) {
  const f = formFor(app);
  const pi = promptInput(app);
  const mediaInputs = app.inputs.filter((i) => isMedia(i.type));
  const pickers = Object.fromEntries(mediaInputs.map((inp) => {
    const input = el("input", { type: "file", accept: ACCEPT[inp.type], hidden: true });
    input.addEventListener("change", () => { if (input.files[0] && setFile(app, inp, input.files[0])) rerenderBar(); input.value = ""; });
    return [inp.id, input];
  }));
  const pick = (inp) => pickers[inp.id].click();
  const hint = el("div", { class: "cmp-hint", hidden: true });

  const prompt = pi ? el("textarea", { class: "cmp-prompt", rows: "2", "aria-label": pi.label,
    // an optional prompt (a template app's "Extra direction") says so instead of asking for a scene
    placeholder: pi.default ? t("ws.eg", { x: pi.default }) : pi.required ? t("ws.prompt.ph") : t("ws.prompt.opt", { label: pi.label }), value: f.values[pi.id] ?? "" }) : null;
  const grow = () => { if (!prompt) return; prompt.style.height = "auto"; prompt.style.height = `${Math.min(220, prompt.scrollHeight)}px`; };
  if (prompt) {
    prompt.addEventListener("input", () => { f.values[pi.id] = prompt.value; grow(); prompt.classList.remove("missing"); persistSoon(); });
    prompt.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); go(); } });
    requestAnimationFrame(grow);
  }

  const attach = el("div", { class: "cmp-attach" }, ...mediaInputs.map((inp) => {
    const x = f.files[inp.id];
    if (!x) {
      return el("button", { class: "att need", type: "button", title: `${t("ws.add", { what: inp.label })}${inp.required ? "" : ` (${t("ws.optional")})`}`,
        "aria-label": t("ws.add", { what: inp.label }), dataset: { slot: inp.id }, onclick: () => pick(inp) }, icon(inp.type === "image" ? "image" : inp.type));
    }
    const m = inp.type === "image" ? el("img", { src: x.url, alt: "" }) : inp.type === "video" ? el("video", { src: `${x.url}#t=0.1`, muted: true, preload: "metadata" }) : el("span", { style: { display: "grid", placeItems: "center", height: "100%" } }, icon("audio"));
    return el("div", { class: "att", title: x.file.name },
      m, el("span", { class: "lbl" }, inp.label),
      el("button", { class: "x", type: "button", "aria-label": t("ws.remove"), onclick: () => { clearFile(app, inp.id); rerenderBar(); } }, icon("x")));
  }));

  const chips = [];
  if (mediaInputs.length) {
    chips.push(el("button", { class: "chip square", type: "button", title: t("ws.add", { what: mediaInputs[0].label }), "aria-label": t("ws.add", { what: mediaInputs[0].label }),
      onclick: (ev) => {
        const empty = mediaInputs.filter((i) => !f.files[i.id]);
        if (mediaInputs.length === 1 || empty.length === 1) return pick(empty[0] || mediaInputs[0]);
        popover(ev.currentTarget, el("div", {}, ...mediaInputs.map((inp) => el("button", { class: "opt", type: "button", onclick: () => { closePopover(); pick(inp); } },
          icon(inp.type === "image" ? "image" : inp.type), inp.label))));
      } }, icon("plus")));
  }
  const model = el("button", { class: "chip model", type: "button", "aria-haspopup": "dialog",
    onclick: (ev) => popover(ev.currentTarget, switcher(app), { width: 360 }) },
    el("span", { class: "thumb" }, appThumb(app)), el("span", { class: "v" }, app.name), icon("chevD"));
  chips.push(model);

  for (const inp of app.inputs) {
    if (isMedia(inp.type) || inp === pi) continue;
    chips.push(chipFor(app, inp, f));
  }
  if (app.presets?.length) {
    const presetChip = el("button", { class: `chip${f.preset ? " filled" : ""}`, type: "button" }, el("span", { class: "k" }, t("ws.preset")),
      el("span", { class: "v" }, f.preset ? app.presets.find((p) => p.id === f.preset)?.label : t("ws.preset.none")));
    presetChip.onclick = (ev) => popover(ev.currentTarget, el("div", {}, el("h4", {}, t("ws.preset")),
      ...[{ id: "", label: t("ws.preset.none") }, ...app.presets].map((p) => el("button", { class: "opt", type: "button", "aria-selected": String(f.preset === p.id),
        onclick: () => { f.preset = p.id; persist(app); closePopover(); rerenderBar(); } }, p.label, el("span", { class: "chk" }, icon("check"))))));
    chips.push(presetChip);
  }

  const ui = {
    clearMissing: () => { prompt?.classList.remove("missing"); attach.querySelectorAll(".missing").forEach((n) => n.classList.remove("missing")); },
    markMissing: (id) => {
      if (pi && id === pi.id) { prompt.classList.add("missing"); prompt.focus(); }
      attach.querySelector(`[data-slot="${id}"]`)?.classList.add("missing");
    },
  };
  const go = async () => { if (await submit(app, ui) && wsTab !== "history") { wsTab = "history"; hooks.rerender?.(); } };
  const gen = genButton(app, go);
  if (!app.runnable) { hint.hidden = false; hint.textContent = app.status === "draft" ? t("ws.draft") : t("ws.noworkflow"); }

  const bar = el("div", { class: "composer" },
    hint,
    el("div", { class: "cmp-top" }, attach, prompt || el("div", { class: "cmp-prompt dim", style: { paddingTop: "16px" } }, app.summary)),
    el("div", { class: "cmp-row" }, ...chips, el("span", { class: "grow" }), countControl(f), gen),
    ...Object.values(pickers));
  return bar;
}

let persistTimer = null;
function persistSoon() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => { for (const id of forms.keys()) { const a = byId.get(id); if (a) persist(a); } }, 400);
}

function chipFor(app, inp, f) {
  const set = (v) => { f.values[inp.id] = v; persistSoon(); };
  if (inp.type === "toggle") {
    const b = el("button", { class: `chip${f.values[inp.id] ? " on" : ""}`, type: "button", "aria-pressed": String(Boolean(f.values[inp.id])), title: inp.help || inp.label },
      icon(/enhance|reprompt/.test(inp.id) ? "wand" : "check"), inp.label);
    b.onclick = () => { set(!f.values[inp.id]); b.classList.toggle("on", Boolean(f.values[inp.id])); b.setAttribute("aria-pressed", String(Boolean(f.values[inp.id]))); };
    return b;
  }
  const v = el("span", { class: "v" });
  const b = el("button", { class: "chip", type: "button", "aria-haspopup": "dialog", title: inp.help || inp.label },
    inp.type === "seed" ? icon("dice") : el("span", { class: "k" }, inp.label), v);
  const draw = () => {
    const val = f.values[inp.id];
    if (inp.type === "select") v.textContent = optionLabel(inp, val);
    else if (inp.type === "seed") v.textContent = val === -1 || val === "" ? t("ws.seed.random") : String(val);
    else if (inp.type === "textarea" || inp.type === "text") { v.textContent = String(val || "").trim() ? "✓" : "—"; b.classList.toggle("filled", Boolean(String(val || "").trim())); }
    else v.textContent = String(val);
  };
  draw();
  b.onclick = (ev) => {
    let content;
    if (inp.type === "select") {
      content = el("div", {}, el("h4", {}, inp.label), ...(inp.options || []).map((o) => el("button", { class: "opt", type: "button",
        "aria-selected": String(String(o.value) === String(f.values[inp.id])), onclick: () => { set(o.value); draw(); closePopover(); } },
        o.label, el("span", { class: "chk" }, icon("check")))));
    } else if (inp.type === "slider") {
      content = el("div", { class: "pad" }, rangeInput(inp, f.values[inp.id], (n) => { set(n); draw(); }), inp.help ? el("p", { class: "help" }, inp.help) : null);
    } else if (inp.type === "seed") {
      content = seedEditor(app, inp, f, () => { persistSoon(); draw(); });
    } else if (inp.type === "textarea") {
      const ta = el("textarea", { placeholder: inp.default ? t("ws.eg", { x: inp.default }) : inp.label, value: f.values[inp.id] ?? "" });
      ta.addEventListener("input", () => { set(ta.value); draw(); });
      content = el("div", { class: "pad" }, el("b", {}, inp.label), ta, inp.help ? el("p", { class: "help" }, inp.help) : null);
    } else {
      const box = el("input", { type: inp.type === "number" ? "number" : "text", min: inp.min, max: inp.max, step: inp.step, value: f.values[inp.id] ?? "",
        placeholder: inp.default !== undefined ? String(inp.default) : "" });
      box.addEventListener("input", () => { set(inp.type === "number" ? (box.value === "" ? "" : Number(box.value)) : box.value); draw(); });
      content = el("div", { class: "pad" }, el("b", {}, inp.label), box, inp.help ? el("p", { class: "help" }, inp.help) : null);
    }
    popover(ev.currentTarget, content, { width: inp.type === "textarea" ? 360 : undefined });
  };
  return b;
}

// ------------------------------------------------------------------ sidebar layout
function dropzone(app, inp, rerender) {
  const f = formFor(app);
  const x = f.files[inp.id];
  const input = el("input", { type: "file", accept: ACCEPT[inp.type], hidden: true });
  input.addEventListener("change", () => { if (input.files[0] && setFile(app, inp, input.files[0])) rerender(); input.value = ""; });
  const limits = [inp.limits?.max_mb ? t("ws.drop.mb", { mb: inp.limits.max_mb }) : "", inp.limits?.seconds ? t("ws.drop.seconds", { a: inp.limits.seconds[0], b: inp.limits.seconds[1] }) : ""].filter(Boolean).join(" · ");
  let zone;
  if (!x) {
    zone = el("div", { class: "drop", role: "button", tabindex: "0", dataset: { slot: inp.id }, "aria-label": t("ws.add", { what: inp.label }),
      onclick: () => input.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } } },
      el("span", { class: "ic" }, icon(inp.type === "image" ? "image" : inp.type === "video" ? "video" : "audio")),
      el("b", {}, inp.label, inp.required ? "" : el("span", { class: "faint", style: { fontWeight: 500 } }, ` · ${t("ws.optional")}`)),
      el("small", {}, inp.help || t(`ws.drop.${inp.type}`)),
      el("small", { class: "faint" }, [t("ws.drop.hint"), limits].filter(Boolean).join(" · ")),
      input);
  } else {
    const media = inp.type === "image" ? el("img", { src: x.url, alt: "" })
      : inp.type === "video" ? el("video", { src: x.url, muted: true, loop: true, playsinline: true, autoplay: true, preload: "auto" })
        : el("audio", { src: x.url, controls: true, preload: "metadata" });
    if (inp.type === "video") media.muted = true;
    const warn = el("span", { class: "fname" }, x.file.name);
    if (inp.type === "video" && inp.limits?.seconds) {
      media.addEventListener("loadedmetadata", () => {
        const [a, b] = inp.limits.seconds;
        if (media.duration < a || media.duration > b) { warn.textContent = `${x.file.name} · ${media.duration.toFixed(1)} s (${a}–${b} s)`; warn.style.color = "var(--warn)"; }
      });
    }
    zone = el("div", { class: "drop has", dataset: { slot: inp.id } }, media, warn,
      el("div", { class: "bar2" },
        el("button", { class: "mini", type: "button", title: t("ws.replace"), "aria-label": t("ws.replace"), onclick: () => input.click() }, icon("swap")),
        el("button", { class: "mini", type: "button", title: t("ws.remove"), "aria-label": t("ws.remove"), onclick: () => { clearFile(app, inp.id); rerender(); } }, icon("x"))),
      input);
  }
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    zone.classList.remove("over");
    const file = e.dataTransfer.files[0];
    if (file && setFile(app, inp, file)) rerender();
  });
  return zone;
}

function sideField(app, inp, f, ui) {
  const set = (v) => { f.values[inp.id] = v; persistSoon(); };
  const help = inp.help ? el("p", { class: "help" }, inp.help) : null;
  if (inp.type === "textarea") {
    const ta = el("textarea", { class: inp.required ? "" : "short", placeholder: inp.default ? t("ws.eg", { x: inp.default }) : inp.label, value: f.values[inp.id] ?? "", "aria-label": inp.label });
    ta.addEventListener("input", () => { set(ta.value); ta.classList.remove("missing"); });
    ui.refs[inp.id] = ta;
    return el("label", { class: "field" }, el("span", { class: "lbl" }, inp.label, inp.required ? null : el("small", {}, t("ws.optional"))), ta, help);
  }
  if (inp.type === "select" && inp.gallery) return galleryField(app, inp, f, set, help);
  if (inp.type === "select") {
    const opts = inp.options || [];
    const short = opts.length <= 4 && opts.every((o) => String(o.label).length <= 12);
    if (short) {
      const seg = el("div", { class: "seg", role: "group", "aria-label": inp.label });
      const draw = () => seg.replaceChildren(...opts.map((o) => el("button", { type: "button", "aria-pressed": String(String(o.value) === String(f.values[inp.id])),
        onclick: () => { set(o.value); draw(); } }, o.label)));
      draw();
      return el("div", { class: "field" }, el("span", { class: "lbl" }, inp.label), seg, help);
    }
    const val = el("span", { class: "v" }, optionLabel(inp, f.values[inp.id]));
    const row = el("button", { class: "selrow", type: "button", "aria-haspopup": "dialog", "aria-label": inp.label }, val, icon("chevD"));
    row.onclick = () => popover(row, el("div", {}, el("h4", {}, inp.label), ...opts.map((o) => el("button", { class: "opt", type: "button",
      "aria-selected": String(String(o.value) === String(f.values[inp.id])), onclick: () => { set(o.value); val.textContent = o.label; closePopover(); } },
      o.label, el("span", { class: "chk" }, icon("check"))))), { width: Math.max(260, row.offsetWidth) });
    return el("div", { class: "field" }, el("span", { class: "lbl" }, inp.label), row, help);
  }
  if (inp.type === "slider") return el("div", { class: "field" }, rangeInput(inp, f.values[inp.id], set), help);
  if (inp.type === "toggle") {
    const box = el("input", { type: "checkbox", checked: Boolean(f.values[inp.id]), "aria-label": inp.label });
    box.addEventListener("change", () => set(box.checked));
    return el("label", { class: "field" }, el("span", { class: "togrow" }, el("span", { class: "t" }, el("b", { style: { fontSize: "13px" } }, inp.label),
      inp.help ? el("small", {}, inp.help) : null), el("span", { class: "switch" }, box, el("i"))));
  }
  if (inp.type === "seed") {
    const box = el("input", { type: "number", min: inp.min ?? 0, placeholder: t("ws.seed.random"), value: f.values[inp.id] === -1 ? "" : f.values[inp.id] ?? "", "aria-label": inp.label });
    box.addEventListener("input", () => set(box.value === "" ? -1 : Math.trunc(Number(box.value))));
    return el("label", { class: "field" }, el("span", { class: "lbl" }, inp.label || t("ws.seed"),
      el("button", { class: "mini", type: "button", title: t("ws.seed.random"), style: { width: "26px", height: "26px" }, onclick: (e) => { e.preventDefault(); box.value = ""; set(-1); } }, icon("dice"))),
      box, el("p", { class: "help" }, t("ws.seed.help")));
  }
  const box = el("input", { type: inp.type === "number" ? "number" : "text", min: inp.min, max: inp.max, step: inp.step, value: f.values[inp.id] ?? "",
    placeholder: inp.default !== undefined ? String(inp.default) : "", "aria-label": inp.label });
  box.addEventListener("input", () => set(inp.type === "number" ? (box.value === "" ? "" : Number(box.value)) : box.value));
  return el("label", { class: "field" }, el("span", { class: "lbl" }, inp.label, inp.required ? null : el("small", {}, t("ws.optional"))), box, help);
}

const isAdvanced = (inp) => inp.type === "seed" || /negative/.test(inp.id);

function presetField(app, f) {
  const opts = [{ id: "", label: t("ws.preset.none") }, ...app.presets];
  const seg = el("div", { class: "seg", role: "group", "aria-label": t("ws.preset") });
  const draw = () => seg.replaceChildren(...opts.map((p) => el("button", { type: "button", "aria-pressed": String(p.id === f.preset),
    onclick: () => { f.preset = p.id; persist(app); draw(); } }, p.label)));
  draw();
  return el("div", { class: "field" }, el("span", { class: "lbl" }, t("ws.preset")), seg);
}

function sidebarPanel(app, rerenderSide) {
  const f = formFor(app);
  const ui = { refs: {} };
  const tab = videoTabOf(app.id);
  const tabs = tab ? el("div", { class: "side-tabs", role: "tablist" }, ...VIDEO_TABS.map((vt) => el("button", { type: "button", role: "tab",
    "aria-selected": String(vt.id === tab),
    onclick: () => {
      if (vt.id === tab) return;
      const last = store.get(`last.vtab.${vt.id}`);
      const target = vt.apps.includes(last) && byId.has(last) ? last : vt.apps.find((id) => byId.has(id));
      if (target) location.hash = `#/app/${target}`;
    } }, t(`vtab.${vt.id}`)))) : null;

  const card = el("div", { class: "model-card", role: "button", tabindex: "0", "aria-label": `${t("ws.change")}: ${app.name}` });
  const ex = exampleItem(app);
  const cardMedia = thumb(ex, { play: "visible" });
  card.append(cardMedia, el("div", { class: "txt" }, el("h3", { class: "display" }, app.name), el("p", {}, tagline(app))));
  const change = el("button", { class: "change", type: "button" }, icon("swap"), t("ws.change"));
  const openSwitch = (ev) => { ev.stopPropagation(); popover(change, switcher(app), { width: 340 }); };
  change.onclick = openSwitch;
  card.onclick = openSwitch;
  card.onkeydown = (e) => { if (e.key === "Enter") openSwitch(e); };
  card.append(change);

  const main = [], adv = [];
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) main.push(dropzone(app, inp, rerenderSide));
    else (isAdvanced(inp) ? adv : main).push(sideField(app, inp, f, ui));
  }
  if (app.presets?.length) adv.unshift(presetField(app, f));
  const advanced = adv.length ? el("details", { class: "adv" }, el("summary", {}, t("ws.advanced"), icon("chevD", "i-chev")), el("div", { class: "in" }, ...adv)) : null;

  const scroll = el("div", { class: "side-scroll" }, card, ...main, advanced);
  const note = el("p", { class: "side-note" }, !app.runnable ? (app.status === "draft" ? t("ws.draft") : t("ws.noworkflow")) : "");
  ui.clearMissing = () => { scroll.querySelectorAll(".missing").forEach((n) => n.classList.remove("missing")); };
  ui.markMissing = (id) => {
    const n = ui.refs[id] || scroll.querySelector(`[data-slot="${id}"]`);
    if (!n) return;
    n.classList.add("missing");
    n.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  const go = async () => { if (await submit(app, ui) && wsTab !== "history") { wsTab = "history"; hooks.rerender?.(); } };
  const foot = el("div", { class: "side-foot" }, el("div", { class: "row" }, countControl(f), genButton(app, go)), note);
  const side = el("aside", { class: "side", "aria-label": app.name }, tabs, scroll, foot);
  side.addEventListener("dragover", (e) => e.preventDefault());
  side.addEventListener("drop", (e) => { e.preventDefault(); if (assignFiles(app, e.dataTransfer.files)) rerenderSide(); });
  return side;
}

// ------------------------------------------------------------------ main area: history, library, how it works
let wsTab = "history";
let dense = store.get("dense", false);

function relatedExamples(app) {
  const cat = categoryOf(app.id);
  const same = (CATEGORIES.find((c) => c.id === cat)?.apps || []).filter((id) => id !== app.id).map((id) => byId.get(id)).filter((a) => a?.example);
  const rest = apps.filter((a) => a.example && a.id !== app.id && !same.includes(a) && a.section === app.section);
  return [...same, ...rest].slice(0, 12);
}

function exampleTiles(list, { onPick } = {}) {
  return list.map((a) => {
    const item = exampleItem(a);
    const m = thumb(item, { play: "visible" });
    const node = el("div", { class: "m-item", role: "button", tabindex: "0", onclick: () => onPick?.(a), onkeydown: (e) => { if (e.key === "Enter") onPick?.(a); } },
      m, el("div", { class: "cap" }, el("span", {}, a.name), icon("chevR")));
    return node;
  });
}

function heroFlow(app) {
  const item = exampleItem(app);
  if (!item) return null;
  const ins = item.inputs.slice(0, 2).map((i) => el("div", { class: "media" }, i.thumb ? el("img", { src: i.thumb, alt: i.label, title: i.label }) : el("span", { class: "typeicon" }, icon(i.type || "image"))));
  return el("div", { class: "flow" },
    ins.length ? el("div", { class: "ins" }, ...ins) : null,
    ins.length ? el("span", { class: "arrow" }, icon("chevR")) : null,
    el("div", { class: "out" }, thumb(item, { play: "visible", useFull: item.type === "video" })));
}

function emptyFor(app, layout) {
  const item = exampleItem(app);
  const load = () => item && recreate(item);
  if (layout === "composer") {
    return el("div", { class: "feed-empty" }, el("div", {},
      el("div", { class: "glass" }, icon(iconOf(app))),
      el("h2", { class: "display" }, t("ws.create.title"), el("span", {}, app.name)),
      el("p", {}, app.summary),
      item ? el("button", { class: "ex", type: "button", onclick: load }, thumb(item, { play: "visible" }),
        el("span", {}, el("b", {}, t("ws.example")), el("small", {}, t("ws.useex")))) : null));
  }
  const related = relatedExamples(app);
  const grid = el("div");
  if (related.length) masonry(grid, exampleTiles(related, { onPick: (a) => { location.hash = `#/app/${a.id}`; } }), { min: 230 });
  return el("div", { style: { display: "grid", gap: "8px" } },
    el("section", { class: "ws-hero" },
      el("div", {}, el("h1", { class: "display" }, tagline(app)), el("p", {}, app.summary),
        el("div", { class: "row" },
          item ? el("button", { class: "btn lime", type: "button", onclick: load }, icon("redo"), t("ws.useex")) : null,
          el("button", { class: "btn ghost", type: "button", onclick: () => { wsTab = "how"; hooks.rerender?.(); } }, icon("info"), t("ws.how")))),
      heroFlow(app)),
    related.length ? el("div", { class: "sec-head" }, el("div", {}, el("h2", { class: "display" }, t("ws.related")))) : null,
    grid);
}

function valueRows(app, values) {
  const labels = Object.fromEntries(app.inputs.map((i) => [i.id, i]));
  const pi = promptInput(app);
  return Object.entries(values || {}).filter(([k, v]) => labels[k] && labels[k] !== pi && labels[k].type !== "seed" && v !== "" && v !== null && v !== undefined)
    .flatMap(([k, v]) => [el("dt", {}, labels[k].label), el("dd", {}, labels[k].type === "select" ? optionLabel(labels[k], v) : labels[k].type === "toggle" ? (v === true || v === "true" ? "✓" : "—") : String(v))]);
}

function libraryTab(app) {
  const item = exampleItem(app);
  const wrap = el("div", { style: { display: "grid", gap: "8px" } });
  if (item) {
    const pi = promptInput(app);
    const prompt = pi ? item.values?.[pi.id] : null;
    wrap.append(el("section", { class: "ex-big" },
      el("div", { class: "stage" }, fullMedia(item.type, item.full, { poster: item.poster, autoplay: false })),
      el("div", { class: "side2" },
        el("div", {}, el("span", { class: "tag ghost" }, t("ws.example")), el("h2", { class: "display", style: { margin: "10px 0 0", fontSize: "26px" } }, app.name)),
        prompt ? el("div", { class: "prompt", style: { padding: "12px", borderRadius: "12px", background: "#1b1b1e", fontSize: "13.5px" } }, prompt) : null,
        item.inputs.length ? el("div", { class: "ins-row" }, ...item.inputs.map((i) => el("figure", {},
          el("div", { class: "media" }, i.thumb ? el("img", { src: i.thumb, alt: "" }) : el("span", { class: "typeicon" }, icon(i.type || "image"))), el("figcaption", {}, i.label)))) : null,
        el("dl", { class: "vals" }, ...valueRows(app, item.values)),
        el("div", { class: "statline" },
          item.seconds ? el("span", {}, icon("clock"), fmtSeconds(item.seconds)) : null,
          item.gpu ? el("span", {}, icon("chip"), item.gpu.split(",")[0]) : null,
          item.peak ? el("span", {}, t("view.peak", { gb: item.peak })) : null,
          item.seed !== null && item.seed !== undefined ? el("span", {}, icon("dice"), item.seed) : null),
        el("div", { class: "row", style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
          el("button", { class: "btn lime", type: "button", onclick: () => recreate(item) }, icon("redo"), t("ws.useex")),
          el("button", { class: "btn ghost", type: "button", onclick: () => hooks.compare?.(item) }, icon("compare"), t("act.compare")),
          flagButton(flags.key(app.id))))));
  }
  const related = relatedExamples(app);
  if (related.length) {
    const grid = el("div");
    masonry(grid, exampleTiles(related, { onPick: (a) => { location.hash = `#/app/${a.id}`; } }), { min: 230 });
    wrap.append(el("div", { class: "sec-head" }, el("h2", { class: "display" }, t("ws.related"))), grid);
  }
  if (!item && !related.length) wrap.append(el("div", { class: "empty" }, t("explore.noex")));
  return wrap;
}

function vramBars(app) {
  const v = app.vram;
  if (!v) return null;
  const peak = app.example?.peak_vram_gb ?? null;
  const max = Math.max(48, v.whole_gb, peak || 0) * 1.05;
  const pct = (gb) => `${Math.min(100, (gb / max) * 100)}%`;
  const ticks = [24, 48].map((g) => el("u", { style: { left: pct(g) }, title: `${g} GB` }));
  const row = (label, gb, cls) => el("div", { style: { display: "grid", gap: "6px" } },
    el("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "12.5px" } }, el("span", { class: "dim" }, label), el("b", {}, `${gb} GB`)),
    el("div", { class: "vbar" }, el("i", { class: cls, style: { width: pct(gb) } }), ...ticks));
  const fit = fitOf(app);
  return el("div", { class: "card" }, el("h3", {}, icon("chip"), t("how.vram"), fit ? el("span", { class: `fit ${fit[1]}`, style: { marginLeft: "auto" } }, t(fit[0])) : null),
    row(t("how.whole"), v.whole_gb, "whole"), row(t("how.phase"), v.largest_phase_gb, ""),
    peak ? row(`${t("how.measured")} (${(app.example.gpu || "").split(",")[0]})`, peak, "whole") : null,
    el("div", { class: "vscale" }, el("span", { style: { left: pct(24) } }, "24 GB"), el("span", { style: { left: pct(48) } }, "48 GB")));
}

function cliLine(app) {
  const parts = ["npm run app --", app.id];
  for (const inp of app.inputs) {
    if (isMedia(inp.type)) { if (inp.required) parts.push(`--file ${inp.id}=my-${inp.type}.${inp.type === "image" ? "jpg" : inp.type === "video" ? "mp4" : "mp3"}`); continue; }
    if (inp.required && inp.type === "textarea") parts.push(`--set ${inp.id}="${String(inp.default || "…").slice(0, 40)}"`);
  }
  return parts.join(" ");
}

function howTab(app) {
  const total = app.models.filter((m) => !m.optional).reduce((s, m) => s + m.gb, 0);
  return el("div", { class: "how-grid" },
    el("div", { class: "card" }, el("h3", {}, icon("layers"), t("how.pipeline")), el("p", {}, t("how.pipeline.d", { id: app.id })),
      el("div", { class: "statline" }, el("span", {}, `${t("how.pack")}: ${app.pack}`), el("span", {}, app.status === "ready" ? "ready" : t("tag.draft")),
        app.higgsfield_feature ? el("span", {}, `${t("how.equiv")}: ${app.higgsfield_feature}`) : null),
      el("p", {}, t("how.download")), el("pre", { class: "code" }, `modal run infra/modal_app.py::download --pack ${app.pack}`),
      el("p", {}, t("how.cli")), el("pre", { class: "code" }, cliLine(app))),
    app.models.length ? el("div", { class: "card" }, el("h3", {}, icon("box"), t("how.models"), el("span", { class: "dim", style: { marginLeft: "auto", fontWeight: 500 } }, t("how.total", { gb: total.toFixed(1) }))),
      el("table", { class: "models" }, el("tbody", {}, ...app.models.map((m) => el("tr", {},
        el("td", {}, el("div", {}, m.name), el("small", { class: "dim" }, [m.repo, m.license, m.gated ? t("how.gated") : "", m.optional ? t("how.optional") : ""].filter(Boolean).join(" · "))),
        el("td", { class: "r" }, `${m.gb} GB`)))))) : null,
    vramBars(app),
    app.notes || app.credits?.length ? el("div", { class: "card" },
      app.notes ? el("h3", {}, icon("info"), t("how.notes")) : null, app.notes ? el("p", {}, app.notes) : null,
      app.credits?.length ? el("h3", {}, t("how.credits")) : null, app.credits?.length ? el("p", {}, app.credits.join(" · ")) : null) : null);
}

function mainArea(app, layout, disposers) {
  const body = el("div", { class: "ws-body", style: { display: "flex", flexDirection: "column", flex: "1", minHeight: "0" } });
  const tabs = el("div", { class: "tabs", role: "tablist" });
  const denseBtn = el("button", { class: "icon-btn", type: "button", title: t("ws.dense"), "aria-label": t("ws.dense"), "aria-pressed": String(dense) });
  let disposeBody = null;
  const draw = () => {
    tabs.replaceChildren(...[["history", "clock"], ["library", "film"], ["how", "info"]].map(([id, ic]) => el("button", { type: "button", role: "tab",
      "aria-selected": String(wsTab === id), onclick: () => { wsTab = id; draw(); } }, icon(ic), t(`ws.${id}`))));
    denseBtn.replaceChildren(icon(dense ? "rows" : "grid"));
    denseBtn.hidden = wsTab !== "history";
    disposeBody?.();
    disposeBody = null;
    if (wsTab === "history") disposeBody = feedView(body, { app: app.id, empty: () => emptyFor(app, layout), dense });
    else body.replaceChildren(wsTab === "library" ? libraryTab(app) : howTab(app));
  };
  denseBtn.onclick = () => { dense = !dense; store.set("dense", dense); denseBtn.setAttribute("aria-pressed", String(dense)); draw(); };
  draw();
  disposers.push(() => disposeBody?.());
  return el("section", { class: "ws-main" }, el("div", { class: "ws-top" }, tabs, el("div", { class: "right" }, denseBtn)), body);
}

// ------------------------------------------------------------------ the view
export function workspaceView(appId) {
  const app = byId.get(appId);
  if (!app) return { node: el("div", { class: "page" }, el("div", { class: "empty" }, `${appId}?`)), active: "apps" };
  rememberApp(app);
  const vt = videoTabOf(app.id);
  if (vt) store.set(`last.vtab.${vt}`, app.id);
  const layout = layoutOf(app);
  const disposers = [];
  const root = el("div", { class: `ws l-${layout}` });

  if (layout === "composer") {
    let bar = null;
    const drawBar = () => { const next = composerBar(app, drawBar); bar ? bar.replaceWith(next) : null; bar = next; if (!bar.isConnected) root.append(bar); };
    root.append(mainArea(app, layout, disposers));
    drawBar();
    // drop files anywhere on the page
    const over = (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); bar.classList.add("drag"); } };
    const leave = (e) => { if (!e.relatedTarget) bar.classList.remove("drag"); };
    const drop = (e) => { if (!e.dataTransfer?.files?.length) return; e.preventDefault(); bar.classList.remove("drag"); if (assignFiles(app, e.dataTransfer.files)) drawBar(); };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    disposers.push(() => { window.removeEventListener("dragover", over); window.removeEventListener("dragleave", leave); window.removeEventListener("drop", drop); });
    disposers.push(() => bar?.remove());
    const paste = (e) => { const files = [...(e.clipboardData?.files || [])]; if (files.length && assignFiles(app, files)) { e.preventDefault(); drawBar(); } };
    document.addEventListener("paste", paste);
    disposers.push(() => document.removeEventListener("paste", paste));
  } else {
    let side = null;
    const drawSide = () => {
      const scrollTop = side?.querySelector(".side-scroll")?.scrollTop || 0;
      const next = sidebarPanel(app, drawSide);
      if (side) side.replaceWith(next); else root.prepend(next);
      side = next;
      side.querySelector(".side-scroll").scrollTop = scrollTop;
    };
    root.append(mainArea(app, layout, disposers));
    drawSide();
    const paste = (e) => { const files = [...(e.clipboardData?.files || [])]; if (files.length && assignFiles(app, files)) { e.preventDefault(); drawSide(); } };
    document.addEventListener("paste", paste);
    disposers.push(() => document.removeEventListener("paste", paste));
  }
  return { node: root, dispose: () => disposers.forEach((d) => d()), app };
}

/** For the viewer's "Recreate" and the feed's "Try again". */
export function setTab(tab) { wsTab = tab; }
export { submit as submitApp, hoverPlay, playWhenVisible };

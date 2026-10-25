// The top bar: studios (with a menu of their apps on hover, menu.js), featured apps, the VRAM map, language, and the GPU pill that tells
// whether the backend is warm (and wakes it on request; looking never starts it).
import { el, icon, logoMark, api, popover, closePopover, toast, live } from "./util.js";
import { t, lang, LANGS, setLang } from "./i18n.js";
import { byId, FEATURED } from "./catalog.js";
import { attachMenus } from "./menu.js";

export const gpuState = { data: null, listeners: new Set() };
let pollTimer = null;

async function pollGpu() {
  clearTimeout(pollTimer);
  try {
    gpuState.data = await api("/api/gpu");
  } catch {
    gpuState.data = null;
  }
  live.gpuWarm = Boolean(gpuState.data?.warm);
  for (const fn of gpuState.listeners) fn(gpuState.data);
  const busy = gpuState.data?.waking || gpuState.data?.running;
  pollTimer = setTimeout(pollGpu, busy ? 3000 : 15000);
}

function gpuPill() {
  const dot = el("span", { class: "dot" });
  const label = el("span", {});
  const pill = el("button", { class: "gpu", type: "button", "aria-haspopup": "dialog" }, dot, label);
  const draw = (g) => {
    pill.className = "gpu";
    if (!g) { label.textContent = "…"; return; }
    if (!g.configured) { pill.classList.add("off"); label.textContent = t("gpu.none"); }
    else if (g.waking?.error) { pill.classList.add("error"); label.textContent = t("gpu.failed"); }
    else if (g.waking) { pill.classList.add("waking"); label.textContent = t("gpu.waking", { s: g.waking.seconds }); }
    else if (g.warm) { pill.classList.add("warm"); label.textContent = t("gpu.ready"); }
    else label.textContent = t("gpu.asleep");
  };
  gpuState.listeners.add(draw);
  draw(gpuState.data);
  pill.onclick = async () => {
    // VRAM in use is asked for only now, and the server only asks a backend that is already warm
    if (gpuState.data?.warm) {
      try { gpuState.data = await api("/api/gpu?device=1"); draw(gpuState.data); } catch { /* keep what we had */ }
    }
    const g = gpuState.data;
    const wake = el("button", { class: "btn lime small", type: "button", onclick: async () => {
      try { gpuState.data = await api("/api/gpu/wake", { method: "POST" }); draw(gpuState.data); pollGpu(); closePopover(); }
      catch (err) { toast(err.message, { error: true }); }
    } }, icon("bolt"), t("gpu.pop.wake"));
    const lines = [];
    if (!g?.configured) lines.push(el("p", { class: "help" }, t("gpu.pop.none")));
    else {
      lines.push(el("p", { class: "help" }, `${t("gpu.pop.backend")}: ${g.host}`));
      if (g.waking?.error) lines.push(el("p", { class: "help", style: { color: "var(--bad)" } }, g.waking.error), wake);
      else if (g.waking) lines.push(el("p", { class: "help" }, t("gpu.pop.waking")));
      else if (g.warm) {
        lines.push(el("p", { class: "help" }, t("gpu.pop.ready")));
        if (g.device?.vram_total_gb) {
          lines.push(el("div", { style: { display: "grid", gap: "6px" } },
            el("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "12.5px" } }, el("span", { class: "dim" }, `${t("gpu.pop.vram")} · ${g.device.name || "GPU"}`),
              el("b", {}, `${g.device.vram_used_gb} / ${g.device.vram_total_gb} GB`)),
            el("div", { class: "vbar" }, el("i", { style: { width: `${(g.device.vram_used_gb / g.device.vram_total_gb) * 100}%` } }))));
        }
        if (g.device?.app) lines.push(el("p", { class: "help" }, `${t("gpu.pop.loaded")}: ${byId.get(g.device.app)?.name ?? g.device.app}`));
      } else lines.push(el("p", { class: "help" }, t("gpu.pop.asleep")), wake);
      if (g.running) lines.push(el("p", { class: "help" }, t("gpu.pop.running", { n: g.running })));
      if (g.demo?.max_runs_per_day) lines.push(el("p", { class: "help" }, t("gpu.pop.demo", { n: g.demo.runs_left, max: g.demo.max_runs_per_day })));
    }
    popover(pill, el("div", { class: "pad", style: { width: "300px" } }, ...lines), { align: "end" });
  };
  return pill;
}

/** Build the bar once; update() marks the current page. */
export function topbar({ onLang }) {
  gpuState.listeners.clear();   // a rebuilt bar (language change) replaces the old pill
  const items = [
    ["explore", "#/", "compass"], ["image", "#/image", "image"], ["video", "#/video", "video"], ["audio", "#/audio", "audio"],
    ["apps", "#/apps", "layers"], ["library", "#/library", "film"],
  ];
  const links = new Map();
  const nav = el("nav", { class: "nav-main", "aria-label": "Freefield" });
  for (const [key, hash] of items) {
    const a = el("a", { href: hash }, t(`nav.${key}`));
    links.set(key, a);
    nav.append(a);
  }
  nav.append(el("span", { class: "sep opt-hide" }));
  for (const f of FEATURED) {
    const app = byId.get(f.id);
    if (!app) continue;
    const a = el("a", { href: `#/app/${app.id}`, class: "opt-hide" }, app.name, f.tag ? el("span", { class: `tag${f.tag === "new" ? "" : " violet"}` }, t(`tag.${f.tag}`)) : null);
    links.set(app.id, a);
    nav.append(a);
  }
  const vram = el("a", { class: "icon-btn", href: "#/vram", title: t("nav.vram"), "aria-label": t("nav.vram") }, icon("chip"));
  links.set("vram", vram);
  const langBtn = el("button", { class: "icon-btn", type: "button", title: t("nav.lang"), "aria-label": t("nav.lang") }, icon("globe"));
  langBtn.onclick = () => popover(langBtn, el("div", {}, ...LANGS.map(([code, name]) => el("button", { class: "opt", type: "button", "aria-selected": String(code === lang),
    onclick: () => { closePopover(); setLang(code); onLang(); } }, name, el("span", { class: "chk" }, icon("check"))))), { align: "end" });
  // phones: the same links in a menu
  const menuBtn = el("button", { class: "icon-btn menu-btn", type: "button", "aria-label": "Menu" }, icon("menu"));
  menuBtn.onclick = () => popover(menuBtn, el("div", {}, ...[...items.map(([key, hash, ic]) => [t(`nav.${key}`), hash, ic]),
    ...FEATURED.filter((f) => byId.has(f.id)).map((f) => [byId.get(f.id).name, `#/app/${f.id}`, "spark"]), [t("nav.vram"), "#/vram", "chip"]]
    .map(([label, hash, ic]) => el("a", { class: "opt", href: hash, onclick: closePopover }, icon(ic), label))));
  const bar = el("header", { class: "topbar" },
    menuBtn,
    el("a", { class: "logo", href: "#/", "aria-label": "Freefield" }, logoMark(), el("span", { class: "word" }, "freefield")),
    nav,
    el("div", { class: "nav-right" }, vram, langBtn, gpuPill(), el("a", { class: "btn lime small cta", href: "#/image" }, icon("spark"), t("nav.create"))));
  attachMenus(bar, links);
  if (!pollTimer) pollGpu();
  return {
    node: bar,
    update(active) {
      for (const [key, a] of links) {
        if (key === active) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      }
    },
  };
}
export { pollGpu };

// The top bar's menus: hovering Image, Video or Audio opens a panel with every app of that studio, grouped like the
// studio, and the open models behind them. A click on the link itself still opens the studio. Pointer only: on touch
// screens the links behave as before, and phones use the menu button.
import { el, icon } from "./util.js";
import { t, lang } from "./i18n.js";
import { apps, byId, FEATURED, MODELS, menuGroups, modelOf, usesModel, tagline } from "./catalog.js";

const canHover = window.matchMedia?.("(hover: hover) and (pointer: fine)");
const OPEN_MS = 90, CLOSE_MS = 180;

function thumbOf(app) {
  const ex = app.example;
  const src = ex?.poster || (ex && ex.type !== "video" ? ex.card : null);
  return el("span", { class: "mm-thumb" }, src
    ? el("img", { src, alt: "", loading: "lazy", decoding: "async" })
    : icon(app.section === "video" ? "video" : app.section === "audio" ? "audio" : "image"));
}

function tagOf(app) {
  if (app.status === "draft") return el("span", { class: "tag ghost" }, t("tag.draft"));
  const f = FEATURED.find((x) => x.id === app.id);
  return f?.tag ? el("span", { class: `tag${f.tag === "new" ? "" : " violet"}` }, t(`tag.${f.tag}`)) : null;
}

const usedBy = (n) => t(n === 1 ? "menu.used1" : "menu.used", { n });

function appItem(app) {
  const model = modelOf(app);
  const tip = [model?.name, app.higgsfield_feature ? `${t("how.equiv")}: ${app.higgsfield_feature}` : null].filter(Boolean).join(" · ");
  const line = tagline(app);
  return el("a", { class: "mm-item", href: `#/app/${app.id}`, role: "menuitem", title: tip || null },
    thumbOf(app),
    el("span", { class: "mm-txt" }, el("b", {}, el("span", { class: "nm" }, app.name), tagOf(app)),
      el("small", {}, line !== app.name ? line : model?.name ?? "")));
}

function modelItem(m, menuApps, studio) {
  const users = menuApps.filter((a) => usesModel(a, m));
  // the model's own app, or the first app of this menu built on it (SeedVR2 in Image opens Upscale, not Upscale Video)
  const target = users.includes(byId.get(m.app)) ? byId.get(m.app) : users[0];
  return el("a", { class: "mm-item model", href: `#/app/${target.id}`, role: "menuitem" },
    el("span", { class: "mm-thumb glyph" }, icon(studio === "video" ? "video" : studio === "audio" ? "audio" : "layers")),
    el("span", { class: "mm-txt" }, el("b", {}, el("span", { class: "nm" }, m.name),
      target.status === "draft" ? el("span", { class: "tag ghost" }, t("tag.draft")) : el("span", { class: "n" }, usedBy(users.length))),
      el("small", {}, m.note[lang === "es" ? 1 : 0])));
}

function panelFor(studio) {
  const groups = menuGroups(studio);
  const menuApps = groups.flatMap((g) => g.apps);
  const models = MODELS.map((m, i) => ({ m, i, n: menuApps.filter((a) => usesModel(a, m)).length }))
    .filter((x) => x.n).sort((a, b) => b.n - a.n || a.i - b.i);
  const feats = el("section", { class: "mm-feats" },
    el("h4", {}, t("menu.features"), el("span", { class: "n" }, t("explore.apps", { n: menuApps.length }))),
    el("div", { class: `mm-cols${groups.length === 1 ? " one" : ""}` }, ...groups.map((g) => el("div", { class: "mm-group", role: "group", "aria-label": g.key ? t(g.key) : null },
      g.key ? el("h5", {}, t(g.key)) : null, ...g.apps.map(appItem)))));
  const mods = el("section", { class: "mm-models" }, el("h4", {}, t("menu.models")), ...models.map(({ m }) => modelItem(m, menuApps, studio)));
  return el("div", { class: `mm-inner mm-${studio}` }, feats, mods);
}

/** Wire the menus onto the studio links of a freshly built top bar. */
export function attachMenus(bar, links) {
  if (!canHover?.matches) return;
  const panel = el("div", { class: "mm", role: "menu", hidden: true });
  bar.append(panel);
  const built = new Map();
  let openKey = null, openTimer = null, closeTimer = null;

  const close = () => {
    clearTimeout(openTimer); clearTimeout(closeTimer);
    if (!openKey) return;
    links.get(openKey)?.setAttribute("aria-expanded", "false");
    openKey = null;
    panel.hidden = true;
  };
  const open = (key) => {
    clearTimeout(openTimer); clearTimeout(closeTimer);
    if (openKey === key) return;
    if (openKey) links.get(openKey)?.setAttribute("aria-expanded", "false");
    if (!built.has(key)) built.set(key, panelFor(key));
    panel.replaceChildren(built.get(key));
    panel.dataset.studio = key;
    panel.hidden = false;
    panel.scrollTop = 0;
    for (const a of panel.querySelectorAll(".mm-item")) {
      if (a.getAttribute("href") === location.hash) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    openKey = key;
    links.get(key).setAttribute("aria-expanded", "true");
  };
  const later = () => { clearTimeout(openTimer); clearTimeout(closeTimer); closeTimer = setTimeout(close, CLOSE_MS); };

  for (const key of ["image", "video", "audio"]) {
    const a = links.get(key);
    if (!a || !apps.length) continue;
    a.setAttribute("aria-haspopup", "true");
    a.setAttribute("aria-expanded", "false");
    a.addEventListener("pointerenter", () => {
      clearTimeout(closeTimer);
      clearTimeout(openTimer);
      // moving from one open menu to the next swaps at once; the first one waits a beat so passing over the bar does not flash it
      if (openKey) open(key); else openTimer = setTimeout(() => open(key), OPEN_MS);
    });
    a.addEventListener("pointerleave", later);
    a.addEventListener("click", close);
    a.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); open(key); panel.querySelector(".mm-item")?.focus(); }
    });
  }
  panel.addEventListener("pointerenter", () => clearTimeout(closeTimer));
  panel.addEventListener("pointerleave", later);
  panel.addEventListener("click", (e) => { if (e.target.closest("a")) close(); });
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { const k = openKey; close(); links.get(k)?.focus(); }
  });
  panel.addEventListener("focusout", (e) => { if (!panel.contains(e.relatedTarget) && ![...links.values()].includes(e.relatedTarget)) close(); });
  window.addEventListener("hashchange", close);
  window.addEventListener("blur", close);
}

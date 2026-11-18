// The top bar's menus: hovering Image, Video or Audio opens a panel with every app of that studio, grouped like the
// studio, and the open models behind them. A click on the link itself still opens the studio. Pointer only: on touch
// screens the links behave as before, and phones use the menu button.
import { el, icon } from "./util.js";
import { t, lang } from "./i18n.js";
import { apps, byId, FEATURED, MODELS, menuGroups, modelOf, usesModel, tagline } from "./catalog.js";

const canHover = window.matchMedia?.("(hover: hover) and (pointer: fine)");
const OPEN_MS = 90, CLOSE_MS = 180;
const AIM_MS = 450;   // how long the pointer may rest on its way from a studio link to the open panel

/** Whether (px, py) is inside the triangle a-b-c (either winding). */
export function inTriangle(px, py, ax, ay, bx, by, cx, cy) {
  const d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by);
  const d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy);
  const d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
}

/** Whether a pointer at (x, y) that left a studio link at aim is heading for the panel rect r: inside the triangle
 *  from aim to the two corners of r that face it. The panel is centred, so the link is usually off to one side and
 *  the way there is a diagonal across the page, which used to close the menu half way. */
export function towardPanel(aim, x, y, r) {
  if (!aim || !r) return false;
  if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return true;
  if (aim.x < r.left) return inTriangle(x, y, aim.x, aim.y, r.right, r.top, r.left, r.bottom);
  if (aim.x > r.right) return inTriangle(x, y, aim.x, aim.y, r.left, r.top, r.right, r.bottom);
  return inTriangle(x, y, aim.x, aim.y, r.left, r.top, r.right, r.top);
}

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
      el("small", {}, m.note[lang === "ru" ? 2 : lang === "es" ? 1 : 0])));
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
  let aim = null;   // where the pointer left a studio link while a panel is open

  const close = () => {
    clearTimeout(openTimer); clearTimeout(closeTimer);
    aim = null;
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
  const heading = (e) => openKey && !panel.hidden && towardPanel(aim, e.clientX, e.clientY, panel.getBoundingClientRect());
  // while the pointer keeps heading for the open panel, the close waits; it closes once the pointer turns away or rests
  document.addEventListener("pointermove", (e) => {
    if (aim && heading(e)) { clearTimeout(closeTimer); closeTimer = setTimeout(close, AIM_MS); }
  }, { passive: true });

  for (const key of ["image", "video", "audio"]) {
    const a = links.get(key);
    if (!a || !apps.length) continue;
    a.setAttribute("aria-haspopup", "true");
    a.setAttribute("aria-expanded", "false");
    a.addEventListener("pointerenter", (e) => {
      clearTimeout(closeTimer);
      clearTimeout(openTimer);
      // moving from one open menu to the next swaps at once; the first one waits a beat so passing over the bar does not flash it.
      // Crossing another studio's link on the way down to the open panel does not swap, unless the pointer stays on it;
      // sliding along the bar from one studio to the next still swaps at once.
      if (openKey && openKey !== key && aim && e.clientY > aim.y + 4 && heading(e)) openTimer = setTimeout(() => open(key), AIM_MS);
      else if (openKey) open(key);
      else openTimer = setTimeout(() => open(key), OPEN_MS);
    });
    a.addEventListener("pointerleave", (e) => { aim = openKey ? { x: e.clientX, y: e.clientY } : null; later(); });
    a.addEventListener("click", close);
    a.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); open(key); panel.querySelector(".mm-item")?.focus(); }
    });
  }
  panel.addEventListener("pointerenter", () => { clearTimeout(closeTimer); clearTimeout(openTimer); aim = null; });
  panel.addEventListener("pointerleave", () => { aim = null; later(); });
  panel.addEventListener("click", (e) => { if (e.target.closest("a")) close(); });
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { const k = openKey; close(); links.get(k)?.focus(); }
  });
  panel.addEventListener("focusout", (e) => { if (!panel.contains(e.relatedTarget) && ![...links.values()].includes(e.relatedTarget)) close(); });
  window.addEventListener("hashchange", close);
  window.addEventListener("blur", close);
}

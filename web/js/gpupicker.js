// The "My GPU" chip in the top bar and its panel: the card size and RAM the studio judges every app against
// (mygpu.js). The VRAM map and the Apps page reuse the size rows and the panel.
import { el, icon, popover, closePopover } from "./util.js";
import { t } from "./i18n.js";
import { apps } from "./catalog.js";
import { mygpu, TIERS, RAMS, countsOn, pickSize, useBackend } from "./mygpu.js";

/** The two rows of sizes, VRAM and RAM, bound to the pick. */
export function sizeRows() {
  const p = mygpu.pick;
  const row = (label, sizes, cur, key) => el("div", { class: "gpick-row" },
    el("span", { class: "lbl" }, label),
    el("div", { class: "seg gpick", role: "group", "aria-label": label }, ...sizes.map((n) => el("button", { type: "button", "aria-pressed": String(n === cur),
      onclick: () => pickSize({ [key]: n }) }, String(n)))),
    el("span", { class: "dim" }, t("unit.gb")));
  return el("div", { class: "gpick-rows" }, row(t("mygpu.vram"), TIERS, p?.vram, "vram"), row(t("mygpu.ram"), RAMS, p?.ram, "ram"));
}

/** How many apps run on the chosen card: as they are, in lite, with RAM, short of RAM (and failed in the lab, if any). */
export function countsRow(pick = mygpu.pick) {
  if (!pick) return null;
  const c = countsOn(apps, pick);
  const cell = (key, cls) => el("div", { class: `gcount ${cls}` }, el("b", {}, String(c[key])), el("span", {}, t(`mygpu.c.${key}`)));
  return el("div", { class: `gcounts${c.no ? " five" : ""}`, "aria-label": t("mygpu.on", { gb: pick.vram }) },
    cell("full", "ok"), cell("lite", "lite"), cell("offload", "tight"), cell("noram", "big"), c.no ? cell("no", "big") : null);
}

/** The panel: sizes, the backend's own card, what runs on the chosen one. Redraws itself while open. */
function gpuPanel() {
  const box = el("div", { class: "pad gpanel" });
  const draw = () => {
    const p = mygpu.pick, b = mygpu.backend;
    const same = b && p && p.vram === b.tier && (b.ram === null || p.ram === b.ram);
    box.replaceChildren(...[
      el("h4", {}, t("mygpu.title")),
      el("p", { class: "help" }, t("mygpu.help")),
      sizeRows(),
      b ? el("div", { class: "gback" }, el("span", {}, t("mygpu.backend", { name: b.name || "GPU", gb: b.vram_gb })),
        same ? el("span", { class: "chip ok" }, icon("check"), t("mygpu.inuse"))
          : el("button", { class: "btn small", type: "button", onclick: useBackend }, t("mygpu.use"))) : null,
      p ? el("p", { class: "gon" }, t("mygpu.on", { gb: p.vram })) : null,
      countsRow(p),
      p ? el("p", { class: "help" }, t("mygpu.estimate")) : null,
      el("div", { class: "row" },
        el("a", { class: "btn small ghost", href: "#/vram", onclick: () => closePopover() }, icon("chip"), t("nav.vram")),
        p ? el("button", { class: "btn small ghost", type: "button", onclick: () => mygpu.set(null) }, t("mygpu.clear")) : null),
    ].filter(Boolean));
  };
  draw();
  return { node: box, off: mygpu.on(draw) };
}

export function openMyGpu(anchor, { align = "end" } = {}) {
  const { node, off } = gpuPanel();
  popover(anchor, node, { align, onClose: off, width: 360, cls: "gpop" });
}

let chipOff = null;
/** The top bar's chip: "My GPU", or the card size once there is one. */
export function gpuChip() {
  const label = el("span", {});
  const btn = el("button", { class: "gchip", type: "button", "aria-haspopup": "dialog", title: t("mygpu.title") }, icon("chip"), label);
  const draw = () => {
    const p = mygpu.pick;
    label.textContent = p ? `${p.vram} ${t("unit.gb")}` : t("mygpu.chip");
    btn.classList.toggle("set", Boolean(p));
  };
  draw();
  chipOff?.();   // a rebuilt bar (a new language) replaces the old chip
  chipOff = mygpu.on(draw);
  btn.onclick = () => openMyGpu(btn);
  return btn;
}

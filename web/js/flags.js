// "Mediocre" marks on the lab examples (/api/flags → lab/flags.json): a toggle on each example so the
// person reviewing the app can say which results are not good enough; whoever runs the lab reads the file
// and looks for a better model, LoRA or prompt of the same kind. Keys: "<app>" for the app's example,
// "<app>/<input>/<option>" for one option of a gallery select (the effects picker).
import { api, el, icon, toast } from "./util.js";
import { t } from "./i18n.js";
import { hosted } from "./catalog.js";

let marks = {};
const subs = new Set();
const emit = () => { for (const fn of subs) fn(marks); };

export const flags = {
  key: (appId, inputId = null, value = null) => (inputId === null ? appId : `${appId}/${inputId}/${value}`),
  is: (key) => Boolean(marks[key]),
  keys: () => Object.keys(marks),
  count: () => Object.keys(marks).length,
  async load() {
    try { marks = (await api("/api/flags")).mediocre || {}; } catch { marks = {}; }
    emit();
  },
  async set(key, mediocre) {
    const d = await api("/api/flags", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key, mediocre }) });
    marks = d.mediocre || {};
    emit();
  },
  on(fn) { subs.add(fn); return () => subs.delete(fn); },
};

// every button on the page follows the store, so the wall, the picker and the viewer agree
flags.on(() => {
  for (const b of document.querySelectorAll("[data-flag-key]")) paint(b);
});

function paint(b) {
  const on = flags.is(b.dataset.flagKey);
  b.setAttribute("aria-pressed", String(on));
  b.title = on ? t("flag.unmark") : t("flag.mark");
  b.setAttribute("aria-label", b.title);
  if (b.dataset.flagLabel) b.lastChild.textContent = on ? t("flag.marked") : t("flag.mediocre");
}

/** The toggle. mini: an icon in a card's corner; otherwise a labelled button for a details panel. */
export function flagButton(key, { mini = false } = {}) {
  const b = el("button", { class: mini ? "mini flag" : "btn ghost flag", type: "button", "data-flag-key": key, ...(mini ? {} : { "data-flag-label": "1" }) },
    icon("thumbdown"), mini ? null : el("span", {}, ""));
  if (hosted) b.hidden = true;   // marks are written to lab/flags.json, which a hosted demo does not keep
  paint(b);
  b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    ev.preventDefault();
    const next = !flags.is(key);
    try {
      await flags.set(key, next);
      toast(next ? t("flag.saved") : t("flag.cleared"));
    } catch (e) {
      toast(e.message, { error: true });
    }
  });
  return b;
}

// On your own Windows PC (the launcher, start.ps1, started this Freefield), a card asks once whether to put a
// Freefield icon on the desktop. The server keeps the answer in the volume, and the launcher's window, still open on
// Windows, makes the icon (server/desktop.ts). /api/gpu carries the state; it is null where there is no launcher:
// RunPod, Vast.ai, the hosted demo.
import { el, api, toast, logoMark } from "./util.js";
import { t } from "./i18n.js";

let card = null;
let busy = false;

function close() {
  card?.remove();
  card = null;
}

async function answer(want) {
  if (busy) return;
  busy = true;
  try {
    await api("/api/desktop-icon", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ want }) });
    if (!want) return close();
    card?.querySelector(".txt")?.replaceChildren(el("b", {}, t("icon.making")));
    for (let i = 0; i < 40; i++) {   // the launcher looks every few seconds
      await new Promise((r) => setTimeout(r, 1500));
      const g = await api("/api/gpu").catch(() => null);
      if (g?.desktop_icon === "created") { toast(t("icon.done")); return close(); }
    }
    toast(t("icon.later"));   // its window was closed: the next start makes it
    close();
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    busy = false;
  }
}

/** A gpuState listener (main.js): shows the card while the answer is "ask". */
export function desktopIconCard(g) {
  if (busy) return;
  if (g?.desktop_icon !== "ask") return close();
  if (card?.isConnected) return;
  card = el("div", { class: "iconcard", role: "dialog", "aria-label": t("icon.q") },
    logoMark(),
    el("div", { class: "txt" },
      el("b", {}, t("icon.q")),
      el("p", {}, t("icon.sub")),
      el("div", { class: "row" },
        el("button", { class: "btn lime small", type: "button", onclick: () => answer(true) }, t("icon.yes")),
        el("button", { class: "btn small ghost", type: "button", onclick: () => answer(false) }, t("icon.no")))));
  document.body.append(card);
}

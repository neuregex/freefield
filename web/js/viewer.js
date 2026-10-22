// The viewer: one result large, with what made it (prompt, settings, inputs, timings) and what
// to do next (recreate, download, compare, delete). Arrow keys move through the list it came from.
import { el, icon, fmtSeconds, toast } from "./util.js";
import { t, ago } from "./i18n.js";
import { byId, promptInput } from "./catalog.js";
import { fullMedia, thumb, downloadName } from "./media.js";
import { hooks, feed, deleteButton } from "./feed.js";
import { flags, flagButton } from "./flags.js";

function optionLabel(inp, v) {
  const o = (inp.options || []).find((x) => String(x.value) === String(v));
  return o ? o.label : String(v ?? "");
}

export function openViewer(items, startKey) {
  if (!items.length) return;
  let i = Math.max(0, items.findIndex((x) => x.key === startKey || x.id === startKey));
  let out = 0;
  const stage = el("div", { class: "stage" });
  const aside = el("aside");
  const modal = el("div", { class: "modal", role: "dialog", "aria-modal": "true" }, stage, aside);
  const prevFocus = document.activeElement;
  const close = () => {
    modal.remove();
    document.removeEventListener("keydown", onKey, true);
    document.body.style.overflow = "";
    prevFocus?.focus?.({ preventScroll: true });
  };
  const go = (d) => { i = (i + d + items.length) % items.length; out = 0; draw(); };
  const onKey = (e) => {
    if (e.target.closest?.("input, textarea")) return;
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    else if (e.key === "ArrowRight" && items.length > 1) go(1);
    else if (e.key === "ArrowLeft" && items.length > 1) go(-1);
  };
  modal.addEventListener("click", (e) => { if (e.target === stage) close(); });

  function draw() {
    const item = items[i];
    const app = byId.get(item.app);
    const output = item.outputs[out] || { type: item.type, url: item.full };
    stage.replaceChildren(...[
      el("button", { class: "round close", type: "button", title: t("act.close"), "aria-label": t("act.close"), onclick: close }, icon("x")),
      items.length > 1 ? el("button", { class: "round navb prev", type: "button", "aria-label": t("act.prev"), onclick: () => go(-1) }, icon("chevL")) : null,
      fullMedia(output.type, output.url, { poster: item.poster }),
      items.length > 1 ? el("button", { class: "round navb next", type: "button", "aria-label": t("act.next"), onclick: () => go(1) }, icon("chevR")) : null,
      item.outputs.length > 1 ? el("div", { class: "tabs", style: { position: "absolute", bottom: "14px", left: "50%", transform: "translateX(-50%)" } },
        ...item.outputs.map((o, k) => el("button", { type: "button", "aria-selected": String(k === out), onclick: () => { out = k; draw(); } }, `${k + 1}`))) : null].filter(Boolean));

    const pi = app ? promptInput(app) : null;
    const prompt = pi ? String(item.values?.[pi.id] ?? "") : "";
    const labels = Object.fromEntries((app?.inputs || []).map((x) => [x.id, x]));
    const settings = Object.entries(item.values || {}).filter(([k, v]) => labels[k] && labels[k] !== pi && labels[k].type !== "seed" && v !== "" && v !== null && v !== undefined);
    const stats = [
      item.seconds ? [icon("clock"), t("view.gpu", { s: fmtSeconds(item.seconds) })] : null,
      item.total && (!item.seconds || item.total - item.seconds > 2) ? [item.seconds ? null : icon("clock"), t("view.total", { s: fmtSeconds(item.total) })] : null,
      item.gpu ? [icon("chip"), item.gpu.split(",")[0]] : null,
      item.peak ? [t("view.peak", { gb: item.peak })] : null,
      item.seed !== null && item.seed !== undefined ? [icon("dice"), String(item.seed)] : null,
    ].filter(Boolean);
    const url = output.url;
    aside.replaceChildren(...[
      el("div", { class: "approw" }, app ? thumb({ ...item, kind: "example", card: app.example?.card || item.card, poster: app.example?.poster, type: app.example?.type || item.type }, { play: "none" }) : null,
        el("div", {}, el("b", {}, app?.name ?? item.app), el("small", {}, item.kind === "example" ? t("view.example") : ago(item.created)))),
      prompt ? el("div", { style: { display: "grid", gap: "6px" } },
        el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, el("small", { class: "dim" }, t("view.prompt")),
          el("button", { class: "btn small ghost", type: "button", onclick: () => navigator.clipboard?.writeText(prompt).then(() => toast(t("toast.copied"))) }, icon("copy"), t("act.copy"))),
        el("div", { class: "prompt" }, prompt)) : null,
      stats.length ? el("div", { class: "statline" }, ...stats.map((s) => el("span", {}, ...s))) : null,
      settings.length ? el("div", { style: { display: "grid", gap: "8px" } }, el("small", { class: "dim" }, t("view.settings")),
        el("dl", { class: "vals" }, ...settings.flatMap(([k, v]) => [el("dt", {}, labels[k].label),
          el("dd", {}, labels[k].type === "select" ? optionLabel(labels[k], v) : labels[k].type === "toggle" ? (v === true || v === "true" ? "✓" : "—") : String(v))]))) : null,
      item.inputs.length ? el("div", { style: { display: "grid", gap: "8px" } }, el("small", { class: "dim" }, t("view.inputs")),
        el("div", { class: "ins-row" }, ...item.inputs.map((x) => el("figure", {},
          el("a", { class: "media", href: x.file, target: "_blank", rel: "noopener", title: x.label },
            x.thumb ? el("img", { src: x.thumb, alt: x.label }) : el("span", { class: "typeicon", style: { position: "static", margin: "33px auto" } }, icon(x.type || "image"))),
          el("figcaption", {}, x.label))))) : null,
      el("div", { class: "acts" },
        app ? el("button", { class: "btn lime", type: "button", onclick: () => { close(); hooks.recreate?.(item); } }, icon("redo"), t("act.recreate")) : null,
        url ? el("a", { class: "btn ghost", href: url, download: downloadName(item, url) }, icon("download"), t("act.download")) : null,
        el("button", { class: "btn ghost", type: "button", onclick: () => { close(); hooks.compare?.({ ...item, full: url, type: output.type }); } }, icon("compare"), t("act.compare")),
        item.kind === "example" && app ? flagButton(flags.key(app.id)) : null,
        item.kind === "history" ? deleteButton(async () => {
          await feed.remove(item.id);
          items.splice(i, 1);
          if (!items.length) close(); else { i = Math.min(i, items.length - 1); draw(); }
        }, "btn ghost danger") : app ? el("a", { class: "btn ghost", href: `#/app/${app.id}`, onclick: close }, icon("ext"), t("act.open")) : null)].filter(Boolean));
  }

  draw();
  document.body.append(modal);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKey, true);
  modal.querySelector(".close")?.focus({ preventScroll: true });
  return close;
}

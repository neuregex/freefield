// The history feed: runs started here (out/history on the server), polled while any is going,
// drawn as result cards that keep their place (and their playing video) while others update.
import { api, el, icon, fmtSeconds, masonry, toast, live } from "./util.js";
import { t, ago } from "./i18n.js";
import { byId, promptInput } from "./catalog.js";
import { entryItem, thumb, downloadName } from "./media.js";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "expired", "lost"]);
export const isDone = (e) => TERMINAL.has(e.status);

/** Set by main.js so cards can call into the workspace and the viewer without import cycles. */
export const hooks = { open: null, recreate: null, retry: null, compare: null };

class Feed {
  constructor() {
    this.entries = new Map();
    this.listeners = new Set();
    this.timer = null;
    this.loaded = new Set();   // scopes fetched at least once: an app id, or "*" for everything
  }
  isLoaded(app) { return this.loaded.has("*") || this.loaded.has(app ?? "*"); }
  async load(app) {
    const { entries } = await api(`/api/history${app ? `?app=${encodeURIComponent(app)}` : ""}`);
    const seen = new Set(entries.map((e) => e.id));
    for (const [id, e] of this.entries) if ((!app || e.app === app) && !seen.has(id)) this.entries.delete(id);
    for (const e of entries) this.entries.set(e.id, e);
    this.loaded.add(app ?? "*");
    this.emit();
    this.schedule();
  }
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit() { for (const fn of this.listeners) fn(); }
  list(app) {
    return [...this.entries.values()].filter((e) => !app || e.app === app).sort((a, b) => (a.id < b.id ? 1 : -1));
  }
  get(id) { return this.entries.get(id); }
  active() { return [...this.entries.values()].filter((e) => !isDone(e)); }
  schedule() {
    if (this.timer || !this.active().length) return;
    this.timer = setTimeout(() => this.poll(), 1200);
  }
  async poll() {
    this.timer = null;
    await Promise.all(this.active().map((e) => api(`/api/history/${e.id}`)
      .then((fresh) => this.entries.set(e.id, fresh))
      .catch((err) => { if (err.status === 404) this.entries.delete(e.id); })));
    this.emit();
    this.schedule();
  }
  async run(appId, formData) {
    const entry = await api(`/api/apps/${appId}/run`, { method: "POST", body: formData });
    this.entries.set(entry.id, entry);
    this.emit();
    this.schedule();
    return entry;
  }
  async remove(id) {
    await api(`/api/history/${id}`, { method: "DELETE" });
    this.entries.delete(id);
    this.emit();
  }
  async cancel(id) {
    await api(`/api/history/${id}/cancel`, { method: "POST" });
    this.poll();
  }
}
export const feed = new Feed();

export function statusText(e) {
  if (e.status === "starting") return live.gpuWarm ? t("status.submitting") : t("status.starting");
  if (e.status === "queued") return e.queue ? t("status.queued.n", { n: e.queue }) : t("status.queued");
  if (e.status === "running") {
    const p = e.progress;
    let s = t("status.running");
    if (p?.step && p?.steps) s += ` · ${t("status.step", { a: p.step, b: p.steps })}`;
    else if (p?.value > 0) s += ` · ${Math.round(p.value * 100)}%`;
    return s;
  }
  return t(`status.${e.status}`);
}

/** The shape a placeholder should have: from width/height or an "a:b" aspect value. */
function aspectOf(e) {
  const v = e.values || {};
  if (Number(v.width) > 0 && Number(v.height) > 0) return `${v.width} / ${v.height}`;
  const m = /(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)/.exec(String(v.aspect ?? v.size ?? ""));
  return m ? `${m[1]} / ${m[2]}` : null;
}

/** A button that asks once more before deleting. */
export function deleteButton(onDelete, cls = "mini", withLabel = cls !== "mini") {
  let armed = null;
  const idle = () => [icon("trash"), withLabel ? t("act.delete") : null];
  const b = el("button", { class: cls, type: "button", title: t("act.delete"), "aria-label": t("act.delete") }, idle());
  b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    if (!armed) {
      b.replaceChildren(icon("check"), withLabel ? t("act.sure") : "");
      b.title = t("act.sure");
      b.style.color = "var(--bad)";
      armed = setTimeout(() => { armed = null; b.replaceChildren(...idle().filter(Boolean)); b.title = t("act.delete"); b.style.color = ""; }, 2600);
      return;
    }
    clearTimeout(armed);
    try { await onDelete(); toast(t("toast.deleted")); } catch (err) { toast(err.message, { error: true }); }
  });
  return b;
}

function pendingCard(e) {
  const app = byId.get(e.app);
  const item = entryItem(e);
  const bar = el("i");
  const barBox = el("div", { class: "bar indet" }, bar);
  const title = el("b");
  const prev = el("img", { class: "preview", alt: "", hidden: true });
  const node = el("div", { class: `rcard pending ${item.type}` },
    el("div", { class: "shimmer" }), prev,
    el("button", { class: "mini stop", type: "button", title: t("act.cancel"), "aria-label": t("act.cancel"),
      onclick: (ev) => { ev.stopPropagation(); feed.cancel(e.id).catch((err) => toast(err.message, { error: true })); } }, icon("stop")),
    el("div", { class: "state" }, title, barBox,
      el("small", {}, `${app?.name ?? e.app} · `, el("span", { dataset: { since: e.created } }, fmtSeconds((Date.now() - Date.parse(e.created)) / 1000)))));
  const ar = aspectOf(e);
  if (ar) node.style.aspectRatio = ar;
  const update = (fresh) => {
    title.textContent = statusText(fresh);
    const p = fresh.progress?.value;
    barBox.classList.toggle("indet", !(p > 0));
    bar.style.width = p > 0 ? `${Math.round(p * 100)}%` : "";
    if (fresh.preview && prev.dataset.src !== fresh.preview) {
      prev.src = fresh.preview;
      prev.dataset.src = fresh.preview;
      prev.hidden = false;
    }
  };
  update(e);
  return { node, update };
}

function failedCard(e) {
  const app = byId.get(e.app);
  const item = entryItem(e);
  const node = el("div", { class: "rcard failed" },
    el("b", {}, `${t(`status.${e.status}`)} · ${app?.name ?? e.app}`),
    el("pre", {}, e.error?.class_type ? `${e.error.class_type}${e.error.node ? ` (node ${e.error.node})` : ""}: ${e.error.message}` : (e.error?.message || "")),
    el("div", { class: "row" },
      app ? el("button", { class: "btn small lime", type: "button", onclick: () => hooks.retry?.(item) }, icon("redo"), t("act.retry")) : null,
      app ? el("button", { class: "btn small ghost", type: "button", onclick: () => hooks.recreate?.(item) }, t("act.recreate")) : null,
      deleteButton(() => feed.remove(e.id), "btn small ghost danger")));
  return { node };
}

function doneCard(e, list) {
  const app = byId.get(e.app);
  const item = entryItem(e);
  const media = thumb(item, { play: "visible" });
  const prompt = app && promptInput(app) ? String(e.values?.[promptInput(app).id] ?? "") : "";
  const stop = (fn) => (ev) => { ev.stopPropagation(); fn(); };
  const open = () => hooks.open?.(list().map(entryItem), e.id);
  const dl = el("a", { class: "mini", href: item.full, download: downloadName(item, item.full), title: t("act.download"), "aria-label": t("act.download"),
    onclick: (ev) => ev.stopPropagation() }, icon("download"));
  const node = el("div", { class: "rcard", tabindex: "0", role: "button", "aria-label": `${app?.name ?? e.app} · ${ago(e.created)}`,
    onclick: open, onkeydown: (ev) => { if (ev.key === "Enter") open(); } },
    media,
    el("div", { class: "ov" },
      el("div", { class: "row" }, el("span", { class: "tag dark" }, app?.name ?? e.app),
        el("div", { class: "acts" }, dl,
          el("button", { class: "mini", type: "button", title: t("act.compare"), "aria-label": t("act.compare"), onclick: stop(() => hooks.compare?.(item)) }, icon("compare")),
          deleteButton(() => feed.remove(e.id)))),
      el("div", { class: "row" }, el("span", { class: "meta" }, prompt || `${ago(e.created)}${e.seconds ? ` · ${fmtSeconds(e.seconds)}` : ""}`),
        app ? el("button", { class: "mini lime", type: "button", title: t("act.recreate"), "aria-label": t("act.recreate"), onclick: stop(() => hooks.recreate?.(item)) }, icon("redo")) : null)));
  return { node };
}

/**
 * Draw the feed for one app (or all) into host and keep it current.
 * empty(): what to show when there is nothing yet. Returns a cleanup function.
 */
export function feedView(host, { app = null, empty = null, dense = false } = {}) {
  const grid = el("div", { class: `feed${dense ? " dense" : ""}` });
  const cards = new Map();
  let lastOrder = null;
  const list = () => feed.list(app).filter((e) => e.status === "succeeded" && e.outputs.length);
  const kindOf = (e) => (!isDone(e) ? "pending" : e.status === "succeeded" && e.outputs.length ? "done" : "failed");
  const render = () => {
    const entries = feed.list(app);
    if (!entries.length && !feed.isLoaded(app)) return;   // first load still on its way: no flash of the empty state
    if (!entries.length) {
      if (lastOrder !== "") host.replaceChildren(empty ? empty() : el("div", { class: "empty" }, t("ws.empty.hist")));
      lastOrder = "";
      cards.clear();
      return;
    }
    if (!grid.isConnected || grid.parentNode !== host) host.replaceChildren(grid);
    let changed = false;
    const seen = new Set();
    const nodes = entries.map((e) => {
      seen.add(e.id);
      const kind = kindOf(e);
      const c = cards.get(e.id);
      if (c && c.kind === kind) { c.update?.(e); return c.node; }
      const made = kind === "pending" ? pendingCard(e) : kind === "done" ? doneCard(e, list) : failedCard(e);
      cards.set(e.id, { ...made, kind });
      changed = true;
      return made.node;
    });
    for (const id of [...cards.keys()]) if (!seen.has(id)) { cards.delete(id); changed = true; }
    const order = entries.map((e) => e.id).join(",");
    if (changed || order !== lastOrder) masonry(grid, nodes, { min: dense ? 190 : 270, gap: dense ? 8 : 12 });
    lastOrder = order;
  };
  const off = feed.on(render);
  render();
  feed.load(app).catch((err) => toast(err.message, { error: true }));
  const tick = setInterval(() => {
    for (const n of host.querySelectorAll("[data-since]")) n.textContent = fmtSeconds((Date.now() - Date.parse(n.dataset.since)) / 1000);
  }, 1000);
  return () => { off(); clearInterval(tick); grid._ro?.disconnect(); };
}

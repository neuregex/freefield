// The Models panel, on a backend that downloads its own models (a pod on RunPod or Vast, your own GPU): what each pack
// lacks and why, the download on its way, the Hugging Face licenses and token. And the strip under the top bar when
// something waits. The server says what each app needs (server/models.ts, /api/models); this file shows it and asks.
// Nothing here exists on the hosted demo: the server answers models_panel: false there.
import { el, icon, api, toast } from "./util.js";
import { t, lang } from "./i18n.js";
import { apps, byId, modelsPanel } from "./catalog.js";
import { hooks } from "./feed.js";

export const models = { data: null, listeners: new Set() };
let timer = null;
let marks = null;   // which apps wait and why, the last time the page was drawn

const gb = (x) => new Intl.NumberFormat(lang, { maximumFractionDigits: 1, minimumFractionDigits: x && x < 10 ? 1 : 0 }).format(Number(x) || 0);
const visible = (needs) => Object.entries(needs || {}).filter(([id]) => byId.has(id));
const signature = (pairs) => pairs.map(([id, n]) => `${id}:${n.kind}`).sort().join(",");
const LICENSE_KINDS = ["token", "license"];

/** Start following the backend's downloads (main.js, when the catalog says there is a Models panel). */
export function startModels() {
  marks = signature(apps.filter((a) => a.needs).map((a) => [a.id, a.needs]));
  pollModels();
}

export async function pollModels({ fresh = false } = {}) {
  clearTimeout(timer);
  try { models.data = await api(`/api/models${fresh ? "?fresh=1" : ""}`); } catch { /* keep the last answer */ }
  const d = models.data;
  if (d?.available) {
    for (const a of apps) {
      const n = d.needs?.[a.id] ?? null;
      a.needs = n;
      a.missing_pack = n ? n.pack : null;
    }
    const now = signature(visible(d.needs));
    if (marks !== null && now !== marks) redrawPage();   // a pack arrived, a token unlocked apps: the cards follow
    marks = now;
  }
  for (const fn of models.listeners) fn(d);
  const moving = d?.job?.state === "running" || d?.queued?.length;
  timer = setTimeout(pollModels, document.hidden ? 60_000 : moving ? 3000 : 30_000);
}

function redrawPage() {
  // never under someone's fingers: a prompt being typed waits for the next look
  if (document.activeElement?.closest?.("input, textarea, select, [contenteditable]")) { marks = null; return; }
  hooks.rerender?.();
}

export function redrawModels() { for (const fn of models.listeners) fn(models.data); }

const count = (d, kinds) => visible(d?.needs).filter(([, n]) => kinds.includes(n.kind)).length;

export function gpuProblemText(p) {
  if (!p) return "";
  if (p.kind === "driver") return t("gpu.problem.driver", { driver: p.driver || "?" });
  if (p.kind === "old") return t("gpu.problem.old", { name: p.name || "GPU" });
  return t("gpu.problem.nogpu");
}

// ------------------------------------------------------------------ what an app's card and form say

/** The tag on an app's card, or null. */
export function needTag(a) {
  const n = a.needs ?? (a.missing_pack ? { kind: "pack", pack: a.missing_pack } : null);
  if (!n) return null;
  const key = { downloading: "tag.downloading", token: "tag.license", license: "tag.license", failed: "tag.failed" }[n.kind] ?? "tag.nopack";
  return el("span", { class: `tag dark need-${n.kind}`, title: needText(a) }, t(key));
}

/** One sentence for the form: why it cannot run yet. The catalog already says (a.needs), before /api/models answers. */
export function needText(a) {
  const n = a.needs ?? (a.missing_pack ? { kind: "pack", pack: a.missing_pack } : null);
  if (!n) return "";
  if (!modelsPanel) return t("ws.nopack", { pack: n.pack });   // an older backend: as before
  if (n.kind === "downloading") return t("ws.need.downloading");
  if (LICENSE_KINDS.includes(n.kind)) return t("ws.need.license");
  if (n.kind === "failed") return t("ws.need.failed");
  return t("ws.nopack2", { pack: n.pack });
}

/** The same sentence with the button that fixes it (opens the Models panel), for the form. */
export function needNode(a) {
  const n = a.needs ?? (a.missing_pack ? { kind: "pack", pack: a.missing_pack } : null);
  if (!n) return null;
  const text = needText(a);
  if (!modelsPanel || n.kind === "downloading") return el("span", {}, text);
  return el("span", {}, text, " ",
    el("button", { class: "link-btn", type: "button", onclick: () => openModels({ pack: n.pack }) },
      t(n.kind === "pack" ? "ws.need.get" : "ws.need.fix")));
}

// ------------------------------------------------------------------ the strip under the top bar

export function modelsStrip() {
  const node = el("div", { class: "mstrip", hidden: true, role: "status", "aria-live": "polite" });
  const draw = (d) => {
    const problem = d?.gpu_problem;
    if (!d?.available && !problem) { node.hidden = true; return; }
    const waiting = count(d, LICENSE_KINDS), failed = count(d, ["failed"]);
    const job = d.job?.state === "running" ? d.job : null;
    const open = (label, lime = false) => el("button", { class: `btn small${lime ? " lime" : ""}`, type: "button", onclick: () => openModels() }, label);
    const progress = job ? [el("span", { class: "dim" }, t("models.dl", { done: gb(job.done_gb), total: gb(job.gb) })),
      el("span", { class: "mbar" }, el("i", { style: { width: `${Math.min(100, (100 * job.done_gb) / (job.gb || 1))}%` } }))] : [];
    let kids = null, cls = "";
    if (problem) { cls = "bad"; kids = [icon("info"), el("span", { class: "msg" }, gpuProblemText(problem))]; }
    else if (waiting) {
      cls = "warn";
      kids = [icon("info"), el("b", { class: "msg" }, t(waiting === 1 ? "models.waiting1" : "models.waiting", { n: waiting })), ...progress, open(t("models.fix"), true)];
    } else if (job) kids = [icon("download"), ...progress, open(t("models.details"))];
    else if (failed) { cls = "warn"; kids = [icon("info"), el("span", { class: "msg" }, t(failed === 1 ? "models.failed1" : "models.failed", { n: failed })), open(t("models.details"))]; }
    else if (d.job?.state === "stopped") { cls = "warn"; kids = [icon("info"), el("span", { class: "msg" }, t("models.stopped")), open(t("models.details"))]; }
    node.hidden = !kids;
    node.className = `mstrip ${cls}`.trim();
    if (kids) node.replaceChildren(el("div", { class: "in" }, ...kids));
  };
  models.listeners.add(draw);
  draw(models.data);
  return node;
}

// ------------------------------------------------------------------ the panel

let openPanel = null;

/** focus.pack: the pack someone asked for from an app's form (its licenses show even before a download). */
export function openModels(focus = {}) {
  openPanel?.();
  const box = el("div", { class: "mpanel", role: "dialog", "aria-modal": "true", "aria-label": t("models.title") });
  const shade = el("div", { class: "mshade" }, box);
  const prevFocus = document.activeElement;
  let lic = null;          // the last answer of /api/models/licenses
  let checking = false;
  let changing = false;    // the token field shows even with a token (Change)
  let busy = false;
  const tokenInput = el("input", { type: "password", class: "mtoken", placeholder: "hf_…", autocomplete: "off", spellcheck: "false",
    "aria-label": t("models.hf.step2"), onkeydown: (e) => { if (e.key === "Enter") saveToken(); } });

  const close = () => {
    shade.remove();
    models.listeners.delete(draw);
    document.removeEventListener("keydown", onKey, true);
    document.body.style.overflow = "";
    if (openPanel === close) openPanel = null;
    prevFocus?.focus?.({ preventScroll: true });
  };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  shade.addEventListener("pointerdown", (e) => { if (e.target === shade) close(); });

  const d = () => models.data || {};
  /** gated repos that matter now: those apps wait for, and those of the pack asked for */
  const neededRepos = () => {
    const repos = new Set();
    for (const [, n] of visible(d().needs)) if (LICENSE_KINDS.includes(n.kind)) for (const r of n.repos || []) repos.add(r);
    if (focus.pack) for (const r of d().packs?.[focus.pack]?.gated || []) repos.add(r);
    return [...repos].sort();
  };
  /** the packs to download once the licenses are fine */
  const waitingPacks = () => {
    const packs = new Set(visible(d().needs).filter(([, n]) => LICENSE_KINDS.includes(n.kind)).map(([, n]) => n.pack));
    if (focus.pack && d().packs?.[focus.pack]?.missing) packs.add(focus.pack);
    return [...packs];
  };

  async function download(packs) {
    if (!packs.length || busy) return;
    busy = true;
    try {
      const r = await api("/api/models/download", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ packs }) });
      toast(r.queued ? t("models.queued.toast") : r.nothing ? t("models.nothing") : r.running ? t("models.running")
        : t("models.started", { packs: packs.join(", ") }));
    } catch (err) { toast(err.message, { error: true }); }
    finally { busy = false; await pollModels({ fresh: true }); }
  }

  async function check({ thenDownload = true } = {}) {
    const repos = neededRepos();
    if (!repos.length || checking) return;
    checking = true; draw();
    try { lic = await api(`/api/models/licenses?repos=${encodeURIComponent(repos.join(","))}`); }
    catch (err) { toast(err.message, { error: true }); }
    finally { checking = false; }
    draw();
    if (!lic || !thenDownload) return;
    if (lic.token !== "ok") toast(t(lic.token === "bad" ? "models.hf.bad" : "models.hf.need"), { error: true });
    else if (repos.every((r) => lic.repos[r] === "ok")) await download(waitingPacks());
    else toast(t("models.hf.notyet"), { error: true });
  }

  async function saveToken() {
    const value = tokenInput.value.trim();
    if (!value || busy) return;
    busy = true;
    try {
      const r = await api("/api/models/token", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ token: value }) });
      tokenInput.value = "";
      changing = false;
      toast(t("models.hf.saved", { user: r.user }));
      busy = false;
      await pollModels({ fresh: true });
      await check();
    } catch (err) { toast(err.message, { error: true }); }
    finally { busy = false; draw(); }
  }

  async function forgetToken() {
    try { await api("/api/models/token", { method: "DELETE" }); lic = null; await pollModels({ fresh: true }); }
    catch (err) { toast(err.message, { error: true }); }
  }

  function hfSection() {
    const repos = neededRepos();
    const tok = d().token || {};
    if (!repos.length && !tok.source) return null;
    const chip = (state) => {
      if (checking) return el("span", { class: "chip" }, t("models.lic.checking"));
      if (!state) return el("span", { class: "chip faint" }, "—");
      const cls = { ok: "ok", license: "warn", token: "warn", missing: "bad", unknown: "faint" }[state] ?? "faint";
      return el("span", { class: `chip ${cls}` }, state === "ok" ? icon("check") : null, t(`models.lic.${state}`));
    };
    const rows = repos.map((repo) => el("div", { class: "mrow" },
      el("div", { class: "two" },
        el("a", { href: `https://huggingface.co/${repo}`, target: "_blank", rel: "noopener" }, repo, " ", icon("ext")),
        el("small", { class: "dim" }, d().licenses?.[repo] || "")),
      chip(lic?.repos?.[repo])));
    const showInput = !tok.source || changing || lic?.token === "bad";
    const who = lic?.user ? `@${lic.user}` : null;
    const tokenRow = showInput
      ? el("div", { class: "mtoken-row" }, tokenInput,
          el("button", { class: "btn lime small", type: "button", onclick: saveToken, disabled: busy }, t("models.hf.save")))
      : el("div", { class: "mrow" },
          el("div", { class: "two" }, el("span", {}, icon("check"), " ", who ? t("models.hf.have", { user: who }) : t("models.hf.set")),
            el("small", { class: "dim" }, t(`models.hf.src.${tok.source}`))),
          el("div", { class: "row" },
            el("button", { class: "btn small ghost", type: "button", onclick: () => { changing = true; draw(); tokenInput.focus(); } }, t("models.hf.change")),
            tok.source === "studio" ? el("button", { class: "btn small ghost", type: "button", onclick: forgetToken }, t("models.hf.forget")) : null));
    if (!repos.length) {   // nothing waits for a license: just the token, to change or forget
      return el("section", { class: "msec" }, el("h3", {}, t("models.hf.token")), tokenRow,
        tok.problem && tok.source !== "studio" ? el("p", { class: "help warn" }, tok.problem) : null,
        showInput ? el("p", { class: "help" }, t("models.hf.keep")) : null);
    }
    return el("section", { class: "msec" },
      el("h3", {}, t("models.hf.title")),
      el("p", { class: "help" }, t("models.hf.intro")),
      el("p", { class: "step" }, t("models.hf.step1")),
      ...rows,
      el("p", { class: "step" }, t("models.hf.step2"), " ",
        el("a", { href: "https://huggingface.co/settings/tokens", target: "_blank", rel: "noopener" }, t("models.hf.create"), " ", icon("ext"))),
      tokenRow,
      tok.problem && tok.source !== "studio" ? el("p", { class: "help warn" }, tok.problem) : null,
      lic?.token === "bad" ? el("p", { class: "help warn" }, t("models.hf.bad")) : null,
      showInput ? el("p", { class: "help" }, t("models.hf.keep")) : null,
      el("div", { class: "row" },
        el("button", { class: "btn lime", type: "button", onclick: () => check(), disabled: checking || busy || !tok.source }, icon("download"), t("models.hf.check"))));
  }

  function packState(name, p) {
    const job = d().job?.state === "running" ? d().job : null;
    const needs = visible(d().needs).filter(([, n]) => n.pack === name).map(([, n]) => n.kind);
    if (!p.missing) return "ready";
    if (job?.packs?.includes(name) && !needs.some((k) => LICENSE_KINDS.includes(k))) return "downloading";
    if (d().queued?.includes(name)) return "queued";
    if (needs.some((k) => LICENSE_KINDS.includes(k))) return "license";
    if (needs.includes("failed")) return "failed";
    return "get";
  }

  function packsSection() {
    const packApps = d().pack_apps || {};
    const order = { downloading: 0, queued: 1, license: 2, failed: 3, ready: 4, get: 5 };
    const rows = Object.entries(d().packs || {})
      .map(([name, p]) => ({ name, p, apps: (packApps[name] || []).filter((id) => byId.has(id)), state: packState(name, p) }))
      .filter((r) => r.apps.length)
      .sort((a, b) => order[a.state] - order[b.state] || b.apps.length - a.apps.length);
    const free = d().free_gb ?? 0;
    return el("section", { class: "msec" },
      el("h3", {}, t("models.packs")),
      ...rows.map(({ name, p, apps: ids, state }) => {
        const names = ids.slice(0, 3).map((id) => byId.get(id).name).join(", ") + (ids.length > 3 ? "…" : "");
        let right;
        if (state === "ready") right = el("span", { class: "chip ok" }, icon("check"), t("models.pack.ready"));
        else if (state === "downloading") right = el("span", { class: "chip" }, t("models.pack.dl"));
        else if (state === "queued") right = el("span", { class: "chip" }, t("models.pack.queued"));
        else if (state === "license") right = el("button", { class: "btn small", type: "button", onclick: () => { focus = { pack: name }; draw(); box.querySelector(".msec")?.scrollIntoView({ behavior: "smooth" }); } }, t("models.pack.license"));
        else {
          const fits = p.missing_gb <= free - 2;
          right = el("button", { class: `btn small${state === "failed" ? "" : " lime"}`, type: "button", disabled: !fits || busy,
            title: fits ? null : t("models.pack.nodisk", { gb: gb(free) }),
            onclick: () => {
              if (p.gated.length && !d().token?.source) { focus = { pack: name }; draw(); box.scrollTo({ top: 0, behavior: "smooth" }); tokenInput.focus(); return; }
              download([name]);
            } }, icon(state === "failed" ? "redo" : "download"),
            state === "failed" ? t("models.pack.retry") : t("models.pack.get", { gb: gb(p.missing_gb) }));
        }
        return el("div", { class: `mrow${focus.pack === name ? " focus" : ""}` },
          el("div", { class: "two" },
            el("span", {}, el("b", {}, name), " ", el("span", { class: "dim" }, t(ids.length === 1 ? "models.pack.apps1" : "models.pack.apps", { n: ids.length }))),
            el("small", { class: "dim" }, names)),
          right);
      }),
      el("p", { class: "help" }, t("models.free", { gb: gb(free) })));
  }

  function draw() {
    const data = d();
    const job = data.job?.state === "running" ? data.job : null;
    box.replaceChildren(...[   // replaceChildren would write a null as the text "null"
      el("div", { class: "mhead" },
        el("h2", { class: "display" }, t("models.title")),
        el("button", { class: "icon-btn", type: "button", "aria-label": t("act.close"), onclick: close }, icon("x"))),
      data.gpu_problem ? el("p", { class: "mcallout bad" }, icon("info"), gpuProblemText(data.gpu_problem)) : null,
      job ? el("div", { class: "msec" },
        el("div", { class: "row" }, icon("download"), el("b", {}, t("models.dl", { done: gb(job.done_gb), total: gb(job.gb) }))),
        el("span", { class: "mbar wide" }, el("i", { style: { width: `${Math.min(100, (100 * job.done_gb) / (job.gb || 1))}%` } })),
        el("p", { class: "help" }, job.packs.join(", "), data.queued?.length ? ` · ${t("models.queued", { packs: data.queued.join(", ") })}` : "")) : null,
      data.available ? hfSection() : null,
      data.available ? packsSection() : el("p", { class: "help" }, t("models.unavailable"))].filter(Boolean));
  }

  models.listeners.add(draw);
  draw();
  document.body.append(shade);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKey, true);
  openPanel = close;
  (box.querySelector(".mtoken") || box.querySelector("button"))?.focus?.({ preventScroll: true });
  pollModels({ fresh: true });
  if (d().token?.source && neededRepos().length) check({ thenDownload: false });   // show what is accepted already
  return close;
}

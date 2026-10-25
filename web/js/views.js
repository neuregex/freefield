// The pages that are not a workspace: Explore (home), Apps (the store), Library and the VRAM map.
import { el, icon, masonry } from "./util.js";
import { t } from "./i18n.js";
import { apps, byId, CATEGORIES, HERO, START_HERE, hosted, tagline, iconOf, fitOf, categoryOf, studioOf, menuGroups } from "./catalog.js";
import { exampleItem, thumb, hoverPlay, optionTile } from "./media.js";
import { feed, feedView, hooks } from "./feed.js";
import { pickOption, recreate } from "./workspace.js";
import { flags, flagButton } from "./flags.js";

const go = (hash) => () => { location.hash = hash; };
const appTag = (a) => (a.status === "draft" ? el("span", { class: "tag dark" }, t("tag.draft")) : null);

function exampleTile(a, list) {
  const item = exampleItem(a);
  const node = el("div", { class: "m-item", role: "button", tabindex: "0", "aria-label": a.name },
    thumb(item, { play: "visible" }),
    flagButton(flags.key(a.id), { mini: true }),
    el("div", { class: "cap" }, el("span", {}, a.name), el("span", { class: "tag dark" }, t(`nav.${studioOf(a) === "apps" ? "apps" : studioOf(a)}`))));
  const open = () => hooks.open?.(list.map(exampleItem), item.key);
  node.addEventListener("click", open);
  node.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return node;
}

// ------------------------------------------------------------------ Explore
export function exploreView() {
  const withEx = apps.filter((a) => a.example?.full);
  const hero = HERO.map((id) => byId.get(id)).filter((a) => a?.example?.full);
  for (const a of withEx) if (hero.length < 6 && !hero.includes(a) && a.example.type === "video") hero.push(a);

  const row = el("div", { class: "hero-row" }, ...hero.map((a) => {
    const item = exampleItem(a);
    const card = el("div", { class: "hero-card", role: "link", tabindex: "0", onclick: go(`#/app/${a.id}`), onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/app/${a.id}`; } },
      thumb(item, { play: "visible", useFull: item.type === "video" }),
      el("div", { class: "txt" },
        el("div", { style: { display: "flex", gap: "6px" } }, el("span", { class: "tag" }, a.name), appTag(a)),
        el("h3", { class: "display" }, tagline(a)),
        el("p", {}, a.summary)));
    return card;
  }));
  const scroll = (d) => () => row.scrollBy({ left: d * row.clientWidth * 0.66, behavior: "smooth" });
  const prevBtn = el("button", { class: "hero-nav prev", type: "button", "aria-label": t("act.prev"), onclick: scroll(-1), hidden: true }, icon("chevL"));
  const nextBtn = el("button", { class: "hero-nav next", type: "button", "aria-label": t("act.next"), onclick: scroll(1) }, icon("chevR"));
  const arrows = () => {
    prevBtn.hidden = row.scrollLeft < 8;
    nextBtn.hidden = row.scrollLeft + row.clientWidth > row.scrollWidth - 8;
  };
  row.addEventListener("scroll", arrows, { passive: true });
  requestAnimationFrame(arrows);

  // the same apps the top bar's menu lists for that studio
  const count = (studio) => menuGroups(studio).reduce((n, g) => n + g.apps.length, 0);
  const tiles = [
    ["image", "image", "#/image", count("image")], ["video", "video", "#/video", count("video")], ["audio", "audio", "#/audio", count("audio")],
    ["apps", "layers", "#/apps", apps.length], ["library", "film", "#/library", null], ["vram", "chip", "#/vram", null],
  ].map(([key, ic, hash, n]) => el("a", { class: "tile6", href: hash },
    el("span", { class: "ic" }, icon(ic)),
    el("span", { class: "t" }, t(`tile.${key}.t`), n ? el("span", { class: "tag ghost" }, t("explore.apps", { n })) : null),
    el("p", {}, t(`tile.${key}.d`))));

  const grid = el("div");
  if (withEx.length) masonry(grid, withEx.map((a) => exampleTile(a, withEx)), { min: 250 });

  // apps with a gallery select (the effects) get a wall of their options, each playing its lab example
  const walls = apps.flatMap((a) => a.inputs.filter((i) => i.gallery && Object.keys(a.example?.options?.[i.id] || {}).length).map((inp) => {
    const shots = a.example.options[inp.id];
    return [
      el("div", { class: "sec-head" },
        el("div", {}, el("h2", { class: "display" }, a.name), el("p", {}, t("explore.gallery.sub"))),
        el("a", { class: "pill-link", href: `#/app/${a.id}` }, t("apps.try"), icon("chevR"))),
      el("div", { class: "fx-wall" }, ...(inp.options || []).filter((o) => shots[String(o.value)]).map((o) =>
        optionTile(o, shots[String(o.value)], { play: "visible", onPick: () => pickOption(a, inp.id, o.value), flagKey: flags.key(a.id, inp.id, o.value) }))),
    ];
  })).flat();

  // hosted demo: five apps one click away from a live run (their lab example goes into the form)
  const starters = hosted ? START_HERE.map((id) => byId.get(id)).filter((a) => a?.example?.full) : [];
  const start = starters.length ? [
    el("div", { class: "sec-head", style: { marginTop: "6px" } },
      el("div", {}, el("h2", { class: "display" }, t("start.title")), el("p", {}, t("start.sub")))),
    el("div", { class: "start5" }, ...starters.map((a) => {
      const item = exampleItem(a);
      const gpu = (item.gpu || "").split(",")[0].replace("NVIDIA ", "").replace(" 80GB HBM3", "");
      return el("button", { class: "start-card", type: "button", onclick: () => recreate(item) },
        thumb(item, { play: "visible" }),
        el("span", { class: "nm" }, a.name),
        el("span", { class: "dim" }, item.seconds ? t("start.secs", { s: Math.round(item.seconds), gpu: gpu || "GPU" }) : tagline(a)));
    })),
  ] : [];

  const node = el("div", { class: "page" },
    ...start,
    hero.length ? el("div", { class: "hero-wrap" }, row, prevBtn, nextBtn) : null,
    el("section", { class: "promo" },
      el("div", { class: "promo-lead" },
        el("h2", { class: "display" }, t("explore.lead.a"), " ", el("em", {}, t("explore.lead.b"))),
        el("p", {}, t("explore.lead.text")),
        el("div", { class: "row" },
          el("a", { class: "btn lime", href: "#/image" }, icon("spark"), t("explore.start")),
          el("a", { class: "btn ghost", href: "#/apps" }, t("explore.browse")))),
      el("div", { class: "tiles6" }, ...tiles)),
    ...walls,
    el("div", { class: "sec-head" },
      el("div", {}, el("h2", { class: "display" }, t("explore.made")), el("p", {}, t("explore.made.sub"))),
      el("a", { class: "pill-link", href: "#/apps" }, t("explore.seeall"), icon("ext"))),
    withEx.length ? grid : el("div", { class: "empty" }, t("explore.noex"), el("pre", { class: "code", style: { display: "inline-block", marginTop: "10px" } }, "modal run --detach lab/lab_modal.py --showcase")),
    el("div", { class: "sec-head" }, el("h2", { class: "display" }, t("explore.how"))),
    el("div", { class: "how" }, ...[1, 2, 3].map((n) => el("div", {}, el("span", { class: "n" }, `0${n}`), el("h3", {}, t(`how.${n}.t`)), el("p", {}, t(`how.${n}.d`))))));
  return { node, active: "explore", dispose: () => grid._ro?.disconnect() };
}

// ------------------------------------------------------------------ Apps
let appsCat = "all";
let appsQuery = "";

function appCard(a) {
  const item = exampleItem(a);
  const media = item ? thumb(item, { play: "hover" }) : el("div", { class: "media" }, el("span", { class: "placeholder" }, icon(iconOf(a))));
  const fit = fitOf(a);
  media.append(el("div", { class: "badges" },
    a.status === "draft" ? el("span", { class: "tag dark" }, t("tag.draft")) : null,
    fit && fit[1] === "big" ? el("span", { class: "tag violet" }, "48 GB") : null));
  const card = el("a", { class: "app-card", href: `#/app/${a.id}` }, media,
    el("h3", {}, a.name), el("p", {}, a.summary),
    el("span", { class: "btn white small" }, icon("play"), t("apps.try")));
  hoverPlay(card, media._video);
  return card;
}

export function appsView() {
  const body = el("div");
  const search = el("input", { type: "search", placeholder: t("apps.search"), value: appsQuery, "aria-label": t("apps.search") });
  const pills = el("div", { class: "pills", role: "group" });
  const cats = [...CATEGORIES.map((c) => c.id), ...(apps.some((a) => categoryOf(a.id) === "more") ? ["more"] : [])];
  const draw = () => {
    pills.replaceChildren(...["all", ...cats].map((c) => el("button", { type: "button", "aria-pressed": String(appsCat === c),
      onclick: () => { appsCat = c; draw(); } }, c === "all" ? t("apps.all") : t(`cat.${c}.t`))));
    const q = appsQuery.trim().toLowerCase();
    const match = (a) => !q || [a.name, a.summary, a.higgsfield_feature, a.id].filter(Boolean).join(" ").toLowerCase().includes(q);
    const sections = (appsCat === "all" ? cats : [appsCat]).map((c) => {
      const list = (c === "more" ? apps.filter((a) => categoryOf(a.id) === "more") : (CATEGORIES.find((x) => x.id === c)?.apps || []).map((id) => byId.get(id)).filter(Boolean)).filter(match);
      if (!list.length) return null;
      return el("section", {},
        el("div", { class: "sec-head" },
          el("div", {}, el("h2", { class: "display" }, t(`cat.${c}.t`)), t(`cat.${c}.d`) ? el("p", {}, t(`cat.${c}.d`)) : null),
          appsCat === "all" ? el("button", { class: "more", type: "button", style: { background: "none", border: 0, cursor: "pointer" }, onclick: () => { appsCat = c; draw(); window.scrollTo({ top: 0 }); } },
            t("apps.seeall"), icon("chevR")) : null),
        el("div", { class: "app-row" }, ...list.map(appCard)));
    }).filter(Boolean);
    body.replaceChildren(...(sections.length ? sections : [el("div", { class: "empty" }, t("apps.none", { q: appsQuery }))]));
  };
  search.addEventListener("input", () => { appsQuery = search.value; draw(); });
  draw();
  const node = el("div", { class: "page" },
    el("header", { class: "apps-head" },
      el("span", { class: "ic" }, icon("grid")),
      el("h1", { class: "display" }, t("apps.title.a"), " ", el("em", {}, t("apps.title.b"))),
      el("p", {}, t("apps.sub")),
      el("div", { class: "apps-bar" }, el("label", { class: "search" }, icon("search"), search), pills)),
    body);
  return { node, active: "apps" };
}

// ------------------------------------------------------------------ Library
let libTab = "mine";
let libApp = "";
let libFlagged = false;   // the lab tab: only the examples marked mediocre

/** The gallery options marked mediocre, as a wall (the lab tab's filter). */
function flaggedOptions() {
  return apps.flatMap((a) => a.inputs.filter((i) => i.gallery && a.example?.options?.[i.id]).flatMap((inp) => {
    const shots = a.example.options[inp.id];
    const list = (inp.options || []).filter((o) => shots[String(o.value)] && flags.is(flags.key(a.id, inp.id, o.value)));
    return list.length ? [el("div", { class: "sec-head" }, el("div", {}, el("h3", { class: "display" }, `${a.name} · ${inp.label}`))),
      el("div", { class: "fx-wall" }, ...list.map((o) => optionTile(o, shots[String(o.value)], { play: "visible", onPick: () => pickOption(a, inp.id, o.value), flagKey: flags.key(a.id, inp.id, o.value) })))] : [];
  }));
}

export function libraryView() {
  const tabs = el("div", { class: "tabs", role: "tablist" });
  const filter = el("div", { class: "pills" });
  const body = el("div", { style: { display: "flex", flexDirection: "column", minHeight: "40vh" } });
  let disposeFeed = null;
  const draw = () => {
    tabs.replaceChildren(...[["mine", "clock"], ["lab", "film"]].map(([id, ic]) => el("button", { type: "button", role: "tab", "aria-selected": String(libTab === id),
      onclick: () => { libTab = id; draw(); } }, icon(ic), t(`lib.${id}`))));
    disposeFeed?.();
    disposeFeed = null;
    if (libTab === "mine") {
      const used = [...new Set(feed.list().map((e) => e.app))].map((id) => byId.get(id)).filter(Boolean);
      filter.replaceChildren(...(used.length > 1 ? [["", t("lib.allapps")], ...used.map((a) => [a.id, a.name])] : []).map(([id, label]) =>
        el("button", { type: "button", "aria-pressed": String(libApp === id), onclick: () => { libApp = id; draw(); } }, label)));
      disposeFeed = feedView(body, { app: libApp || null, empty: () => el("div", { class: "empty" }, t("lib.empty"), " ", el("a", { class: "more", href: "#/image" }, t("explore.start"), icon("chevR"))) });
    } else {
      const n = flags.count();
      filter.replaceChildren(...(n || libFlagged ? [[false, t("lib.allex")], [true, t("lib.flagged", { n })]].map(([on, label]) =>
        el("button", { type: "button", "aria-pressed": String(libFlagged === on), onclick: () => { libFlagged = on; draw(); } }, label)) : []));
      const withEx = apps.filter((a) => a.example?.full && (!libFlagged || flags.is(flags.key(a.id))));
      const grid = el("div");
      masonry(grid, withEx.map((a) => exampleTile(a, withEx)), { min: 250 });
      const walls = libFlagged ? flaggedOptions() : [];
      body.replaceChildren(...(withEx.length || walls.length ? [grid, ...walls] : [el("div", { class: "empty" }, t(libFlagged ? "lib.noflag" : "explore.noex"))]));
    }
  };
  draw();
  const offFlags = flags.on(() => { if (libTab === "lab") draw(); });
  // the app filter appears once two apps have history; entries of apps outside the catalog (the smoke apps without ?dev) do not count
  const usedApps = () => new Set(feed.list().map((e) => e.app).filter((id) => byId.has(id))).size;
  const off = feed.on(() => { if (libTab === "mine" && filter.childElementCount === 0 && usedApps() > 1) draw(); });
  feed.load().catch(() => {});
  const node = el("div", { class: "page" },
    el("div", { class: "sec-head", style: { marginTop: "6px" } }, el("div", {}, el("h2", { class: "display", style: { fontSize: "34px" } }, t("lib.title")), el("p", {}, t("lib.sub")))),
    el("div", { style: { display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", marginBottom: "14px" } }, tabs, filter),
    body);
  return { node, active: "library", dispose: () => { disposeFeed?.(); off(); offFlags(); } };
}

// ------------------------------------------------------------------ VRAM map
export function vramView(gpu) {
  const list = apps.filter((a) => a.vram).sort((a, b) => b.vram.largest_phase_gb - a.vram.largest_phase_gb);
  const max = Math.max(48, ...list.map((a) => Math.max(a.vram.whole_gb, a.example?.peak_vram_gb || 0))) * 1.04;
  const pct = (gb) => `${Math.min(100, (gb / max) * 100)}%`;
  const rows = list.map((a) => {
    const fit = fitOf(a);
    const peak = a.example?.peak_vram_gb;
    return el("a", { class: "vrow", href: `#/app/${a.id}` },
      el("div", { class: "nm" }, el("b", {}, a.name), el("small", {}, `${a.pack} · ${a.vram.whole_gb} GB`)),
      el("div", { class: "vbar", title: `${t("vram.whole")} ${a.vram.whole_gb} GB · ${t("vram.phase")} ${a.vram.largest_phase_gb} GB${peak ? ` · ${t("vram.measured")} ${peak} GB` : ""}` },
        el("i", { class: "whole", style: { width: pct(a.vram.whole_gb) } }),
        el("i", { style: { width: pct(a.vram.largest_phase_gb) } }),
        peak ? el("b", { style: { left: pct(peak) } }) : null,
        el("u", { style: { left: pct(24) } }), el("u", { style: { left: pct(48) } })),
      el("span", { class: `fit ${fit?.[1] || ""}` }, fit ? t(fit[0]) : ""));
  });
  const live = gpu?.device?.vram_total_gb ? el("div", { class: "card", style: { marginBottom: "14px" } },
    el("h3", {}, icon("bolt"), t("vram.live", { name: gpu.device.name || "GPU", used: gpu.device.vram_used_gb, total: gpu.device.vram_total_gb })),
    el("div", { class: "vbar" }, el("i", { style: { width: `${(gpu.device.vram_used_gb / gpu.device.vram_total_gb) * 100}%` } }))) : null;
  const node = el("div", { class: "page" },
    el("div", { class: "sec-head", style: { marginTop: "6px" } }, el("div", {}, el("h2", { class: "display", style: { fontSize: "34px" } }, t("vram.title")), el("p", { style: { maxWidth: "80ch" } }, t("vram.sub")))),
    live,
    el("div", { class: "legend", style: { margin: "0 0 12px" } },
      el("span", {}, el("i", { style: { background: "rgba(255,255,255,.14)" } }), t("vram.whole")),
      el("span", {}, el("i", { style: { background: "var(--accent)" } }), t("vram.phase")),
      el("span", {}, el("i", { style: { background: "var(--pink)", width: "3px" } }), t("vram.measured"))),
    el("div", { class: "vrow", style: { background: "transparent", border: 0, cursor: "default", padding: "0 12px" } }, el("span"),
      el("div", { class: "vscale" }, el("span", { style: { left: pct(24) } }, "24 GB"), el("span", { style: { left: pct(48) } }, "48 GB")), el("span")),
    el("div", { class: "vtable" }, ...rows));
  return { node, active: "vram" };
}

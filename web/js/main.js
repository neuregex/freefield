// Boot and routing. Each route builds a view ({ node, dispose, active }) into <main>.
//   #/                 Explore         #/apps      the app store       #/app/<id>  an app's workspace
//   #/image #/video #/audio            the studios (open the last app used there)
//   #/library          history and lab examples                       #/vram      the VRAM map
import { el, closePopover, toast } from "./util.js";
import { t } from "./i18n.js";
import { loadCatalog, byId, lastAppFor, studioOf, FEATURED } from "./catalog.js";
import { topbar, gpuState, pollGpu } from "./nav.js";
import { exploreView, appsView, libraryView, vramView } from "./views.js";
import { workspaceView, recreate } from "./workspace.js";
import { hooks, feed } from "./feed.js";
import { openViewer } from "./viewer.js";
import { openCompare } from "./compare.js";
import { flags } from "./flags.js";

const main = el("main", { id: "main", class: "view" });
let bar = null;
let current = null;

function route() {
  const hash = location.hash || "#/";
  const m = /^#\/app\/([\w-]+)/.exec(hash);
  if (m) {
    const view = workspaceView(m[1]);
    const app = view.app;
    const featured = app && FEATURED.some((f) => f.id === app.id);
    return { ...view, active: app ? (featured ? app.id : studioOf(app)) : "apps" };
  }
  const studio = /^#\/(image|video|audio)$/.exec(hash);
  if (studio) {
    location.replace(`#/app/${lastAppFor(studio[1])}`);
    return null;
  }
  if (hash.startsWith("#/apps")) return appsView();
  if (hash.startsWith("#/library")) return libraryView();
  if (hash.startsWith("#/vram")) return vramView(gpuState.data?.device ? gpuState.data : null);
  return exploreView();
}

function render({ keepScroll = false } = {}) {
  closePopover();
  const view = route();
  if (!view) return;   // redirected
  current?.dispose?.();
  current = view;
  main.replaceChildren(view.node);
  bar?.update(view.active);
  if (!keepScroll) window.scrollTo(0, 0);
  const app = view.app;
  document.title = app ? `${app.name} · Freefield` : "Freefield";
}

function buildBar() {
  const next = topbar({ onLang: () => { buildBar(); render({ keepScroll: true }); } });
  if (bar) bar.node.replaceWith(next.node); else document.body.prepend(next.node);
  bar = next;
}

hooks.open = (items, key) => openViewer(items, key);
hooks.recreate = (item) => recreate(item);
hooks.retry = (item) => recreate(item, { run: true });
hooks.compare = (item) => openCompare(item);
hooks.rerender = () => render({ keepScroll: true });

// a run starting or ending changes what the GPU pill should say
let activeRuns = 0;
feed.on(() => {
  const n = feed.active().length;
  if (n !== activeRuns) { activeRuns = n; pollGpu(); }
});

async function boot() {
  document.body.append(main);
  try {
    await loadCatalog();
    await flags.load();
  } catch (err) {
    main.replaceChildren(el("div", { class: "page" }, el("div", { class: "empty" }, `${err.message}. Is \`npm run serve\` running?`)));
    return;
  }
  buildBar();
  window.addEventListener("hashchange", () => render());
  render();
}

window.addEventListener("unhandledrejection", (e) => {
  if (e.reason?.name === "AbortError") return;
  toast(String(e.reason?.message || e.reason), { error: true });
});
boot();
export { byId, t };

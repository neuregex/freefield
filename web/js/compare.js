// Compare a Freefield result with another one: a file from Higgsfield (or anywhere), or another
// generation. Images side by side or as a wipe; videos side by side with one transport, kept in sync.
// Dropped files stay in the browser (object URLs); nothing is uploaded.
import { el, icon, fmtSeconds } from "./util.js";
import { t } from "./i18n.js";
import { byId } from "./catalog.js";
import { feed } from "./feed.js";
import { entryItem } from "./media.js";

function mediaEl(side) {
  if (side.type === "video") {
    const v = el("video", { src: side.url, playsinline: true, loop: true, preload: "auto", muted: true });
    v.muted = true;
    return v;
  }
  if (side.type === "audio") return el("audio", { src: side.url, controls: true, preload: "metadata" });
  return el("img", { src: side.url, alt: side.label });
}

function kindOfFile(file) {
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  return "image";
}

async function sizeOf(url) {
  try {
    const r = await fetch(url, { method: "HEAD" });
    const n = Number(r.headers.get("content-length"));
    return n > 0 ? n : null;
  } catch { return null; }
}
const mb = (n) => (n ? `${(n / 1e6).toFixed(n > 1e7 ? 0 : 1)} MB` : "");

export function openCompare(item) {
  const app = byId.get(item.app);
  const left = { label: `Freefield · ${app?.name ?? item.app}`, type: item.type, url: item.full, size: null };
  let right = null;
  let mode = "side";
  const root = el("div", { class: "cmpx", role: "dialog", "aria-modal": "true" });
  const urls = [];
  const close = () => {
    root.remove();
    urls.forEach((u) => URL.revokeObjectURL(u));
    document.removeEventListener("keydown", onKey, true);
    clearInterval(sync);
    document.body.style.overflow = "";
  };
  const onKey = (e) => { if (e.key === "Escape" && !e.target.closest?.("input")) { e.stopPropagation(); close(); } };
  let sync = null;

  const setRightFile = (file) => {
    const url = URL.createObjectURL(file);
    urls.push(url);
    right = { label: store.lastLabel || "Higgsfield", type: kindOfFile(file), url, size: file.size, name: file.name };
    draw();
  };
  const store = { lastLabel: null };

  function pane(side, which) {
    if (!side) {
      const input = el("input", { type: "file", accept: "image/*,video/*,audio/*", hidden: true });
      input.addEventListener("change", () => input.files[0] && setRightFile(input.files[0]));
      const zone = el("div", { class: "drop", role: "button", tabindex: "0", onclick: () => input.click(),
        onkeydown: (e) => { if (e.key === "Enter") input.click(); } },
        el("span", { class: "ic" }, icon("upload")), el("b", {}, t("cmp.drop")), el("small", {}, t("cmp.local")), input);
      zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
      zone.addEventListener("dragleave", () => zone.classList.remove("over"));
      zone.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setRightFile(f); });
      const mine = feed.list().filter((e) => e.status === "succeeded" && e.outputs[0]?.type === left.type && e.outputs[0]?.url !== left.url).slice(0, 12);
      return el("div", { class: "pane" },
        el("div", { class: "lab" }, el("b", {}, t("cmp.other"))),
        el("div", { class: "box" }, zone),
        mine.length ? el("div", { style: { display: "grid", gap: "6px" } }, el("small", { class: "dim" }, t("cmp.pick")),
          el("div", { style: { display: "flex", gap: "6px", overflowX: "auto" } }, ...mine.map((e) => {
            const it = entryItem(e);
            return el("button", { type: "button", style: { flex: "none", width: "64px", height: "64px", borderRadius: "10px", overflow: "hidden", border: "1px solid #2a2a2f", padding: 0, background: "#000", cursor: "pointer" },
              title: byId.get(e.app)?.name ?? e.app,
              onclick: () => { right = { label: `Freefield · ${byId.get(e.app)?.name ?? e.app}`, type: it.type, url: it.full, size: null }; draw(); } },
              it.type === "video" ? el("video", { src: `${it.full}#t=0.1`, muted: true, preload: "metadata", style: { width: "100%", height: "100%", objectFit: "cover" } })
                : el("img", { src: it.full, alt: "", style: { width: "100%", height: "100%", objectFit: "cover" } }));
          }))) : el("div"));
    }
    const m = mediaEl(side);
    const info = el("div", { class: "info" });
    const label = el("input", { value: side.label, "aria-label": "label" });
    label.addEventListener("input", () => { side.label = label.value; if (which === "right") store.lastLabel = label.value; });
    const fill = async () => {
      const bits = [];
      if (m.tagName === "IMG" && m.naturalWidth) bits.push(`${m.naturalWidth}×${m.naturalHeight}`);
      if (m.tagName === "VIDEO" && m.videoWidth) bits.push(`${m.videoWidth}×${m.videoHeight}`, fmtSeconds(m.duration));
      if (m.tagName === "AUDIO" && m.duration) bits.push(fmtSeconds(m.duration));
      side.size ??= await sizeOf(side.url);
      if (side.size) bits.push(mb(side.size));
      info.replaceChildren(...bits.map((b) => el("span", {}, b)));
    };
    m.addEventListener(m.tagName === "IMG" ? "load" : "loadedmetadata", fill);
    return el("div", { class: "pane" },
      el("div", { class: "lab" }, label, which === "right" ? el("button", { class: "mini", type: "button", title: t("cmp.clear"), "aria-label": t("cmp.clear"),
        onclick: () => { right = null; draw(); } }, icon("x")) : null),
      el("div", { class: "box" }, m), info);
  }

  function wipe() {
    let x = 50;
    const a = el("img", { src: left.url, alt: left.label });
    const b = el("img", { src: right.url, alt: right.label });
    const handle = el("div", { class: "handle" });
    const box = el("div", { class: "wipe" }, b, a, handle, el("span", { class: "tagl" }, left.label), el("span", { class: "tagr" }, right.label));
    const paint = () => { a.style.clipPath = `inset(0 ${100 - x}% 0 0)`; handle.style.left = `${x}%`; };
    const move = (e) => { const r = box.getBoundingClientRect(); x = Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100)); paint(); };
    box.addEventListener("pointerdown", (e) => { box.setPointerCapture(e.pointerId); move(e); });
    box.addEventListener("pointermove", (e) => { if (box.hasPointerCapture(e.pointerId)) move(e); });
    box.tabIndex = 0;
    box.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") { x = Math.max(0, x - 2); paint(); } if (e.key === "ArrowRight") { x = Math.min(100, x + 2); paint(); } });
    paint();
    return box;
  }

  function transport(videos) {
    const [va, vb] = videos;
    const play = el("button", { class: "btn small lime", type: "button" }, icon("play"), t("cmp.both"));
    const seek = el("input", { type: "range", min: 0, max: 1000, value: 0, "aria-label": "seek" });
    const time = el("span", { class: "t" }, "0.0 s");
    const dur = () => Math.max(va.duration || 0, vb.duration || 0);
    const setPlaying = (on) => play.replaceChildren(icon(on ? "pause" : "play"), t("cmp.both"));
    play.onclick = () => {
      if (va.paused) {
        vb.currentTime = Math.min(va.currentTime, vb.duration || 0);
        Promise.all([va.play(), vb.play()]).catch(() => {});
        setPlaying(true);
      } else { va.pause(); vb.pause(); setPlaying(false); }
    };
    seek.addEventListener("input", () => {
      const s = (seek.value / 1000) * dur();
      for (const v of videos) v.currentTime = Math.min(s, v.duration || 0);
    });
    va.addEventListener("timeupdate", () => {
      const d = dur();
      if (d) seek.value = String(Math.round((va.currentTime / d) * 1000));
      time.textContent = `${va.currentTime.toFixed(1)} / ${d.toFixed(1)} s`;
    });
    const mute = (v, which) => {
      const b = el("button", { class: "btn small ghost", type: "button", title: which }, icon("mute"), which);
      b.onclick = () => { v.muted = !v.muted; b.replaceChildren(icon(v.muted ? "mute" : "volume"), which); };
      return b;
    };
    clearInterval(sync);
    sync = setInterval(() => {   // keep the right clip on the left clip's clock
      if (!va.paused && !vb.paused && vb.duration && va.currentTime < vb.duration && Math.abs(va.currentTime - vb.currentTime) > 0.12) vb.currentTime = va.currentTime;
    }, 400);
    return el("footer", {}, play, seek, time, mute(va, "A"), mute(vb, "B"));
  }

  function draw() {
    clearInterval(sync);
    const bothImages = right && left.type === "image" && right.type === "image";
    if (!bothImages && mode === "wipe") mode = "side";
    const header = el("header", {},
      el("h2", { class: "display" }, t("cmp.title")),
      bothImages ? el("div", { class: "tabs" }, ...[["side", t("cmp.side")], ["wipe", t("cmp.wipe")]].map(([id, label]) =>
        el("button", { type: "button", "aria-selected": String(mode === id), onclick: () => { mode = id; draw(); } }, label))) : null,
      el("span", { class: "grow" }),
      right ? el("button", { class: "btn small ghost", type: "button", onclick: () => { const r = right; right = { ...left }; Object.assign(left, r); draw(); } }, icon("swap"), t("cmp.swap")) : null,
      el("button", { class: "icon-btn", type: "button", title: t("act.close"), "aria-label": t("act.close"), onclick: close }, icon("x")));
    let body, footer = null;
    if (mode === "wipe" && bothImages) body = wipe();
    else {
      const pa = pane(left, "left"), pb = pane(right, "right");
      body = el("div", { class: "panes" }, pa, pb);
      const vids = [pa, pb].map((p) => p.querySelector("video")).filter(Boolean);
      if (vids.length === 2) footer = transport(vids);
      else if (vids.length === 1) { vids[0].controls = true; }
    }
    root.replaceChildren(header, body, footer || el("div"));
  }

  root.addEventListener("dragover", (e) => e.preventDefault());
  root.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setRightFile(f); });
  draw();
  document.body.append(root);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKey, true);
  return close;
}

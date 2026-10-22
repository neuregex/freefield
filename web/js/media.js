// One shape for everything the UI shows as a result, whether it came from the lab (an example)
// or from a run started here (a history entry), plus the elements that display them.
import { el, icon, extOf } from "./util.js";
import { byId } from "./catalog.js";
import { flagButton } from "./flags.js";

/** A lab example (web/examples/index.json via /api/apps) as a result item. */
export function exampleItem(app) {
  const ex = app?.example;
  if (!ex) return null;
  const labels = Object.fromEntries(app.inputs.map((i) => [i.id, i]));
  return {
    kind: "example", key: `ex:${app.id}`, app: app.id, type: ex.type, card: ex.card || ex.full, poster: ex.poster, full: ex.full,
    outputs: [{ type: ex.type, url: ex.full, poster: ex.poster }],
    inputs: (ex.inputs || []).filter((i) => i.src || i.full).map((i) => ({
      id: i.id, label: labels[i.id]?.label || i.label || i.id, type: i.type || labels[i.id]?.type,
      thumb: i.src || null, file: i.full || i.src, play: i.type === "video" || i.type === "audio" ? i.full : null,
    })),
    values: ex.values || {}, seed: ex.seed ?? null, seconds: ex.seconds ?? null, total: null, gpu: ex.gpu || null,
    peak: ex.peak_vram_gb ?? null, created: null, status: "succeeded",
  };
}

/** A history entry (/api/history) as a result item. */
export function entryItem(e) {
  const app = byId.get(e.app);
  const labels = Object.fromEntries((app?.inputs || []).map((i) => [i.id, i]));
  const first = e.outputs[0];
  return {
    kind: "history", key: e.id, id: e.id, app: e.app, status: e.status,
    type: first?.type || app?.outputs?.[0]?.type || "image",
    card: first?.url || null, poster: null, full: first?.url || null,
    outputs: e.outputs.map((o) => ({ type: o.type, url: o.url, name: o.name })),
    inputs: e.inputs.map((i) => ({ id: i.id, label: labels[i.id]?.label || i.id, type: i.type, thumb: i.type === "image" ? i.url : null, file: i.url,
      play: i.type === "image" ? null : i.url, name: i.name })),
    values: e.values || {}, seed: e.values?.seed ?? null, preset: e.preset, seconds: e.seconds, total: e.total, created: e.created,
    started: e.started, error: e.error, progress: e.progress, queue: e.queue, preview: e.preview, gpu: null, peak: null,
  };
}

// videos in grids play while on screen and pause when scrolled away
const visible = new IntersectionObserver((entries) => {
  for (const en of entries) {
    const v = en.target;
    if (en.isIntersecting) v.play().catch(() => {});
    else v.pause();
  }
}, { threshold: 0.35 });

export function playWhenVisible(video) { visible.observe(video); return video; }
export function hoverPlay(node, video) {
  if (!video) return;
  node.addEventListener("mouseenter", () => video.play().catch(() => {}));
  node.addEventListener("mouseleave", () => { video.pause(); });
  node.addEventListener("focusin", () => video.play().catch(() => {}));
  node.addEventListener("focusout", () => video.pause());
}

function loopVideo(src, poster, preload = "none") {
  const v = el("video", { src, poster: poster || null, loop: true, playsinline: true, preload, muted: true, disablepictureinpicture: true });
  v.muted = true;
  return v;
}

/**
 * The picture of an item for a card: an image, a muted loop or a waveform.
 * play: "hover" (the caller wires it with hoverPlay), "visible" (plays while on screen) or "none".
 */
export function thumb(item, { play = "visible", useFull = false, cls = "" } = {}) {
  const box = el("div", { class: `media ${cls}`.trim() });
  if (!item) return box;
  const src = useFull ? item.full || item.card : item.card || item.full;
  if (item.type === "video" && src) {
    const isHistory = item.kind === "history";
    const v = loopVideo(isHistory ? `${src}#t=0.1` : src, item.poster, isHistory ? "metadata" : "none");
    box.append(v);
    box._video = v;
    if (play === "visible") playWhenVisible(v);
  } else if (item.type === "audio") {
    box.classList.add("audio", "wave");
    if (item.card && extOf(item.card) === "png") box.append(el("img", { src: item.card, alt: "", loading: "lazy" }));
    else if (item.full) box.append(waveform(item.full));
    box.append(el("span", { class: "typeicon" }, icon("audio")));
  } else if (src) {
    box.append(el("img", { src, alt: "", loading: "lazy", decoding: "async", class: extOf(src) === "png" ? "alpha" : null }));
  }
  return box;
}

/** A gallery option's lab example (web/examples/<app>/options/...): a muted loop with its poster, or a still. */
export function optionThumb(shot, { play = "visible" } = {}) {
  return thumb({ kind: "example", type: shot.type, card: shot.card, poster: shot.poster, full: null }, { play });
}

/**
 * One option of a gallery select as a card: its example (or a placeholder) and its label.
 * flagKey: the example's key in lab/flags.json; with one, the card gets the "mediocre" toggle in its corner.
 */
export function optionTile(opt, shot, { selected = false, play = "hover", onPick, flagKey = null } = {}) {
  const media = shot ? optionThumb(shot, { play }) : el("div", { class: "media" }, el("span", { class: "placeholder" }, icon("spark")));
  const tile = el("button", { class: "fx-tile", type: "button", "aria-pressed": String(selected), onclick: onPick }, media, el("span", { class: "lbl" }, opt.label));
  if (play === "hover") hoverPlay(tile, media._video);
  if (!flagKey || !shot) return tile;
  return el("div", { class: "fx-cell" }, tile, flagButton(flagKey, { mini: true }));
}

/** A playable, full-size element for the viewer and the library. */
export function fullMedia(type, src, { poster, autoplay = true } = {}) {
  if (!src) return el("div", { class: "empty" }, "—");
  if (type === "video") {
    const v = el("video", { src, poster: poster || null, controls: true, loop: true, playsinline: true, preload: "auto", autoplay: autoplay || null });
    return v;
  }
  if (type === "audio") {
    return el("div", { class: "audio-box" }, el("div", { class: "media audio wave", style: { borderRadius: "12px", aspectRatio: "4 / 1" } }, waveform(src)),
      el("audio", { src, controls: true, preload: "metadata", autoplay: autoplay || null }));
  }
  return el("img", { src, alt: "", class: extOf(src) === "png" ? "alpha" : null });
}

/** A waveform drawn from the audio file itself (decoded lazily, once it is on screen). */
export function waveform(url) {
  const canvas = el("canvas", { width: 640, height: 160, style: { width: "100%", height: "auto", display: "block" } });
  const io = new IntersectionObserver(async (entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    try {
      const buf = await (await fetch(url)).arrayBuffer();
      const ctx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(1, 1, 44100);
      const audio = await ctx.decodeAudioData(buf);
      const data = audio.getChannelData(0);
      const g = canvas.getContext("2d");
      const bars = 96, step = Math.floor(data.length / bars), w = canvas.width / bars;
      g.fillStyle = "#e8ff5a";
      for (let b = 0; b < bars; b++) {
        let peak = 0;
        for (let i = b * step; i < (b + 1) * step; i += 64) peak = Math.max(peak, Math.abs(data[i] || 0));
        const h = Math.max(3, Math.sqrt(peak) * canvas.height * 0.9);
        g.fillRect(b * w + 1.5, (canvas.height - h) / 2, w - 3, h);
      }
    } catch { /* leave it blank */ }
  });
  io.observe(canvas);
  return canvas;
}

/** File name for a download link. */
export function downloadName(item, url) {
  const ext = extOf(url) || (item.type === "video" ? "mp4" : item.type === "audio" ? "mp3" : "png");
  return `freefield-${item.app}-${item.kind === "history" ? item.id : "example"}.${ext}`;
}

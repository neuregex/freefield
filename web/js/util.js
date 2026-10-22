// Small helpers shared by every view: DOM building, icons, the JSON API, per-viewer storage,
// toasts and popovers. No framework; each view builds its DOM and gives back a cleanup function.

/** el("button", { class: "btn", onclick }, "text", child) */
export function el(tag, attrs = {}, ...kids) {
  const e = tag === "svg" || attrs?.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false || k === "svg") continue;
    if (k === "class") e.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "value" && "value" in e) e.value = v;
    else if (k === "checked" || k === "muted" || k === "disabled" && "disabled" in e) e[k] = Boolean(v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false || k === "") continue;
    e.append(k?.nodeType ? k : document.createTextNode(String(k)));
  }
  return e;
}

// 24×24 stroke icons drawn for Freefield
const P = {
  plus: "M12 5v14M5 12h14",
  chevR: "M9 6l6 6-6 6", chevL: "M15 6l-6 6 6 6", chevD: "M6 9l6 6 6-6",
  image: "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z|M21 15l-5-5-9 9|C9 9.5 1.6",
  video: "M4 6h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z|M16 10.5l5-3v9l-5-3",
  audio: "M9 18V6l11-2v12|C6 18 3|C17 16 3",
  download: "M12 4v11|M7 10l5 5 5-5|M5 20h14",
  trash: "M4 7h16|M10 11v6|M14 11v6|M6 7l1 13h10l1-13|M9 7V4h6v3",
  compare: "M12 3v18|M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z|M7 12l-2 0|M19 12l-2 0",
  play: "F M8 5.5v13l11-6.5z",
  pause: "M8 5v14|M16 5v14",
  x: "M6 6l12 12|M18 6L6 18",
  search: "C11 11 7|M20 20l-4-4",
  globe: "C12 12 9|M3 12h18|M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3z",
  code: "M8 8l-4 4 4 4|M16 8l4 4-4 4|M13.5 5l-3 14",
  dice: "M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z|D 8.5 8.5|D 15.5 8.5|D 12 12|D 8.5 15.5|D 15.5 15.5",
  sliders: "M4 7h9|M17 7h3|M4 17h3|M11 17h9|C15 7 2|C9 17 2",
  copy: "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z|M16 9V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3",
  redo: "M4 12a8 8 0 1 0 2.4-5.7|M4 4v5h5",
  upload: "M12 16V4|M7 9l5-5 5 5|M5 20h14",
  grid: "M4 4h7v7H4z|M13 4h7v7h-7z|M4 13h7v7H4z|M13 13h7v7h-7z",
  rows: "M4 5h16v6H4z|M4 13h16v6H4z",
  clock: "C12 12 9|M12 7v5l3 2",
  chip: "M7 7h10v10H7z|M10 3v4|M14 3v4|M10 17v4|M14 17v4|M3 10h4|M3 14h4|M17 10h4|M17 14h4",
  swap: "M7 7h12l-3-3|M17 17H5l3 3",
  wand: "M5 19L15 9|M13 7l4 4|M18 3v3|M16.5 4.5h3|M20 9v2|M19 10h2",
  ext: "M14 4h6v6|M20 4l-9 9|M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  layers: "M12 3l9 5-9 5-9-5z|M3 13l9 5 9-5",
  info: "C12 12 9|M12 11v5|D 12 8",
  check: "M5 12.5l4.5 4.5L19 7.5",
  stop: "F M7 7h10v10H7z",
  bolt: "F M13 2L4.5 13.5H11L10 22l8.5-11.5H12z",
  film: "M4 4h16v16H4z|M8 4v16|M16 4v16|M4 9h4|M4 15h4|M16 9h4|M16 15h4",
  compass: "C12 12 9|F M15.5 8.5l-2 5-5 2 2-5z",
  spark: "F M12 2.5l1.9 6.1 6.1 1.9-6.1 1.9L12 18.5l-1.9-6.1L4 10.5l6.1-1.9z|F M19 15l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1L16 18l2.1-.9z",
  volume: "M4 9v6h4l5 4V5L8 9z|M16.5 8.5a5 5 0 0 1 0 7",
  mute: "M4 9v6h4l5 4V5L8 9z|M17 9l5 6|M22 9l-5 6",
  camera: "M4 8h3l2-3h6l2 3h3v11H4z|C12 13 3.5",
  user: "C12 8 4|M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6",
  hand: "M8 13V6a1.5 1.5 0 0 1 3 0v6|M11 11V4.5a1.5 1.5 0 0 1 3 0V11|M14 11V6a1.5 1.5 0 0 1 3 0v8c0 4-2.5 7-6 7-2.5 0-4-1.2-5.2-3L3.6 14a1.5 1.5 0 0 1 2.4-1.8L8 15",
  scissors: "C6 7 2.5|C6 17 2.5|M8 8.5L20 18|M8 15.5L20 6",
  box: "M12 3l8 4.5v9L12 21l-8-4.5v-9z|M12 12l8-4.5|M12 12v9|M12 12L4 7.5",
  sun: "C12 12 4|M12 2v2|M12 20v2|M4.9 4.9l1.4 1.4|M17.7 17.7l1.4 1.4|M2 12h2|M20 12h2|M4.9 19.1l1.4-1.4|M17.7 6.3l1.4-1.4",
  menu: "M4 7h16|M4 12h16|M4 17h16",
  thumbdown: "M17 4v10|M7 13.5l3 6.5c1.6 0 2.5-1 2.5-2.5V15h5.3c1 0 1.8-1 1.6-2L18.3 5.3c-.1-.8-.8-1.3-1.6-1.3H7z",
};

/** icon("image") → an inline SVG (stroke = currentColor). Path syntax: "|" separates parts; C cx cy r = circle; D x y = dot; "F " = filled path. */
export function icon(name, cls = "") {
  const svg = el("svg", { svg: true, class: `i i-${name} ${cls}`.trim(), viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
  for (const part of (P[name] || "").split("|")) {
    const circle = /^([CD])\s*([\d.]+)\s+([\d.]+)(?:\s+([\d.]+))?$/.exec(part.trim());
    if (circle?.[1] === "C") {
      svg.append(el("circle", { svg: true, cx: circle[2], cy: circle[3], r: circle[4] }));
    } else if (circle?.[1] === "D") {
      svg.append(el("circle", { svg: true, cx: circle[2], cy: circle[3], r: "1.1", fill: "currentColor", stroke: "none" }));
    } else if (part.startsWith("F ")) {
      svg.append(el("path", { svg: true, d: part.slice(2), fill: "currentColor", stroke: "none" }));
    } else if (part) {
      svg.append(el("path", { svg: true, d: part }));
    }
  }
  return svg;
}

/** The Freefield mark: three rows of a field, the middle one free. */
export function logoMark() {
  const svg = el("svg", { svg: true, class: "mark", viewBox: "0 0 32 32", "aria-hidden": "true" });
  svg.append(
    el("rect", { svg: true, x: "1", y: "1", width: "30", height: "30", rx: "9", fill: "#e8ff5a" }),
    el("path", { svg: true, d: "M8 11.5h16", stroke: "#11140a", "stroke-width": "3", "stroke-linecap": "round" }),
    el("path", { svg: true, d: "M8 16.5h9", stroke: "#11140a", "stroke-width": "3", "stroke-linecap": "round" }),
    el("circle", { svg: true, cx: "22.5", cy: "16.5", r: "1.9", fill: "#11140a" }),
    el("path", { svg: true, d: "M8 21.5h12", stroke: "#11140a", "stroke-width": "3", "stroke-linecap": "round" }),
  );
  return svg;
}

/** Small bits of live state shared between modules (the GPU pill writes, cards read). */
export const live = { gpuWarm: false };

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

/** fetch → JSON; a non-2xx answer throws with the server's message. */
export async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError(body?.error || `${res.status} ${res.statusText}`, res.status);
  return body;
}

/** Per-viewer conveniences (language, drafts, last app). Storage can be missing or throw: never rely on it. */
export const store = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem(`ff.${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`ff.${key}`, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

export function fmtSeconds(s) {
  if (s === null || s === undefined || !Number.isFinite(Number(s))) return "";
  s = Number(s);
  if (s < 10) return `${s.toFixed(1).replace(/\.0$/, "")} s`;
  if (s < 90) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m} min${r ? ` ${String(r).padStart(2, "0")} s` : ""}`;
}

/** Rough duration for buttons: "18 s", "~6 min". */
export function fmtShort(s) {
  if (!Number.isFinite(Number(s))) return "";
  s = Number(s);
  return s < 90 ? `${Math.round(s)} s` : `~${Math.round(s / 60)} min`;
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const isMedia = (type) => type === "image" || type === "video" || type === "audio";
export const extOf = (url) => (/\.([a-z0-9]+)(?:\?|#|$)/i.exec(url || "")?.[1] || "").toLowerCase();

/** A short-lived message at the bottom of the screen. */
export function toast(message, { error = false, ms = 4200 } = {}) {
  let host = document.querySelector(".toast-host");
  if (!host) document.body.append(host = el("div", { class: "toast-host", role: "status", "aria-live": "polite" }));
  const t = el("div", { class: `toast${error ? " err" : ""}` }, message);
  host.append(t);
  setTimeout(() => t.remove(), error ? Math.max(ms, 8000) : ms);
}

let openPop = null;
/** A popover anchored to a button; opens upwards when there is no room below. Returns a close function. */
export function popover(anchor, content, { onClose, align = "start", width, cls = "" } = {}) {
  closePopover();
  const pop = el("div", { class: `pop ${cls}`.trim(), role: "dialog" }, content);
  if (width) pop.style.width = `${width}px`;
  document.body.append(pop);
  const place = () => {
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = align === "end" ? r.right - pw : r.left;
    left = clamp(left, 12, window.innerWidth - pw - 12);
    const below = window.innerHeight - r.bottom, above = r.top;
    const top = below >= ph + 12 || below > above ? r.bottom + 8 : r.top - ph - 8;
    pop.style.left = `${left}px`;
    pop.style.top = `${clamp(top, 12, window.innerHeight - ph - 12)}px`;
  };
  place();
  const away = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
  const key = (e) => { if (e.key === "Escape") { close(); anchor.focus?.(); } };
  const close = () => {
    if (!pop.isConnected) return;
    pop.remove();
    document.removeEventListener("pointerdown", away, true);
    document.removeEventListener("keydown", key, true);
    window.removeEventListener("resize", close);
    if (openPop === close) openPop = null;
    onClose?.();
  };
  setTimeout(() => {
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", key, true);
    window.addEventListener("resize", close);
  });
  openPop = close;
  pop.querySelector("[autofocus], input, textarea, .opt[aria-selected='true'], .opt")?.focus?.({ preventScroll: true });
  return close;
}
export function closePopover() { openPop?.(); }

/** Debounce for resize and typing. */
export function debounce(fn, ms = 150) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Build columns that keep reading order (row by row) and re-flow when the width changes. */
export function masonry(container, items, { min = 260, gap = 12 } = {}) {
  container.classList.add("masonry");
  const flow = () => {
    const w = container.clientWidth || container.parentElement?.clientWidth || window.innerWidth;
    const n = Math.max(1, Math.floor((w + gap) / (min + gap)));
    if (container._n === n && container._items === items) return;
    container._n = n; container._items = items;
    const cols = Array.from({ length: n }, () => el("div", { class: "col" }));
    items.forEach((it, i) => cols[i % n].append(it));
    container.replaceChildren(...cols);
  };
  flow();
  container._ro?.disconnect();
  container._ro = new ResizeObserver(debounce(flow, 80));
  container._ro.observe(container);
  return () => container._ro?.disconnect();
}

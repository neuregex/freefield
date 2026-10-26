// The brush for inputs marked "paint" in app.json (inpaint): paint over a photo, get a white-on-black PNG mask the
// size of that photo. Strokes live on a transparent canvas at the photo's own size, so the mask is exact whatever the
// screen size; the screen shows them as a tint over the photo.
import { el, icon, toast, clamp } from "./util.js";
import { t } from "./i18n.js";

const TINT = "rgba(232, 255, 90, 0.55)";

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image"));
    img.src = src;
  });
}

/** A mask file (white = painted) back into strokes: white becomes opaque, black transparent. */
async function strokesFrom(maskFile, w, h) {
  const url = URL.createObjectURL(maskFile);
  try {
    const img = await loadImage(url);
    const c = el("canvas", { width: w, height: h });
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0, w, h);
    const d = g.getImageData(0, 0, w, h);
    for (let i = 0; i < d.data.length; i += 4) {
      const v = d.data[i];
      d.data[i] = d.data[i + 1] = d.data[i + 2] = 255;
      d.data[i + 3] = v;
    }
    g.putImageData(d, 0, 0);
    return c;
  } finally { URL.revokeObjectURL(url); }
}

/** A small preview: the photo with the painted area tinted, for the dropzone. */
export async function maskPreview(photoUrl, maskFile) {
  const img = await loadImage(photoUrl);
  const w = Math.min(640, img.naturalWidth), h = Math.round(w * img.naturalHeight / img.naturalWidth);
  const strokes = await strokesFrom(maskFile, w, h);
  const c = el("canvas", { width: w, height: h, class: "mask-preview" });
  const g = c.getContext("2d");
  g.drawImage(img, 0, 0, w, h);
  const tint = el("canvas", { width: w, height: h });
  const tg = tint.getContext("2d");
  tg.drawImage(strokes, 0, 0);
  tg.globalCompositeOperation = "source-in";
  tg.fillStyle = TINT;
  tg.fillRect(0, 0, w, h);
  g.drawImage(tint, 0, 0);
  return c;
}

/** Open the brush over `photo` (a File). Resolves with the mask File, or null when cancelled. */
export async function openPainter(photo, { mask = null, title } = {}) {
  const url = URL.createObjectURL(photo);
  let img;
  try { img = await loadImage(url); } catch { URL.revokeObjectURL(url); toast(t("paint.bad"), { error: true }); return null; }
  const W = img.naturalWidth, H = img.naturalHeight;
  const strokes = mask ? await strokesFrom(mask, W, H) : el("canvas", { width: W, height: H });
  const sg = strokes.getContext("2d");
  const view = el("canvas", { class: "pt-canvas" });
  const vg = view.getContext("2d");
  const tint = el("canvas");
  const cursor = el("div", { class: "pt-cursor", hidden: true });
  let size = Math.round(Math.min(W, H) * 0.06), erase = false, scale = 1;
  const undo = [];

  const sizeIn = el("input", { type: "range", min: String(Math.max(4, Math.round(Math.min(W, H) * 0.01))), max: String(Math.round(Math.min(W, H) * 0.25)),
    value: String(size), "aria-label": t("paint.size") });
  sizeIn.addEventListener("input", () => { size = Number(sizeIn.value); });
  const brushBtn = el("button", { type: "button", "aria-pressed": "true" }, t("paint.brush"));
  const eraseBtn = el("button", { type: "button", "aria-pressed": "false" }, t("paint.erase"));
  const setMode = (e) => { erase = e; brushBtn.setAttribute("aria-pressed", String(!e)); eraseBtn.setAttribute("aria-pressed", String(e)); };
  brushBtn.onclick = () => setMode(false);
  eraseBtn.onclick = () => setMode(true);

  const draw = () => {
    vg.clearRect(0, 0, view.width, view.height);
    vg.drawImage(img, 0, 0, view.width, view.height);
    const tg = tint.getContext("2d");
    tg.globalCompositeOperation = "source-over";
    tg.clearRect(0, 0, tint.width, tint.height);
    tg.drawImage(strokes, 0, 0, tint.width, tint.height);
    tg.globalCompositeOperation = "source-in";
    tg.fillStyle = TINT;
    tg.fillRect(0, 0, tint.width, tint.height);
    vg.drawImage(tint, 0, 0);
  };
  const stage = el("div", { class: "pt-stage" }, view, cursor);
  const fit = () => {
    const box = stage.getBoundingClientRect();
    scale = Math.min(box.width / W, box.height / H, 1);
    view.width = tint.width = Math.max(1, Math.round(W * scale));
    view.height = tint.height = Math.max(1, Math.round(H * scale));
    draw();
  };

  // strokes in the photo's own pixels
  const toImg = (e) => {
    const r = view.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width, 0, 1) * W, clamp((e.clientY - r.top) / r.height, 0, 1) * H];
  };
  let last = null;
  const line = (a, b) => {
    sg.globalCompositeOperation = erase ? "destination-out" : "source-over";
    sg.strokeStyle = "#fff";
    sg.fillStyle = "#fff";
    sg.lineWidth = size;
    sg.lineCap = "round";
    sg.lineJoin = "round";
    sg.beginPath();
    sg.moveTo(a[0], a[1]);
    sg.lineTo(b[0], b[1]);
    sg.stroke();
  };
  const moveCursor = (e) => {
    const r = stage.getBoundingClientRect();
    const d = size * scale;
    Object.assign(cursor.style, { width: `${d}px`, height: `${d}px`, left: `${e.clientX - r.left - d / 2}px`, top: `${e.clientY - r.top - d / 2}px` });
    cursor.hidden = false;
  };
  view.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    view.setPointerCapture(e.pointerId);
    undo.push(sg.getImageData(0, 0, W, H));
    if (undo.length > 20) undo.shift();
    last = toImg(e);
    line(last, last);
    draw();
  });
  view.addEventListener("pointermove", (e) => {
    moveCursor(e);
    if (!last) return;
    const p = toImg(e);
    line(last, p);
    last = p;
    draw();
  });
  const end = () => { last = null; };
  view.addEventListener("pointerup", end);
  view.addEventListener("pointercancel", end);
  view.addEventListener("pointerleave", () => { cursor.hidden = true; });

  const painted = () => {
    const d = sg.getImageData(0, 0, W, H).data;
    for (let i = 3; i < d.length; i += 16) if (d[i] > 0) return true;
    return false;
  };

  return new Promise((resolve) => {
    const close = (result) => {
      window.removeEventListener("resize", fit);
      document.removeEventListener("keydown", key, true);
      overlay.remove();
      URL.revokeObjectURL(url);
      resolve(result);
    };
    const done = () => {
      if (!painted()) { toast(t("paint.empty"), { error: true }); return; }
      const out = el("canvas", { width: W, height: H });
      const og = out.getContext("2d");
      og.fillStyle = "#000";
      og.fillRect(0, 0, W, H);
      og.drawImage(strokes, 0, 0);
      out.toBlob((blob) => close(blob ? new File([blob], "mask.png", { type: "image/png" }) : null), "image/png");
    };
    const key = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(null); }
      else if ((e.key === "z" || e.key === "Z") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (undo.length) { sg.putImageData(undo.pop(), 0, 0); draw(); } }
    };
    const overlay = el("div", { class: "painter", role: "dialog", "aria-modal": "true", "aria-label": title || t("paint.title") },
      el("div", { class: "pt-box" },
        el("header", {}, el("div", {}, el("h3", {}, title || t("paint.title")), el("p", { class: "help" }, t("paint.help"))),
          el("button", { class: "icon-btn", type: "button", "aria-label": t("act.close"), onclick: () => close(null) }, icon("x"))),
        stage,
        el("footer", {},
          el("div", { class: "seg" }, brushBtn, eraseBtn),
          el("label", { class: "pt-size" }, el("span", {}, t("paint.size")), sizeIn),
          el("button", { class: "btn small", type: "button", onclick: () => { if (undo.length) { sg.putImageData(undo.pop(), 0, 0); draw(); } } }, icon("redo"), t("paint.undo")),
          el("button", { class: "btn small", type: "button", onclick: () => { undo.push(sg.getImageData(0, 0, W, H)); sg.clearRect(0, 0, W, H); draw(); } }, icon("trash"), t("paint.clear")),
          el("span", { style: { flex: 1 } }),
          el("button", { class: "btn small", type: "button", onclick: () => close(null) }, t("act.cancel")),
          el("button", { class: "btn lime small", type: "button", onclick: done }, icon("check"), t("paint.done")))));
    document.body.append(overlay);
    window.addEventListener("resize", fit);
    document.addEventListener("keydown", key, true);
    requestAnimationFrame(fit);
  });
}

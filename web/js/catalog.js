// The app catalog (/api/apps) and the ways the UI groups it: studios, categories, taglines.
// Everything about an app's form comes from its app.json; this file only decides where it shows up.
import { api, store } from "./util.js";
import { lang } from "./i18n.js";

export let apps = [];
export const byId = new Map();
export let draftsAllowed = false;

const DEV = new URLSearchParams(location.search).has("dev");   // ?dev shows the smoke-test apps

export async function loadCatalog() {
  const d = await api("/api/apps");
  draftsAllowed = Boolean(d.drafts);
  apps = d.apps.filter((a) => DEV || !a.id.startsWith("smoke"));
  byId.clear();
  for (const a of apps) byId.set(a.id, a);
  return apps;
}

/** Apps grouped like a store: a card can only sit in one row. */
export const CATEGORIES = [
  { id: "create", apps: ["z-image", "cinema-studio", "styles", "video-t2v", "video", "music", "sfx"] },
  { id: "identity", apps: ["character", "speak", "talking", "recast", "motion-transfer", "genjutsu", "dub", "character-swap", "face-swap"] },
  { id: "camera", apps: ["camera-moves", "camera-copy", "reshoot", "reframe", "transitions", "angles", "shots", "zooms", "whats-next"] },
  { id: "style", apps: ["relight", "style-reference", "mixed-media", "upscale", "upscale-video", "sdr-hdr", "smooth", "remove-bg"] },
  { id: "vfx", apps: ["effects", "edit", "vfx-clean-plate", "vfx-day-to-night", "vfx-water"] },
  { id: "ads", apps: ["product-shot", "poster", "packshot", "macro-scene", "macro-product", "giant-product", "billboard", "graffiti-ad", "fridge-ad", "ugc-shot",
    "asmr-product", "chameleon", "magic-button", "truck-ad", "kick-ad", "volcano-ad"] },
  { id: "portraits", apps: ["headshot", "commercial-faces", "style-snap", "skin-enhancer", "outfit-vending", "glitter-sticker", "fashion-factory", "try-on", "outfit-swap", "outfit-shot"] },
  { id: "clips", apps: ["behind-the-scenes", "asmr-whisper", "asmr-host", "roller-coaster", "storm-creature", "cloud-surf", "mukbang", "melting-doodle", "rap-video", "idol"] },
  { id: "play", apps: ["game-styles", "plushie", "render-3d", "figure-3d", "pixel-game", "brick-toy", "sketch-to-real", "paint-app", "mural", "micro-beasts", "meme"] },
  { id: "templates", apps: ["j-magazine", "cafe-60s", "victory-card", "j-poster", "mascot", "burning-sunset", "comic-book", "giallo", "renaissance", "japanese-show", "breakdown", "edit-text", "image-effects", "color-grade"] },
];
export function categoryOf(id) {
  return CATEGORIES.find((c) => c.apps.includes(id))?.id ?? "more";
}

/** The video studio's three tabs, like a camera crew: shoot, fix, move. */
export const VIDEO_TABS = [
  { id: "create", apps: ["video", "effects", "video-t2v", "genjutsu", "speak", "talking", "dub", "transitions", "camera-moves"] },
  { id: "edit", apps: ["recast", "mixed-media", "reframe", "vfx-clean-plate", "vfx-day-to-night", "vfx-water", "sdr-hdr", "upscale-video", "smooth", "reshoot"] },
  { id: "motion", apps: ["motion-transfer", "camera-copy"] },
  { id: "templates", apps: ["behind-the-scenes", "asmr-product", "asmr-whisper", "asmr-host", "chameleon", "magic-button", "truck-ad", "kick-ad", "volcano-ad",
    "roller-coaster", "storm-creature", "cloud-surf", "mukbang", "melting-doodle", "rap-video", "idol"] },
];
export const videoTabOf = (id) => VIDEO_TABS.find((tab) => tab.apps.includes(id))?.id ?? null;

/** Shown in the top bar next to the studios, like a store's front window. */
export const FEATURED = [{ id: "recast", tag: "featured" }, { id: "speak", tag: "new" }, { id: "relight", tag: null }];

/** Big cards on the Explore page, in this order when they have an example. */
export const HERO = ["effects", "recast", "motion-transfer", "speak", "camera-moves", "talking", "transitions", "vfx-day-to-night", "video-t2v", "relight", "styles"];

/** Prompt-first apps get the floating composer; upload-first apps get the sidebar. */
export function layoutOf(app) {
  const hasText = app.inputs.some((i) => i.type === "textarea");
  return (app.section === "image" || app.section === "audio") && hasText ? "composer" : "sidebar";
}

/** The apps a model switcher offers next to this one: the same kind of app in the same category. */
export function familyOf(app) {
  const layout = layoutOf(app);
  if (layout === "composer") return apps.filter((a) => layoutOf(a) === "composer" && a.section === app.section && categoryOf(a.id) === categoryOf(app.id));
  if (app.section === "video" || videoTabOf(app.id)) {
    const tab = videoTabOf(app.id);
    return apps.filter((a) => videoTabOf(a.id) === tab);
  }
  return apps.filter((a) => layoutOf(a) === "sidebar" && !videoTabOf(a.id));
}

/** Which studio (top-bar entry) an app belongs to. */
export function studioOf(app) {
  if (videoTabOf(app.id) || app.section === "video") return "video";
  if (app.section === "audio") return "audio";
  if (layoutOf(app) === "composer") return "image";
  return "apps";
}

const DEFAULT_APP = { image: "z-image", video: "video", audio: "music" };
export function lastAppFor(studio) {
  const id = store.get(`last.${studio}`);
  if (id && byId.has(id)) return id;
  const fallback = DEFAULT_APP[studio];
  if (byId.has(fallback)) return fallback;
  return apps.find((a) => studioOf(a) === studio)?.id ?? apps[0]?.id;
}
export function rememberApp(app) {
  store.set(`last.${studioOf(app)}`, app.id);
}

const TAGLINES = {
  "z-image": ["Words to picture in seconds", "De palabras a imagen en segundos"],
  "cinema-studio": ["Shoot it on any camera", "Fílmalo con cualquier cámara"],
  styles: ["Nine looks, one prompt", "Nueve estilos, un prompt"],
  "style-reference": ["Paint like your reference", "Pinta como tu referencia"],
  character: ["Same face, any scene", "La misma cara, cualquier escena"],
  edit: ["Edit with words", "Edita con palabras"],
  "product-shot": ["Your product, anywhere", "Tu producto, en cualquier lugar"],
  relight: ["Move the light", "Mueve la luz"],
  "remove-bg": ["Cut out anything", "Recorta lo que sea"],
  upscale: ["More pixels, more detail", "Más píxeles, más detalle"],
  video: ["Bring a still to life", "Dale vida a una foto"],
  "video-t2v": ["Type a shot, get a clip", "Escribe una toma, obtén un clip"],
  "camera-moves": ["Direct the camera", "Dirige la cámara"],
  effects: ["35 effects from one photo", "35 efectos desde una foto"],
  "camera-copy": ["Copy any camera move", "Copia cualquier movimiento de cámara"],
  recast: ["Recast anyone in your clip", "Cambia al protagonista de tu clip"],
  "motion-transfer": ["Borrow the moves", "Toma prestado el movimiento"],
  speak: ["Make a portrait talk", "Haz hablar un retrato"],
  talking: ["Lip-sync to your voice", "Sincroniza labios con tu voz"],
  transitions: ["From this frame to that one", "De este cuadro a aquel"],
  reshoot: ["Reshoot from a new angle", "Vuelve a filmar desde otro ángulo"],
  "upscale-video": ["Sharpen every frame", "Nitidez en cada cuadro"],
  smooth: ["Silky slow motion", "Cámara lenta fluida"],
  "vfx-clean-plate": ["Empty the street", "Vacía la calle"],
  "vfx-day-to-night": ["Day becomes night", "El día se vuelve noche"],
  "vfx-water": ["Add water to any shot", "Agrega agua a cualquier toma"],
  genjutsu: ["Your cast, props and place in one clip", "Tu elenco, props y lugar en un clip"],
  reframe: ["Any aspect ratio, nothing cropped", "Cualquier formato, sin recortar"],
  "sdr-hdr": ["HDR range for an SDR clip", "Rango HDR para un clip SDR"],
  "mixed-media": ["Same clip, 16 looks", "El mismo clip, 16 estilos"],
  dub: ["New words, same face", "Palabras nuevas, la misma cara"],
  music: ["Write a song", "Compón una canción"],
  sfx: ["Sound for every scene", "Sonido para cada escena"],
};
export function tagline(app) {
  const pair = TAGLINES[app.id];
  return pair ? pair[lang === "es" ? 1 : 0] : app.name;
}

/** Icon name per app for chips and tiles. */
export function iconOf(app) {
  const byIdIcon = { relight: "sun", "remove-bg": "scissors", "product-shot": "box", character: "user", speak: "user", talking: "user",
    recast: "user", "motion-transfer": "hand", "camera-moves": "camera", "camera-copy": "camera", reshoot: "camera", music: "audio", sfx: "audio", effects: "spark" };
  return byIdIcon[app.id] || (app.section === "video" ? "video" : app.section === "audio" ? "audio" : "image");
}

/** The prompt of a set of values: the first required textarea, else the first textarea. */
export function promptInput(app) {
  const texts = app.inputs.filter((i) => i.type === "textarea");
  return texts.find((i) => i.required) || texts[0] || null;
}

/** Seconds the lab example took, as an estimate for the Generate button. */
export function estimate(app) {
  const s = app.example?.seconds;
  return s ? { seconds: s, gpu: (app.example.gpu || "").split(",")[0] || "GPU" } : null;
}

/** "fits whole" → [label key, css class] */
export function fitOf(app) {
  const v = app.vram?.verdict;
  if (!v) return null;
  const map = { "fits whole": ["fit.whole", "ok"], "fits by phases": ["fit.phases", "ok"], "tight (by phases)": ["fit.tight", "tight"],
    "needs Modal": ["fit.big", "big"], "no models": ["fit.none", ""] };
  return map[v] || [v, ""];
}

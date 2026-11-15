// The app catalog (/api/apps) and the ways the UI groups it: studios, categories, taglines.
// Everything about an app's form comes from its app.json; this file only decides where it shows up.
import { api, store } from "./util.js";
import { lang } from "./i18n.js";
import { localizeApp } from "./app-locale.js";

export let apps = [];
export const byId = new Map();
export let draftsAllowed = false;
export let hosted = false;   // the server runs as a hosted demo (passcode, run cap): lab marks are read-only

const DEV = new URLSearchParams(location.search).has("dev");   // ?dev shows the smoke-test apps

export async function loadCatalog() {
  const d = await api("/api/apps");
  draftsAllowed = Boolean(d.drafts);
  hosted = Boolean(d.hosted);
  apps = d.apps.filter((a) => DEV || !a.id.startsWith("smoke")).map((a) => localizeApp(a, () => lang));
  byId.clear();
  for (const a of apps) byId.set(a.id, a);
  return apps;
}

/** Apps grouped like a store: a card can only sit in one row. */
export const CATEGORIES = [
  { id: "create", apps: ["create-image", "cinema-studio", "cinema-video", "z-image", "moss-image", "moodboard", "styles", "video-t2v", "video", "h3-video", "h3-photo", "music", "sfx"] },
  { id: "identity", apps: ["character", "character-3", "speak", "talking", "recast", "motion-transfer", "genjutsu", "dub", "character-swap", "face-swap"] },
  { id: "camera", apps: ["camera-moves", "camera-copy", "reshoot", "reframe", "extend-video", "transitions", "angles", "shots", "zooms", "whats-next", "bullet-time-scene", "bullet-time-white", "bullet-time-splash"] },
  { id: "style", apps: ["relight", "style-reference", "mixed-media", "upscale", "upscale-video", "sdr-hdr", "smooth", "remove-bg", "video-remove-bg", "depth-map", "expand-image"] },
  { id: "vfx", apps: ["effects", "morph", "edit", "inpaint", "vfx-clean-plate", "vfx-day-to-night", "vfx-water"] },
  { id: "ads", apps: ["product-shot", "poster", "packshot", "macro-scene", "macro-product", "giant-product", "billboard", "graffiti-ad", "fridge-ad", "ugc-shot",
    "asmr-product", "chameleon", "magic-button", "truck-ad", "kick-ad", "volcano-ad"] },
  { id: "portraits", apps: ["ai-influencer", "ai-influencer-photo", "photodump", "headshot", "commercial-faces", "style-snap", "skin-enhancer", "outfit-vending", "glitter-sticker", "fashion-factory", "try-on", "outfit-swap", "outfit-shot"] },
  { id: "clips", apps: ["behind-the-scenes", "asmr-whisper", "asmr-host", "roller-coaster", "storm-creature", "cloud-surf", "mukbang", "melting-doodle", "rap-video", "idol"] },
  { id: "play", apps: ["game-styles", "plushie", "render-3d", "figure-3d", "pixel-game", "brick-toy", "sketch-to-real", "paint-app", "mural", "micro-beasts", "meme"] },
  { id: "templates", apps: ["j-magazine", "cafe-60s", "victory-card", "j-poster", "mascot", "burning-sunset", "comic-book", "giallo", "renaissance", "japanese-show", "breakdown", "edit-text", "image-effects", "color-grade"] },
];
export function categoryOf(id) {
  return CATEGORIES.find((c) => c.apps.includes(id))?.id ?? "more";
}

/** The video studio's three tabs, like a camera crew: shoot, fix, move. */
export const VIDEO_TABS = [
  { id: "create", apps: ["video", "cinema-video", "h3-video", "h3-photo", "effects", "morph", "video-t2v", "genjutsu", "speak", "talking", "dub", "transitions", "camera-moves"] },
  { id: "edit", apps: ["recast", "mixed-media", "reframe", "extend-video", "vfx-clean-plate", "vfx-day-to-night", "vfx-water", "sdr-hdr", "upscale-video", "smooth", "reshoot", "video-remove-bg"] },
  { id: "motion", apps: ["motion-transfer", "camera-copy"] },
  { id: "templates", apps: ["behind-the-scenes", "asmr-product", "asmr-whisper", "asmr-host", "chameleon", "magic-button", "truck-ad", "kick-ad", "volcano-ad",
    "roller-coaster", "storm-creature", "cloud-surf", "mukbang", "melting-doodle", "rap-video", "idol", "bullet-time-scene", "bullet-time-white", "bullet-time-splash"] },
];
export const videoTabOf = (id) => VIDEO_TABS.find((tab) => tab.apps.includes(id))?.id ?? null;

/** Shown in the top bar next to the studios, like a store's front window. */
export const FEATURED = [{ id: "recast", tag: "featured" }, { id: "speak", tag: "new" }, { id: "relight", tag: null }];

/** The open models behind the apps, for the top bar's menus. `file` is a piece of the model file's name: an app that
 *  downloads a matching file uses the model. `app` runs the model on its own. Order matters for modelOf(): an app is
 *  labelled with the first model it uses, so the video and audio models come before FLUX 3 Klein, which many video
 *  apps use only to prepare a frame. */
export const MODELS = [
  { name: "LTX-2.5 22B", file: "ltx-2.5-22b", app: "video", note: ["Image to video, IC-LoRAs and VFX", "Imagen a video, IC-LoRAs y VFX", "Изображение в видео, IC-LoRA и визуальные эффекты"] },
  { name: "MiniMax H3", file: "minimax_h3_", app: "h3-video", note: ["Video with sound, extend, reshoot", "Video con sonido, extender y re-shoot", "Видео со звуком, продолжение и пересъёмка"] },
  { name: "Wan 2.1 I2V 14B", file: "wan2.1_i2v", app: "effects", note: ["24 effect LoRAs and Bullet Time", "24 LoRAs de efectos y Bullet Time", "24 LoRA эффектов и эффект остановки времени"] },
  { name: "Wan 2.2 Fun Camera", file: "wan2.2_fun_camera", app: "camera-moves", note: ["Camera moves", "Movimientos de cámara", "Движения камеры"] },
  { name: "Wan Animate 2", file: "wan_animate", app: "motion-transfer", note: ["The motion of a driving clip", "El movimiento de otro clip", "Движения из видеообразца"] },
  { name: "SCAIL-2 + SAM 3.1", file: "SCAIL", app: "recast", note: ["Swap the actor of a clip", "Cambia al actor de un clip", "Замена актёра в ролике"] },
  { name: "SeedVR2 3B", file: "seedvr2", app: "upscale-video", note: ["Video and image upscale", "Escalado de video y de imagen", "Повышение разрешения видео и изображений"] },
  { name: "MiniMax Music 3", file: "minimax_music3", app: "music", note: ["Songs with lyrics", "Canciones con letra", "Песни с текстом"] },
  { name: "Stable Audio 3", file: "stable_audio_3", app: "sfx", note: ["Sound effects and instrumental music", "Efectos de sonido y música instrumental", "Звуковые эффекты и инструментальная музыка"] },
  { name: "Qwen-Image-Edit 2509", file: "qwen_image_edit", app: "relight", note: ["Light, angles and the next shot", "Luz, ángulos y la siguiente toma", "Свет, ракурсы и следующий кадр"] },
  { name: "Krea 2 Turbo", file: "krea2_turbo", app: "styles", note: ["Styles with Krea's LoRAs", "Estilos con los LoRAs de Krea", "Стили с LoRA от Krea"] },
  { name: "MOSS-Image", file: "moss_image", app: "moss-image", note: ["Layout prompts", "Prompts con layout", "Промпты с компоновкой"] },
  { name: "Z-Image Turbo", file: "z_image_turbo", app: "z-image", note: ["Fast drafts", "Borradores rápidos", "Быстрые черновики"] },
  { name: "FLUX 3 Image Klein", file: "flux3-image-klein", app: "create-image", note: ["Text to image and every edit", "Texto a imagen y todas las ediciones", "Изображения по тексту и любое редактирование"] },
];
export const usesModel = (app, m) => app.models.some((x) => x.name.includes(m.file));
/** The model an app is built on, for a one-line label ("FLUX 3 Image Klein"); null for the model-free apps. */
export function modelOf(app) {
  return MODELS.find((m) => usesModel(app, m)) ?? null;
}

/** The apps a top-bar menu lists, grouped like the studio itself: the image apps by category, the video apps by tab. */
export function menuGroups(studio) {
  const inMenu = (a) => studio === "image" ? a.section === "image" && studioOf(a) !== "video" : studioOf(a) === studio;
  const pick = (ids) => ids.map((id) => byId.get(id)).filter((a) => a && inMenu(a));
  const groups = studio === "video" ? VIDEO_TABS.map((g) => ({ key: `vtab.${g.id}`, apps: pick(g.apps) }))
    : studio === "image" ? CATEGORIES.map((g) => ({ key: `cat.${g.id}.t`, apps: pick(g.apps) }))
    : [{ key: null, apps: apps.filter(inMenu) }];
  const listed = new Set(groups.flatMap((g) => g.apps));
  const rest = apps.filter((a) => inMenu(a) && !listed.has(a));
  if (rest.length) groups.push({ key: "cat.more.t", apps: rest });
  return groups.filter((g) => g.apps.length);
}

/** Big cards on the Explore page, in this order when they have an example. */
// the hosted demo opens with these, each loaded with its lab example: quick first, then the big video models
export const START_HERE = ["face-swap", "morph", "mixed-media", "dub", "reshoot"];
export const HERO = ["effects", "recast", "motion-transfer", "speak", "camera-moves", "talking", "transitions", "vfx-day-to-night", "video-t2v", "relight", "styles"];

/** Prompt-first apps get the floating composer; upload-first apps get the sidebar. */
export function layoutOf(app) {
  if (app.inputs.some((i) => i.paint)) return "sidebar";   // painting a mask needs the photo in a dropzone
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
  "z-image": ["Words to picture in seconds", "De palabras a imagen en segundos", "Из слов в картинку за секунды"],
  "cinema-studio": ["Shoot it on any camera", "Fílmalo con cualquier cámara", "Снимайте на любую камеру"],
  "cinema-video": ["The same film look, now moving", "El mismo look de cine, ahora en movimiento", "Тот же кинообраз, теперь в движении"],
  styles: ["Nine looks, one prompt", "Nueve estilos, un prompt", "Девять стилей, один промпт"],
  "style-reference": ["Paint like your reference", "Pinta como tu referencia", "Рисуйте в стиле референса"],
  character: ["Same face, any scene", "La misma cara, cualquier escena", "Одно лицо в любой сцене"],
  edit: ["Edit with words", "Edita con palabras", "Редактируйте словами"],
  "product-shot": ["Your product, anywhere", "Tu producto, en cualquier lugar", "Ваш товар — где угодно"],
  relight: ["Move the light", "Mueve la luz", "Переместите свет"],
  "remove-bg": ["Cut out anything", "Recorta lo que sea", "Вырежьте что угодно"],
  upscale: ["More pixels, more detail", "Más píxeles, más detalle", "Больше пикселей, больше деталей"],
  video: ["Bring a still to life", "Dale vida a una foto", "Оживите фотографию"],
  "video-t2v": ["Type a shot, get a clip", "Escribe una toma, obtén un clip", "Опишите кадр — получите ролик"],
  "camera-moves": ["Direct the camera", "Dirige la cámara", "Управляйте камерой"],
  effects: ["24 effects from one photo", "24 efectos desde una foto", "24 эффекта из одного фото"],
  "camera-copy": ["Copy any camera move", "Copia cualquier movimiento de cámara", "Скопируйте любое движение камеры"],
  recast: ["Recast anyone in your clip", "Cambia al protagonista de tu clip", "Замените актёра в своём ролике"],
  "motion-transfer": ["Borrow the moves", "Toma prestado el movimiento", "Позаимствуйте движения"],
  speak: ["Make a portrait talk", "Haz hablar un retrato", "Пусть портрет заговорит"],
  talking: ["Lip-sync to your voice", "Sincroniza labios con tu voz", "Движения губ под ваш голос"],
  transitions: ["From this frame to that one", "De este cuadro a aquel", "От одного кадра к другому"],
  reshoot: ["Reshoot from a new angle", "Vuelve a filmar desde otro ángulo", "Переснимите с нового ракурса"],
  "upscale-video": ["Sharpen every frame", "Nitidez en cada cuadro", "Чёткость в каждом кадре"],
  smooth: ["Silky slow motion", "Cámara lenta fluida", "Плавное замедленное движение"],
  "vfx-clean-plate": ["Empty the street", "Vacía la calle", "Освободите улицу"],
  "vfx-day-to-night": ["Day becomes night", "El día se vuelve noche", "День превращается в ночь"],
  "vfx-water": ["Add water to any shot", "Agrega agua a cualquier toma", "Добавьте воду в любой кадр"],
  genjutsu: ["Your cast, props and place in one clip", "Tu elenco, props y lugar en un clip", "Ваши актёры, реквизит и место в одном ролике"],
  reframe: ["Any aspect ratio, nothing cropped", "Cualquier formato, sin recortar", "Любые пропорции без обрезки"],
  "sdr-hdr": ["HDR range for an SDR clip", "Rango HDR para un clip SDR", "Диапазон HDR для ролика SDR"],
  "mixed-media": ["Same clip, 16 looks", "El mismo clip, 16 estilos", "Один ролик, 16 стилей"],
  dub: ["New words, same face", "Palabras nuevas, la misma cara", "Новые слова, то же лицо"],
  morph: ["Fifteen transformations, your face", "Quince transformaciones, tu cara", "Пятнадцать превращений с вашим лицом"],
  music: ["Write a song", "Compón una canción", "Напишите песню"],
  sfx: ["Sound for every scene", "Sonido para cada escena", "Звук для каждой сцены"],

  "ai-influencer": ["A made-up influencer for your feed", "Un influencer inventado para tu feed", "Вымышленный блогер для вашей ленты"],
  "ai-influencer-photo": ["Your face, a new look", "Tu cara, un look nuevo", "Ваше лицо, новый образ"],
  angles: ["The same scene from another angle", "La misma escena desde otro ángulo", "Та же сцена с другого ракурса"],
  "asmr-host": ["You hosting an ASMR studio", "Tú conduciendo un estudio de ASMR", "Вы — ведущий ASMR-студии"],
  "asmr-product": ["Your product in an ASMR clip", "Tu producto en un clip de ASMR", "Ваш товар в ASMR-ролике"],
  "asmr-whisper": ["You whispering in an ASMR clip", "Tú susurrando en un clip de ASMR", "Ваш шёпот в ASMR-ролике"],
  "behind-the-scenes": ["The camera pulls back to the film set", "La cámara se aleja y muestra el set", "Камера отъезжает и открывает съёмочную площадку"],
  billboard: ["Your photo on a city billboard", "Tu foto en un espectacular", "Ваше фото на городском билборде"],
  breakdown: ["Your subject taken apart and labeled", "Tu objeto desarmado y rotulado", "Ваш объект по частям и с подписями"],
  "brick-toy": ["Rebuilt from plastic bricks", "Reconstruido con bloques de plástico", "Заново собрано из пластиковых кубиков"],
  "bullet-time-scene": ["Freeze the moment, circle the camera", "Congela el momento y gira la cámara", "Остановите мгновение и облетите его камерой"],
  "bullet-time-splash": ["Frozen water around your subject", "Agua congelada alrededor del sujeto", "Застывшая вода вокруг вашего объекта"],
  "bullet-time-white": ["Bullet time on a white backdrop", "Bullet time sobre fondo blanco", "Остановка времени на белом фоне"],
  "burning-sunset": ["Your scene under a blazing sunset", "Tu escena bajo un atardecer intenso", "Ваша сцена в пылающем закате"],
  "cafe-60s": ["You in a 1960s cafe", "Tú en un café de los años 60", "Вы в кафе 1960-х"],
  chameleon: ["A chameleon in your product's colors", "Un camaleón del color de tu producto", "Хамелеон в цветах вашего товара"],
  "character-swap": ["Put another person in the scene", "Pon a otra persona en la escena", "Поместите другого человека в сцену"],
  "cloud-surf": ["You surfing across pink clouds", "Tú surfeando sobre nubes rosas", "Вы на доске среди розовых облаков"],
  "color-grade": ["Six color grades for a photo", "Seis gradaciones de color", "Шесть вариантов цветокоррекции фото"],
  "comic-book": ["Your photo as a comic panel", "Tu foto como viñeta de cómic", "Ваше фото как кадр комикса"],
  "commercial-faces": ["Campaign portraits of you", "Retratos de campaña tuyos", "Ваши портреты для рекламной кампании"],
  "create-image": ["Text to image with FLUX 3 Klein", "Texto a imagen con FLUX 3 Klein", "Изображения по тексту с FLUX 3 Klein"],
  "depth-map": ["Depth or normals from a photo", "Profundidad o normales de una foto", "Карта глубины или нормалей по фото"],
  "edit-text": ["Change the text in an image", "Cambia el texto de una imagen", "Измените текст на изображении"],
  "expand-image": ["Grow a photo past its edges", "Extiende una foto más allá del borde", "Расширьте фото за его границы"],
  "extend-video": ["Continue a clip, sound included", "Continúa un clip, con sonido", "Продолжите ролик вместе со звуком"],
  "face-swap": ["The face from another photo", "La cara de otra foto", "Лицо с другой фотографии"],
  "fashion-factory": ["A catalog photo in a new garment", "Foto de catálogo con otra prenda", "Каталожное фото в новой одежде"],
  "figure-3d": ["You as a boxed collectible figure", "Tú como figura coleccionable", "Вы как коллекционная фигурка в коробке"],
  "fridge-ad": ["Your product in a display fridge", "Tu producto en un refrigerador", "Ваш товар в холодильной витрине"],
  "game-styles": ["You in 12 video game styles", "Tú en 12 estilos de videojuego", "Вы в 12 стилях видеоигр"],
  giallo: ["A 1970s giallo film still", "Un fotograma de giallo de los 70", "Кадр из фильма джалло 1970-х"],
  "giant-product": ["Your product as a city monument", "Tu producto gigante sobre la ciudad", "Ваш товар как городской монумент"],
  "glitter-sticker": ["You as a glitter sticker", "Tú como sticker con brillos", "Вы как наклейка с блёстками"],
  "graffiti-ad": ["Your product as a graffiti mural", "Tu producto como mural de grafiti", "Ваш товар как граффити на стене"],
  "h3-photo": ["A photo to a clip with sound", "De foto a clip con sonido", "Из фото в ролик со звуком"],
  "h3-video": ["A clip with sound from a prompt", "Un clip con sonido desde un prompt", "Ролик со звуком по описанию"],
  headshot: ["A studio headshot from a selfie", "Headshot de estudio desde una selfie", "Студийный портрет из селфи"],
  idol: ["Your K-pop stage moment", "Tu momento de idol de K-pop", "Ваш выход на K-pop-сцену"],
  "image-effects": ["Ten effects for a photo", "Diez efectos para una foto", "Десять эффектов для фото"],
  "j-magazine": ["You on a Japanese magazine cover", "Tú en portada de revista japonesa", "Вы на обложке японского журнала"],
  "j-poster": ["A Japanese-style poster of you", "Un póster de estilo japonés tuyo", "Постер с вами в японском стиле"],
  "japanese-show": ["You on a retro Japanese TV show", "Tú en un programa japonés retro", "Вы в японском ретро-телешоу"],
  "kick-ad": ["Boxes knocked away from your product", "Cajas que vuelan junto a tu producto", "Коробки разлетаются вокруг вашего товара"],
  "macro-product": ["A macro detail of your product", "Un detalle macro de tu producto", "Макродеталь вашего товара"],
  "macro-scene": ["Your product in a macro scene", "Tu producto en una escena macro", "Ваш товар в макросцене"],
  "magic-button": ["A glowing button changes the scene", "Un botón que cambia la escena", "Светящаяся кнопка меняет сцену"],
  mascot: ["You in a mascot costume", "Tú con traje de mascota", "Вы в костюме талисмана"],
  "melting-doodle": ["Doodles melting down the frame", "Garabatos que se derriten", "Рисунки стекают по кадру"],
  meme: ["A meme from a scene and two lines", "Un meme: una escena y dos textos", "Мем из сцены и двух строк"],
  "micro-beasts": ["You among tiny animals", "Tú entre animales diminutos", "Вы среди крошечных зверей"],
  "moss-image": ["Text to image with a layout", "Texto a imagen con layout", "Изображение по тексту с компоновкой"],
  mukbang: ["You eating for the camera", "Tú comiendo para la cámara", "Вы едите перед камерой"],
  mural: ["You on a street mural", "Tú en un mural callejero", "Вы на уличном мурале"],
  "outfit-shot": ["A garment on a model, in studio", "Una prenda en modelo, en estudio", "Одежда на модели в студии"],
  "outfit-swap": ["Wear someone else's outfit", "Ponte el outfit de otra persona", "Примерьте чужой наряд"],
  "outfit-vending": ["Your clothes in a vending machine", "Tu ropa en una máquina expendedora", "Ваша одежда в торговом автомате"],
  packshot: ["The closing frame of an ad", "El cuadro final de un anuncio", "Финальный кадр рекламы"],
  "paint-app": ["Redrawn in a 90s paint program", "En un programa de dibujo de los 90", "Перерисовано в редакторе из 90-х"],
  "pixel-game": ["Your scene as 16-bit pixel art", "Tu escena en pixel art de 16 bits", "Ваша сцена в 16-битном пиксель-арте"],
  plushie: ["Remade as a plush toy", "Convertido en peluche", "Превращение в плюшевую игрушку"],
  poster: ["A product photo to a poster", "De foto de producto a póster", "Из фото товара в постер"],
  "rap-video": ["You in a rap music video", "Tú en un video de rap", "Вы в рэп-клипе"],
  renaissance: ["You as a Renaissance painting", "Tú como pintura renacentista", "Вы на картине эпохи Возрождения"],
  "render-3d": ["A stylized 3D render", "Un render 3D estilizado", "Стилизованный 3D-рендер"],
  "roller-coaster": ["You on a roller coaster", "Tú en una montaña rusa", "Вы на американских горках"],
  shots: ["Nine framings of one image", "Nueve encuadres de una imagen", "Девять вариантов кадрирования одного изображения"],
  "sketch-to-real": ["From a sketch to a photo", "De boceto a foto", "Из эскиза в фотографию"],
  "skin-enhancer": ["A natural skin retouch", "Retoque de piel natural", "Естественная ретушь кожи"],
  "storm-creature": ["A storm giant behind your scene", "Gigante de tormenta tras tu escena", "Штормовой гигант за вашей сценой"],
  "style-snap": ["You in a complete new outfit", "Tú con un outfit completo nuevo", "Вы в совершенно новом наряде"],
  "truck-ad": ["A toy truck with your product", "Camión de juguete con tu producto", "Игрушечный грузовик с вашим товаром"],
  "try-on": ["Try a garment on your photo", "Pruébate una prenda en tu foto", "Примерьте одежду на своём фото"],
  "ugc-shot": ["A casual phone photo of your product", "Una foto casual de tu producto", "Непринуждённое фото товара на телефон"],
  "victory-card": ["Your face on a winning card", "Tu cara en una carta ganadora", "Ваше лицо на победной карте"],
  "video-remove-bg": ["Cut the subject out of a clip", "Recorta al sujeto de un clip", "Вырежьте объект из ролика"],
  "volcano-ad": ["A volcano erupts behind your product", "Un volcán detrás de tu producto", "Извержение вулкана за вашим товаром"],
  "whats-next": ["The next shot of your scene", "La siguiente toma de tu escena", "Следующий кадр вашей сцены"],
  zooms: ["Zoom levels of one image", "Niveles de zoom de una imagen", "Разные уровни приближения одного изображения"],
  "character-3": ["Three photos, one face", "Tres fotos, una misma cara", "Три фото, одно лицо"],
  moodboard: ["The look of three images", "El look de tres imágenes", "Настроение трёх изображений"],
  photodump: ["Four photos of you, one aesthetic", "Cuatro fotos tuyas, una estética", "Четыре ваших фото в одной эстетике"],
  inpaint: ["Paint it, describe it", "Píntalo y descríbelo", "Закрасьте и опишите"],
};
export function tagline(app) {
  const pair = TAGLINES[app.id];
  return pair ? pair[lang === "ru" ? 2 : lang === "es" ? 1 : 0] : app.name;
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

#!/usr/bin/env python3
"""Template apps: one app per Higgsfield app that is a fixed prompt over a pipeline Freefield already runs.

    python tools/template_apps.py            # writes apps/<id>/app.json + workflow.api.json and the tpl-* lab cases
    python tools/template_apps.py --check    # only checks the table (ids, lengths, placeholders)
    python tools/template_apps.py --readme   # prints the Markdown table for README.md
    python tools/template_apps.py --lab      # prints the lab command that makes every template's example

Each entry below is a Higgsfield app (its name in `feature`) rebuilt as a prompt template on one of
three bases: FLUX 3 Image Klein's edit pipeline (apps/edit, one reference image; the same workflow
behind edit, character and product-shot) or Z-Image Turbo (apps/z-image, text to image). The app
folder gets a copy of the base workflow (built by tools/build_apps.py) and a manifest whose "details"
input carries the prompt as a bind template; selects feed {placeholders} in that prompt. The base
app's models and credits are copied as they are.

lab/cases.json gets one "tpl-<id>" showcase case per app (the section after the effects cases is
regenerated in place), on the synthetic references the lab already makes, plus the few new
references listed in REFS.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# the pipelines a template can sit on: node ids for the image, the prompt and the settings
BASES = {
    "edit": {"app": "edit", "pack": "image-flux3", "image": ("11", "image"), "prompt": ("4", "text"), "keep": ("steps", "seed"), "output": {"node": "9", "type": "image"}},
    "z-image": {"app": "z-image", "pack": "image", "image": None, "prompt": ("57:27", "text"), "keep": ("width", "height", "steps", "seed"), "output": {"node": "9", "type": "image"}},
}

# new synthetic references the template cases need (the rest come from the effects section)
REFS = {
    "ref-tpl-sketch": ("A rough pencil sketch on white paper of a cat sitting on a windowsill next to a potted plant, loose lines, no color", 1024, 1024,
                       "Reference sketch for Sketch to Real."),
    "ref-tpl-sign": ("Photo of a small bakery storefront with a wooden sign above the door that reads OPEN in bold white letters, daylight, photorealistic", 1280, 768,
                     "Reference with legible text for Edit Text."),
}
PERSON, MAN, WOMAN, PRODUCT, SNEAKER, SCENE, LAKE = "ref-face-a", "ref-fx-man-b", "ref-fx-woman-a", "ref-product", "ref-fx-sneaker", "ref-fx-cafe", "ref-fx-lake"

KEEP_PRODUCT = " Keep the product identical: shape, label, text and colors."
KEEP_FACE = " Keep the face, hairstyle and build identical."


def sel(id_, label, options, default=None, help_=None):
    """A select whose value is a prompt fragment; label → value pairs."""
    opts = [{"value": v, "label": lb} for lb, v in options]
    d = {"id": id_, "type": "select", "label": label, "default": default if default is not None else opts[0]["value"], "options": opts}
    if help_:
        d["help"] = help_
    return d


def txt(id_, label, default="", required=False, help_=None):
    d = {"id": id_, "type": "text", "label": label, "default": default}
    if required:
        d["required"] = True
    if help_:
        d["help"] = help_
    return d


# (id, name, Higgsfield app, web category, base, image label, summary, prompt, extra inputs, lab reference, lab values, what to look for)
T = []


def A(id_, name, feature, cat, base, image_label, summary, prompt, inputs=(), ref=None, values=None, note=""):
    T.append(dict(id=id_, name=name, feature=feature, cat=cat, base=base, image_label=image_label, summary=summary, prompt=prompt,
                  inputs=list(inputs), ref=ref, values=values or {}, note=note))


# ---------------------------------------------------------------- ads & products (apps/edit pipeline, a product photo)
A("poster", "Poster", "Poster", "ads", "edit", "Product photo",
  "Turns a product photo into a printed advertising poster with your headline (FLUX 3 Image Klein).",
  "A printed advertising poster for the product from <ref_image_0>: the product large in the center, a bold headline reading \"{headline}\" at the top, "
  "a clean typographic layout, studio lighting, vivid colors." + KEEP_PRODUCT,
  [txt("headline", "Headline", "NEW SEASON", required=True)], PRODUCT, {"headline": "NOIR"},
  "A poster layout with the bottle intact and the headline legible.")
A("packshot", "Packshot", "Packshot", "ads", "edit", "Product photo",
  "The closing frame of an ad: your product centered on a clean gradient with room for a tagline.",
  "The closing packshot of a commercial: the product from <ref_image_0> centered on a smooth {backdrop} gradient background, a soft shadow under it, "
  "generous empty space above it." + KEEP_PRODUCT,
  [sel("backdrop", "Backdrop", [("Dark charcoal", "dark charcoal"), ("Clean white", "clean white"), ("Deep blue", "deep blue"), ("Warm beige", "warm beige")])],
  PRODUCT, {}, "Centered bottle, clean gradient, nothing else in frame.")
A("macro-scene", "Macro Scene", "Macroshot Scene", "ads", "edit", "Product photo",
  "An extreme macro close-up of your product in a natural setting: stone, leaves, sand or ice.",
  "Extreme macro close-up of the product from <ref_image_0> {setting}, shallow depth of field, tiny water droplets, crisp texture." + KEEP_PRODUCT,
  [sel("setting", "Setting", [("Wet black stone", "on wet black stone with mist"), ("Green leaves", "among fresh green leaves"), ("Sand at golden hour", "on sand at golden hour"),
                               ("Ice and frost", "on ice with frost crystals")])],
  PRODUCT, {}, "Macro look with droplets; the label still readable.")
A("macro-product", "Macro Product", "Macroshot Product", "ads", "edit", "Product photo",
  "A macro photograph of one detail of your product: texture, edges and label filling the frame.",
  "Extreme macro photograph of a detail of the product from <ref_image_0>: its texture, edges and label fill the frame, 100mm macro lens, soft diffused light." + KEEP_PRODUCT,
  [], PRODUCT, {}, "A tight detail of the bottle, not the whole bottle.")
A("giant-product", "Giant Product", "Giant Product", "ads", "edit", "Product photo",
  "Your product as a giant monument over a city skyline, people tiny at its base.",
  "The product from <ref_image_0> as a giant monument standing over a city skyline {time}, people and cars tiny at its base, wide-angle shot, realistic scale and lighting." + KEEP_PRODUCT,
  [sel("time", "Time of day", [("Sunset", "at sunset"), ("Night, city lights", "at night with the city lights on"), ("Foggy morning", "on a foggy morning")])],
  PRODUCT, {}, "Convincing scale: the bottle towers over buildings.")
A("billboard", "Billboard", "Billboard Ad", "ads", "edit", "Your photo",
  "Your photo on a giant lit billboard over a city street.",
  "The photo from <ref_image_0> displayed on a giant billboard {where}, the billboard lit up, pedestrians and traffic below, realistic.",
  [sel("where", "Where", [("Skyscraper at night", "on a skyscraper at night"), ("Highway at dusk", "over a busy highway at dusk"), ("Rainy city square", "in a rainy city square")])],
  PERSON, {}, "The portrait appears on the billboard, not as the whole image.")
A("graffiti-ad", "Graffiti Ad", "Graffiti Ad", "ads", "edit", "Product photo",
  "Your product as a spray-paint graffiti mural on a brick wall.",
  "The product from <ref_image_0> painted as a large spray-paint graffiti mural on a brick wall in the street, paint drips and stencil edges, daylight. "
  "Keep its shape, label and colors recognizable.",
  [], SNEAKER, {}, "A mural of the sneaker with graffiti texture.")
A("fridge-ad", "Fridge Ad", "Fridge Ad", "ads", "edit", "Product photo",
  "Your product inside an illuminated display fridge, condensation on the glass.",
  "The product from <ref_image_0> standing inside an illuminated glass-door display fridge in a shop, cold light, condensation on the glass, rows of shelves." + KEEP_PRODUCT,
  [], PRODUCT, {}, "Fridge interior with the bottle on a shelf.")
A("ugc-shot", "UGC Shot", "Marketing (UGC)", "ads", "edit", "Product photo",
  "A casual phone photo of a hand holding your product, like a social media post.",
  "A casual phone photo of a hand holding the product from <ref_image_0> {where}, natural light, slightly tilted framing, like a social media post." + KEEP_PRODUCT,
  [sel("where", "Where", [("Bright kitchen", "in a bright kitchen"), ("Cafe table", "at a cafe table"), ("Outdoors in a park", "outdoors in a park")])],
  PRODUCT, {}, "A hand holding the bottle; snapshot look, not studio.")

# ---------------------------------------------------------------- portraits & looks (a photo of a person)
A("headshot", "Studio Headshot", "AI Headshot Generator", "portraits", "edit", "Your selfie",
  "A professional studio headshot from one selfie: backdrop and outfit of your choice.",
  "A professional studio headshot of the same person as in <ref_image_0>, {backdrop}, wearing {outfit}, soft three-point lighting, sharp focus on the eyes, "
  "shoulders-up framing." + KEEP_FACE,
  [sel("backdrop", "Backdrop", [("Light grey", "plain light grey backdrop"), ("Dark charcoal", "dark charcoal backdrop"), ("Office, blurred", "in a bright office with blurred windows"),
                                 ("Outdoor bokeh", "outdoors with golden-hour bokeh")]),
   sel("outfit", "Outfit", [("Navy blazer", "a navy blazer over a white shirt"), ("Black turtleneck", "a black turtleneck"), ("Linen shirt", "a light linen shirt"),
                             ("As in the photo", "the same clothes as in the photo")])],
  WOMAN, {}, "Same face, studio light, blazer; shoulders-up.")
A("commercial-faces", "Commercial Faces", "Commercial Faces", "portraits", "edit", "Your photo",
  "Campaign portraits of you: skincare, corporate, sportswear or editorial.",
  "A commercial campaign portrait of the same person as in <ref_image_0> for {use}, professional lighting, editorial composition, magazine print quality." + KEEP_FACE,
  [sel("use", "Campaign", [("Skincare advert", "a skincare advert, clean beauty lighting"), ("Corporate brochure", "a bank's corporate brochure"),
                            ("Sportswear", "a sportswear campaign, dynamic pose"), ("Fashion editorial", "a fashion editorial, dramatic side light")])],
  MAN, {}, "Campaign look with his face unchanged.")
A("style-snap", "Style Snap", "Style Snap", "portraits", "edit", "Your photo",
  "You in a complete new outfit: streetwear, business, gala, athleisure, 70s or monochrome.",
  "The same person as in <ref_image_0> wearing a complete {style} outfit, full-length shot in a matching setting, natural pose." + KEEP_FACE,
  [sel("style", "Style", [("Streetwear", "streetwear"), ("Business formal", "business formal"), ("Evening gala", "evening gala"), ("Athleisure", "sporty athleisure"),
                           ("Vintage 70s", "vintage 1970s"), ("Minimal monochrome", "minimalist monochrome")])],
  WOMAN, {"style": "streetwear"}, "Full-length, new outfit, same face.")
A("skin-enhancer", "Skin Enhancer", "Skin Enhancer", "portraits", "edit", "Your photo",
  "A beauty-editor retouch: even tone, natural pores kept, no plastic smoothing.",
  "Retouch the photo from <ref_image_0> like a beauty editor: even skin tone, natural pores and fine texture kept, blemishes reduced, no plastic smoothing. "
  "Everything else stays exactly the same.",
  [], MAN, {}, "Subtle: compare with the input; pores still visible.")
A("outfit-vending", "Outfit Vending", "Outfit Vending Machine", "portraits", "edit", "Your photo",
  "The clothes you are wearing, displayed item by item inside a lit vending machine.",
  "The clothes and accessories worn in <ref_image_0> displayed as separate items inside an illuminated glass vending machine at night, each in its own slot with a "
  "price tag, neon glow.",
  [], "ref-character", {}, "Red jacket, jeans and sneakers as vending items.")
A("glitter-sticker", "Glitter Sticker", "Glitter Sticker", "portraits", "edit", "Your photo",
  "You as a glossy glitter sticker with a white die-cut border.",
  "The person from <ref_image_0> as a glossy glitter sticker: simplified cute illustration, sparkling holographic texture, thick white die-cut border, "
  "on a plain white background.",
  [], WOMAN, {}, "Sticker look: white border, holographic sparkle.")

# ---------------------------------------------------------------- toys & games
A("game-styles", "Game Styles", "Game Dump", "play", "edit", "Your photo",
  "You as a character in 12 kinds of video game, from 16-bit pixel art to voxel worlds.",
  "The same person as in <ref_image_0> as a character in {style}, keep the face recognizable.",
  [sel("style", "Game style", [("16-bit platformer", "a 16-bit pixel art platformer"), ("Low-poly 90s console", "a low-poly 1990s console game"), ("Cel-shaded action", "a cel-shaded action game"),
                                ("Isometric RPG", "an isometric role-playing game"), ("Voxel builder", "a voxel block-building game"), ("Claymation adventure", "a claymation adventure game"),
                                ("Fighting game select screen", "a 2D fighting game character select screen"), ("Visual novel", "a visual novel portrait"),
                                ("Neon cyberpunk shooter", "a neon cyberpunk shooter"), ("Cozy farming sim", "a cozy farming simulator"), ("Kart racer", "a kart racing game"),
                                ("Survival horror", "a survival horror game, no gore")])],
  MAN, {"style": "a cel-shaded action game"}, "Cel-shaded render with his features.")
A("plushie", "Plushie", "Plushies", "play", "edit", "Your photo",
  "The subject of your photo remade as a soft plush toy.",
  "The subject of <ref_image_0> remade as a soft plush toy: fleece fabric, stitched seams, embroidered eyes, sitting on a child's bed, soft daylight.",
  [], "ref-fx-duck", {}, "A plush duck with seams and embroidered eyes.")
A("render-3d", "3D Render", "3D Render", "play", "edit", "Your photo",
  "A stylized 3D render of your photo: clay-like materials, soft studio light.",
  "The subject of <ref_image_0> as a stylized 3D render: smooth clay-like materials, big expressive proportions, soft studio lighting, subtle subsurface scattering, "
  "clean gradient background.",
  [], WOMAN, {}, "3D look, recognizable features.")
A("figure-3d", "3D Figure", "3D Figure", "play", "edit", "Your photo",
  "Your photo as a collectible figure in a blister pack on a shelf.",
  "The subject of <ref_image_0> as a collectible 3D figure in a clear blister pack with a printed cardboard backing, on a shelf, product photography lighting.",
  [], "ref-character", {}, "Figure in packaging, same outfit.")
A("pixel-game", "Pixel Game", "Pixel Game", "play", "edit", "Your photo",
  "Your scene redrawn as 16-bit pixel art with a game HUD.",
  "The scene from <ref_image_0> redrawn as 16-bit pixel art from a retro video game, limited palette, visible pixels, a side-view game HUD at the top.",
  [], SCENE, {}, "Visible pixels, HUD at the top.")
A("brick-toy", "Brick Toy", "Brick Cube", "play", "edit", "Your photo",
  "The subject of your photo rebuilt from interlocking plastic bricks.",
  "The subject of <ref_image_0> rebuilt as a toy made of interlocking plastic bricks, blocky shapes, studs visible, on a white table.",
  [], "ref-fx-toycar", {}, "A brick-built red car with studs.")
A("sketch-to-real", "Sketch to Real", "Sketch-to-Real", "play", "edit", "Your sketch",
  "Turns a sketch into a photorealistic photo of the same scene.",
  "Turn the sketch from <ref_image_0> into a photorealistic photograph of the same scene: same composition and subjects, real materials, natural light.",
  [], "ref-tpl-sketch", {}, "A real cat on a real windowsill, same layout as the sketch.")
A("paint-app", "Paint App", "Paint App", "play", "edit", "Your photo",
  "Your photo redrawn in a 1990s computer paint program.",
  "The photo from <ref_image_0> redrawn as a crude drawing made in a 1990s computer paint program: aliased lines, flat fill colors, a spray-can texture, "
  "white canvas with the program's toolbar at the edge.",
  [], WOMAN, {}, "Crude flat drawing with a toolbar.")
A("mural", "Street Mural", "Signboard", "play", "edit", "Your photo",
  "You hand-painted on a large street mural.",
  "The person from <ref_image_0> hand-painted on a large street mural on the side of a building, visible brush strokes, weathered paint, pedestrians passing below.",
  [], MAN, {}, "Painted wall with his face, street below.")
A("micro-beasts", "Micro-Beasts", "Surrounded by Animals", "play", "edit", "Your photo",
  "You surrounded by tiny cute animals.",
  "The person from <ref_image_0> surrounded by tiny cute animals: {animals} climbing on their shoulders and hands, sharp detail, soft daylight." + KEEP_FACE,
  [sel("animals", "Animals", [("Hamsters and kittens", "hamsters and kittens"), ("Ducklings and bunnies", "ducklings and bunnies"), ("Tiny puppies", "tiny puppies"), ("Baby otters", "baby otters")])],
  WOMAN, {}, "Small animals on her shoulders; same face.")
A("meme", "Meme Generator", "Meme Generator", "play", "z-image", None,
  "A meme image from a scene and two captions (Z-Image Turbo).",
  "A meme image: {scene}. Bold white capital letters in a thick Impact-style font with a black outline read \"{top}\" at the top and \"{bottom}\" at the bottom of the image.",
  [{"id": "scene", "type": "textarea", "label": "Scene", "required": True, "default": "a cat staring at a laptop screen with a worried face"},
   txt("top", "Top text", "WHEN THE BUILD", required=True), txt("bottom", "Bottom text", "PASSES ON FRIDAY", required=True)],
  None, {"scene": "a golden retriever sitting at a desk in front of three monitors, looking proud", "top": "WHEN THE TESTS", "bottom": "PASS FIRST TRY"},
  "Legible captions top and bottom.")

# ---------------------------------------------------------------- templates (looks and scenes over a photo)
A("j-magazine", "J-Magazine", "J-Magazine", "templates", "edit", "Your photo",
  "You on the cover of a Japanese fashion magazine.",
  "The person from <ref_image_0> on the cover of a Japanese fashion magazine: bold vertical Japanese headlines, a masthead at the top, colorful text blocks, glossy print look." + KEEP_FACE,
  [], WOMAN, {}, "Magazine cover layout with her face.")
A("cafe-60s", "60s Cafe", "60s Cafe", "templates", "edit", "Your photo",
  "You in a 1960s cafe: period clothes, chrome counter, film grain.",
  "The person from <ref_image_0> sitting in a 1960s cafe: period clothes and hairstyle, chrome counter, pastel colors, Kodachrome film grain, warm light." + KEEP_FACE,
  [], MAN, {}, "Period look, same face.")
A("victory-card", "Victory Card", "Victory Card", "templates", "edit", "Your photo",
  "Your face on a playing card in a winning poker hand.",
  "The person from <ref_image_0> as the face of a king or queen playing card in a winning poker hand, ornate card design, gold foil, five cards fanned on green felt.",
  [], WOMAN, {}, "Her face on the court card.")
A("j-poster", "J-Poster", "J-Poster", "templates", "edit", "Your photo",
  "A Japanese-style graphic poster of you.",
  "A Japanese-style poster featuring the person from <ref_image_0>: bold red and black graphic design, vertical typography, rising-sun rays, print texture." + KEEP_FACE,
  [], MAN, {}, "Bold graphic poster with his face.")
A("mascot", "Mascot", "Mascot", "templates", "edit", "Your photo",
  "You in a football club mascot costume on the pitch.",
  "The person from <ref_image_0> in a full football club mascot costume: an oversized foam head of a {animal} held under one arm, team colors, standing on a stadium pitch, "
  "the crowd behind." + KEEP_FACE,
  [sel("animal", "Mascot", [("Lion", "lion"), ("Eagle", "eagle"), ("Bulldog", "bulldog"), ("Bear", "bear")])],
  MAN, {}, "Mascot suit, foam head under the arm, his face visible.")
A("burning-sunset", "Burning Sunset", "Burning Sunset", "templates", "edit", "Your photo",
  "Your scene under a blazing sunset sky.",
  "The scene from <ref_image_0> under a blazing sunset: the sky on fire with orange and crimson clouds, long shadows, warm light on everything, composition unchanged.",
  [], LAKE, {}, "Same lake, fiery sky.")
A("comic-book", "Comic Book", "Comic Book", "templates", "edit", "Your photo",
  "Your photo as a comic book panel: ink lines, halftone, a caption box.",
  "The photo from <ref_image_0> as a comic book panel: bold ink outlines, halftone dots, flat colors, an action caption box, dynamic framing.",
  [], SCENE, {}, "Inked panel with halftone.")
A("giallo", "Giallo Horror", "Giallo Horror", "templates", "edit", "Your photo",
  "A 1970s Italian giallo film still: red and blue gels, deep shadows, no blood.",
  "The person from <ref_image_0> in a 1970s Italian giallo film still: saturated red and blue gel lighting, deep shadows, a gloved hand at the edge of the frame, "
  "film grain. No blood, no wounds." + KEEP_FACE,
  [], WOMAN, {}, "Gel lighting and grain; nothing gory.")
A("renaissance", "Renaissance", "Renaissance", "templates", "edit", "Your photo",
  "You as a Renaissance oil painting in a gilded museum frame.",
  "The person from <ref_image_0> as a Renaissance oil painting: chiaroscuro light, period clothing, cracked varnish, in an ornate gilded frame on a museum wall." + KEEP_FACE,
  [], MAN, {}, "Oil painting in a frame, same face.")
A("japanese-show", "Japanese Show", "Japanese Show", "templates", "edit", "Your photo",
  "You on a retro Japanese TV variety show, 4-panel screen.",
  "The person from <ref_image_0> on a retro Japanese TV variety show: a 4-panel screen layout, bright studio set, colorful caption text overlays, 1990s broadcast look." + KEEP_FACE,
  [], WOMAN, {}, "Four panels, TV captions.")
A("breakdown", "Breakdown", "Breakdown", "templates", "edit", "Your photo",
  "The subject of your photo taken apart into labeled components, knolling style.",
  "The subject of <ref_image_0> taken apart into its components, laid out neatly on a grid with small labels, knolling photography, top-down, white background.",
  [], SNEAKER, {}, "Sole, laces, upper laid out on a grid.")
A("edit-text", "Edit Text", "Edit Text", "templates", "edit", "Image with text",
  "Replaces the text written in an image, keeping the font and perspective.",
  "Replace the text \"{old}\" with \"{new}\" in <ref_image_0>, keeping the same font, color, size and perspective; nothing else changes.",
  [txt("old", "Text to replace", required=True), txt("new", "New text", required=True)],
  "ref-tpl-sign", {"old": "OPEN", "new": "CLOSED"}, "The sign now reads CLOSED in the same style.")
A("image-effects", "Image Effects", "Image Effects", "templates", "edit", "Your photo",
  "Ten effects for a photo: glitch, double exposure, neon, sketch, watercolor and more.",
  "Apply a {effect} effect to the photo from <ref_image_0>; keep the composition.",
  [sel("effect", "Effect", [("Glitch", "glitch distortion with RGB split"), ("Double exposure", "double exposure with a forest"), ("Neon outline", "neon outline glow"),
                              ("Pencil sketch", "pencil sketch"), ("Watercolor", "watercolor painting"), ("Pop art", "pop art screen print"), ("Vintage film", "vintage faded film"),
                              ("Infrared", "infrared false-color"), ("Anaglyph 3D", "anaglyph 3D"), ("Thermal camera", "thermal camera")])],
  SCENE, {"effect": "glitch distortion with RGB split"}, "RGB split and glitch bands over the cafe.")
A("color-grade", "Color Grade", "Color Grading", "templates", "edit", "Your photo",
  "Six color grades for a photo: teal and orange, vintage film, noir, pastel, B&W, golden hour.",
  "Color grade the photo from <ref_image_0> with a {look} look; keep every detail and the composition.",
  [sel("look", "Look", [("Teal and orange", "teal and orange blockbuster"), ("Warm vintage film", "warm vintage film"), ("Cold noir", "cold desaturated noir"),
                         ("Pastel", "soft pastel"), ("High-contrast B&W", "high-contrast black and white"), ("Golden hour", "golden hour glow")])],
  SCENE, {"look": "teal and orange blockbuster"}, "Only the colors change.")


def check() -> None:
    ids = [t["id"] for t in T]
    assert len(ids) == len(set(ids)), "duplicate ids"
    store = (ROOT / "web" / "js" / "catalog.js").read_text(encoding="utf-8")
    missing = [i for i in ids if f'"{i}"' not in store]
    assert not missing, f"not in web/js/catalog.js CATEGORIES: {missing}"
    existing = {p.name for p in (ROOT / "apps").iterdir() if p.is_dir()}
    for t in T:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", t["id"]), t["id"]
        assert t["id"] not in existing or (ROOT / "apps" / t["id"] / "app.json").exists() and "tools/template_apps.py" in (ROOT / "apps" / t["id"] / "app.json").read_text(encoding="utf-8"), f"{t['id']} is a hand-made app"
        assert len(t["name"]) <= 40 and len(t["summary"]) <= 160, t["id"]
        assert t["base"] in BASES, t["id"]
        used = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", t["prompt"]))
        have = {i["id"] for i in t["inputs"]}
        assert used <= have, (t["id"], used - have)
        assert have <= used, (t["id"], have - used)
        for i in t["inputs"]:
            assert i["id"] not in ("image", "details", "steps", "seed", "width", "height"), (t["id"], i["id"])
        if t["base"] == "z-image":
            assert t["ref"] is None and t["image_label"] is None
        else:
            assert t["ref"], t["id"]
        for k in t["values"]:
            assert k in have, (t["id"], k)


def manifest(t: dict) -> dict:
    base = BASES[t["base"]]
    src = json.loads((ROOT / "apps" / base["app"] / "app.json").read_text(encoding="utf-8"))
    keep = {i["id"]: i for i in src["inputs"] if i["id"] in base["keep"]}
    inputs = []
    if base["image"]:
        inputs.append({"id": "image", "type": "image", "label": t["image_label"], "required": True, "limits": {"max_mb": 20},
                       "bind": [{"node": base["image"][0], "field": base["image"][1]}]})
    inputs += t["inputs"]
    inputs.append({"id": "details", "type": "textarea", "label": "Extra direction", "help": "Added at the end of the app's prompt.",
                   "bind": [{"node": base["prompt"][0], "field": base["prompt"][1], "template": t["prompt"] + " {details}"}]})
    inputs += [keep[k] for k in base["keep"]]
    test = {"image": "test/portrait.png"} if base["image"] else {}
    test.update(t["values"])
    return {
        "$schema": "../../schema/app.schema.json",
        "id": t["id"], "name": t["name"], "section": "image",
        "summary": t["summary"],
        "higgsfield_feature": t["feature"],
        "pack": base["pack"], "status": "ready", "workflow": "workflow.api.json",
        "source": {**src.get("source", {}), "notes": f"Template app written by tools/template_apps.py: the workflow is apps/{base['app']}'s "
                   f"(built by tools/build_apps.py) and the prompt below is fixed; \"Extra direction\" is appended to it."},
        "inputs": inputs,
        "outputs": [{**base["output"], "label": "Result"}],
        "models": src["models"],
        "credits": src.get("credits", []),
        "test": test,
    }


def cases() -> list[str]:
    j = lambda o: json.dumps(o, ensure_ascii=False)  # noqa: E731
    lines = []
    for rid, (prompt, w, h, note) in REFS.items():
        lines.append(f'    {{"id": "{rid}", "app": "z-image", "values": {j({"prompt": prompt, "width": w, "height": h})},\n     "note": {j(note)}}},')
    lines.append("")
    for t in T:
        vals = ({"image": f"@case:{t['ref']}"} if t["ref"] else {}) | t["values"]
        note = j(f"{t['feature']}. {t['note']}")
        lines.append(f'    {{"id": "tpl-{t["id"]}", "showcase": true, "app": "{t["id"]}", "values": {j(vals)},\n'
                     f'     "note": {note}}},')
    lines[-1] = lines[-1].rstrip(",")
    return lines


def write_cases() -> int:
    path = ROOT / "lab" / "cases.json"
    text = path.read_text(encoding="utf-8")
    marker = "\n  ]\n}\n"
    assert text.endswith(marker), repr(text[-40:])
    start = text.find('    {"id": "ref-tpl-')
    if start >= 0:   # the template section is the last one: replace it
        body = text[:start].rstrip()
        assert body.endswith(","), body[-60:]
        body = body[:-1]
    else:
        body = text[: -len(marker)]
    new = body + ",\n\n" + "\n".join(cases()) + marker
    data = json.loads(new)
    path.write_text(new, encoding="utf-8")
    return len(data["cases"])


def readme() -> str:
    rows = ["| App | Rebuilds | Base | Inputs |", "|---|---|---|---|"]
    for t in T:
        extra = ", ".join(i["label"].lower() for i in t["inputs"])
        rows.append(f"| `{t['id']}` | {t['feature']} | `{BASES[t['base']]['app']}` | {t['image_label'].lower() + (', ' if extra else '') if t['image_label'] else ''}{extra} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--readme", action="store_true")
    ap.add_argument("--lab", action="store_true")
    a = ap.parse_args(argv)
    check()
    if a.readme:
        print(readme())
        return 0
    if a.lab:
        print("modal run --detach lab/lab_modal.py --only " + ",".join(f"tpl-{t['id']}" for t in T) + " --shards 2")
        return 0
    if a.check:
        print(f"{len(T)} template apps ok")
        return 0
    for t in T:
        d = ROOT / "apps" / t["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "app.json").write_text(json.dumps(manifest(t), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        wf = (ROOT / "apps" / BASES[t["base"]]["app"] / "workflow.api.json").read_text(encoding="utf-8")
        (d / "workflow.api.json").write_text(wf, encoding="utf-8")
    print(f"apps/: {len(T)} template apps written")
    print(f"lab/cases.json: {write_cases()} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())

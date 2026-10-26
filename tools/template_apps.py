#!/usr/bin/env python3
"""Template apps: one app per Higgsfield app that is a fixed prompt over a pipeline Freefield already runs.

    python tools/template_apps.py            # writes apps/<id>/app.json + workflow.api.json and the tpl-* lab cases
    python tools/template_apps.py --check    # only checks the table (ids, lengths, placeholders)
    python tools/template_apps.py --readme   # prints the Markdown table for README.md
    python tools/template_apps.py --lab      # prints the lab command that makes every template's example

Each entry below is a Higgsfield app (its name in `feature`) rebuilt as a prompt template on one of
these bases, all workflows built by tools/build_apps.py:
  edit       FLUX 3 Image Klein's edit pipeline (apps/edit), one reference image
  edit2      the same with a second reference image (a garment, another person, a face); with
             face_mask, MediaPipe finds the face in the first image and Klein redraws only that oval,
             with the second image as its only reference (with both, it copied the first face back)
  z-image    Z-Image Turbo (apps/z-image), text to image
  video      LTX-2.5 image-to-video (apps/video), with its own audio
  qwen-edit  Qwen-Image-Edit-2509 (apps/relight) with a different LoRA: Multiple Angles or next-scene
  morph      FLUX 3 Klein draws the last frame from the photo and LTX-2.5 + the transition LoRA moves
             the photo into it (apps/morph): for clips where the scene must change around a subject
             that has to stay the same (a face, a product); "klein" is that fixed instruction
  effect     Wan 2.1 image-to-video with one effect LoRA fixed (apps/effects); "effect_lora" names it
  effect-klein  the same, after FLUX 3 Klein redraws the photo with the fixed "klein" instruction
             (merged in as edit:*): for effects that need another background or something added first
  edit + outpaint  the edit pipeline on a bigger canvas: the photo sits on a stretched, blurred copy of itself,
             with a noise mask on the border, so only the border is drawn; a select sets the padding
The app folder gets the base workflow (copied, or with the few edits noted in BASES) and a manifest
whose "details" input carries the prompt as a bind template; selects feed {placeholders} in that
prompt. The base app's models and credits are copied as they are (qwen-edit swaps the LoRA).

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

# the pipelines a template can sit on: node ids for the image(s), the prompt and the settings kept from the base app
BASES = {
    "edit": {"app": "edit", "section": "image", "pack": "image-flux3", "image": ("11", "image"), "prompt": ("4", "text"), "keep": ("steps", "seed"),
             "output": {"node": "9", "type": "image"}},
    "edit2": {"app": "edit", "section": "image", "pack": "image-flux3", "image": ("11", "image"), "image2": ("12", "image"), "prompt": ("4", "text"),
              "keep": ("steps", "seed"), "output": {"node": "9", "type": "image"}},
    "klein": {"app": "create-image", "section": "image", "pack": "image-flux3", "image": None, "prompt": ("18:17", "value"),
              "keep": ("aspect", "resolution", "steps", "seed"), "output": {"node": "9", "type": "image"}},
    "z-image": {"app": "z-image", "section": "image", "pack": "image", "image": None, "prompt": ("57:27", "text"), "keep": ("width", "height", "steps", "seed"),
                "output": {"node": "9", "type": "image"}},
    "video": {"app": "video", "section": "video", "pack": "video-ltx25", "image": ("395", "image"), "prompt": ("398:376", "value"),
              "keep": ("duration", "enhance", "aspect", "seed"), "output": {"node": "75", "type": "video"}},
    "qwen-edit": {"app": "relight", "section": "image", "pack": "image-qwen-edit", "image": ("11", "image"), "prompt": ("15", "value"), "keep": ("seed",),
                  "output": {"node": "12", "type": "image"}},
    "morph": {"app": "morph", "section": "video", "pack": "video-ltx25", "image": ("31", "image"), "prompt": ("251:252", "value"), "klein": ("edit:4", "text"),
              "keep": ("aspect", "duration", "strength", "seed"), "output": {"node": "68", "type": "video"}},
    "effect": {"app": "effects", "section": "video", "pack": "video-wan-effects", "image": ("52", "image"), "prompt": ("6", "text"),
               "keep": ("strength", "aspect", "frames", "seed"), "output": {"node": "56", "type": "video"}},
    "effect-klein": {"app": "effects", "section": "video", "pack": "video-wan-effects", "image": ("52", "image"), "prompt": ("6", "text"),
                     "klein": ("edit:4", "text"), "keep": ("strength", "aspect", "frames", "seed"), "output": {"node": "56", "type": "video"}},
}
BULLET_TIME = "Wan21_I2V_rotation_000003750.safetensors"   # joyfox's Bullet Time LoRA (Apache-2.0), the effects app's "Bullet time"
BULLET_TRIGGER = "rw360xz，人物定在空中，相机视角围绕人物向一个方向旋转。"   # its trigger words, as on its model card


# MediaPipe Face Landmarker as ComfyUI's native nodes load it (comfy_extras/nodes_mediapipe.py, blueprint "Image Face Detection")
FACE_MODEL = {"repo": "Comfy-Org/mediapipe", "file": "detection/mediapipe_face_fp32.safetensors", "dir": "detection", "gb": 0.01, "phase": "encode",
              "license": "Apache-2.0"}

# LoRAs the qwen-edit templates load instead of Relight (file name as ComfyUI sees it)
QWEN_LORAS = {
    "angles": {"repo": "dx8152/Qwen-Edit-2509-Multiple-angles", "file": "镜头转换.safetensors", "gb": 0.24, "license": "Apache-2.0",
               "credit": "Multiple Angles LoRA by dx8152 (Apache-2.0)"},
    "next-scene": {"repo": "lovis93/next-scene-qwen-image-lora-2509", "file": "next-scene_lora-v2-3000.safetensors", "gb": 0.3, "license": "MIT",
                   "credit": "next-scene LoRA v2 by lovis93 (MIT)"},
}

# new synthetic references the template cases need (the rest come from the effects section)
REFS = {
    "ref-tpl-sketch": ("A rough pencil sketch on white paper of a cat sitting on a windowsill next to a potted plant, loose lines, no color", 1024, 1024,
                       "Reference sketch for Sketch to Real."),
    "ref-tpl-sign": ("Photo of a small bakery storefront with a wooden sign above the door that reads OPEN in bold white letters, daylight, photorealistic", 1280, 768,
                     "Reference with legible text for Edit Text."),
}
REFS["ref-tpl-garment"] = ("Product photo of a mustard yellow knit cardigan laid flat on a plain white background, top-down, soft even light", 1024, 1024,
                           "A garment on its own, for the two-reference apps.")
PERSON, MAN, WOMAN, PRODUCT, SNEAKER, SCENE, LAKE = "ref-face-a", "ref-fx-man-b", "ref-fx-woman-a", "ref-product", "ref-fx-sneaker", "ref-fx-cafe", "ref-fx-lake"
WOMAN_B, STREET, STORM, ROAD, GARMENT, CHARACTER = "ref-fx-woman-b", "ref-fx-street", "ref-fx-storm", "ref-fx-road-plain", "ref-tpl-garment", "ref-character"
PORTRAIT = "9:16 (Portrait Widescreen)"

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


def A(id_, name, feature, cat, base, image_label, summary, prompt, inputs=(), ref=None, values=None, note="", image2_label=None, ref2=None, lora=None, help_=None,
      defaults=None, klein=None, face_mask=False, effect_lora=None, outpaint=False, sidebar=False, modes=None, mode_label=None):
    """defaults: new defaults for settings kept from the base app (say, the LTX enhancer off); klein: the morph and effect-klein bases' Klein
    instruction; face_mask (edit2): redraw only the face oval MediaPipe finds in the first image, so the rest of it stays as it is;
    effect_lora: the effect bases' LoRA file; outpaint (edit): draw only a border added around the photo (a select's sets pad it);
    modes, mode_label: sibling apps shown as a switch at the top of the form, and this app's name in it."""
    T.append(dict(id=id_, name=name, feature=feature, cat=cat, base=base, image_label=image_label, summary=summary, prompt=prompt,
                  inputs=list(inputs), ref=ref, values=values or {}, note=note, image2_label=image2_label, ref2=ref2, lora=lora, help=help_,
                  defaults=defaults or {}, klein=klein, face_mask=face_mask, effect_lora=effect_lora, outpaint=outpaint, sidebar=sidebar,
                  modes=modes, mode_label=mode_label))


def pad(left, top, right, bottom):
    """The sets of an outpaint select option: pixels added on each side of the photo (scaled to 1 MP first), and
    where the photo sits on the filled canvas."""
    return ([{"node": "op_pad", "field": f, "value": v} for f, v in (("left", left), ("top", top), ("right", right), ("bottom", bottom))]
            + [{"node": "op_fill", "field": "x", "value": left}, {"node": "op_fill", "field": "y", "value": top}])


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
  "Add a hand holding this product from below and replace the background with {where}, as a casual phone snapshot with slightly tilted framing and natural "
  "light. The product itself does not change: same angle, same size, and the label text stays sharp and perfectly legible, exactly as written in the photo.",
  [sel("where", "Where", [("Bright kitchen", "a bright kitchen"), ("Cafe table", "a busy cafe"), ("Outdoors in a park", "a sunny park")])],
  PRODUCT, {}, "A hand holding the bottle; snapshot look, label legible (tplx-ugc-shot-a, 23 Oct).")

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
  "Turn this photo into {use} Keep the face identical. No text, letters or logos anywhere in the image.",
  [sel("use", "Campaign", [
      ("Sportswear", "a sportswear campaign shot: the same person in a black athletic top, a light sheen of sweat, dramatic low-key lighting with a rim light, "
                     "dark concrete gym background, intense look at the camera, editorial composition."),
      ("Skincare advert", "a skincare advertisement: the same person in a soft white top with glowing dewy skin, holding a small white jar of face cream near "
                          "the cheek, bright white studio with soft beauty-dish lighting, clean pastel backdrop, glossy magazine composition."),
      ("Corporate brochure", "a corporate brochure portrait: the same person in a tailored navy suit, standing in a bright glass office with a blurred city "
                             "view behind, soft window light, confident friendly expression, crisp professional photography."),
      ("Fashion editorial", "a fashion editorial shot: the same person in a structured designer coat, dramatic side light carving the face, a seamless "
                            "colored paper backdrop, a strong pose, high-end magazine photography.")])],
  MAN, {}, "Campaign look with his face unchanged and no invented text (tplx-commercial-faces-b, 23 Oct).")
A("style-snap", "Style Snap", "Style Snap", "portraits", "edit", "Your photo",
  "You in a complete new outfit: streetwear, business, gala, athleisure, 70s or monochrome.",
  "The same person as in <ref_image_0> wearing a complete {style} outfit, full-length shot in a matching setting, natural pose. "
  "Every piece of clothing and both shoes are unbranded, plain designs with no logos or brand marks." + KEEP_FACE,
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
  "Turn this photo into a stylized 3D character render like a still from a modern animated film: the same person as a 3D cartoon character with smooth "
  "skin, large expressive eyes, exaggerated proportions, matte clay-like materials, soft studio lighting with subsurface scattering, clean gradient "
  "background; same hairstyle and clothes.",
  [], WOMAN, {}, "3D character look, recognizable hair and clothes (tplx-render-3d-a, 23 Oct).")
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
A("meme", "Meme Generator", "Meme Generator", "play", "klein", None,
  "A meme image from a scene and two captions (FLUX 3 Klein).",
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
  "Make one large ornate playing card, the queen of hearts, lying on green casino felt next to a stack of poker chips. The card's portrait is this person's "
  "face, large and clearly recognizable, drawn in the classic playing-card illustration style with gold foil borders and the Q and heart symbols in the corners.",
  [], WOMAN, {}, "Her face on the queen of hearts (tplx-victory-card-a, 23 Oct).")
A("j-poster", "J-Poster", "J-Poster", "templates", "edit", "Your photo",
  "A Japanese-style graphic poster of you.",
  "A Japanese-style poster featuring the person from <ref_image_0>: bold red and black graphic design, vertical typography, rising-sun rays, print texture." + KEEP_FACE,
  [], MAN, {}, "Bold graphic poster with his face.")
A("mascot", "Mascot", "Mascot", "templates", "edit", "Your photo",
  "You in a football club mascot costume on the pitch.",
  "The person from <ref_image_0> in a full football club mascot costume: an oversized foam head of a {animal} held under one arm, team colors, standing on a stadium pitch, "
  "the crowd behind. The kit is a plain unbranded club kit with only a simple club crest: no sportswear brand logos, stripes or marks." + KEEP_FACE,
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
  "Apply {effect} to this photo; the scene stays recognizable.",
  [sel("effect", "Effect", [
      ("Glitch", "a heavy digital glitch effect: strong horizontal displacement bands, red and cyan RGB channel split, blocky pixel corruption, scan lines and data-mosh smears across the frame"),
      ("Double exposure", "a double exposure: the silhouette of the main subject filled with a pine forest and mountains at dusk, the background faded to "
                          "white, a soft fine-art blend"),
      ("Neon outline", "glowing neon outlines: bright pink and cyan neon tubes trace the edges of the subject and the main shapes, the rest of the photo "
                       "darkened to near black"),
      ("Pencil sketch", "a graphite pencil sketch look: the whole photo redrawn as a detailed pencil drawing on white paper, hatching for the shadows, no color"),
      ("Watercolor", "a watercolor painting look: soft washes of color bleeding into each other, visible paper texture, loose brush edges, white paper "
                     "showing through"),
      ("Pop art", "a pop art look: bold flat colors, thick black outlines and halftone dots, like a 1960s comic print"),
      ("Vintage film", "a vintage 1970s film photo look: faded warm colors, lifted blacks, heavy film grain, light leaks and a slight blur"),
      ("Infrared", "an infrared photo look: foliage and skin turned pale white and pink, dark skies, high contrast, a dreamy glow"),
      ("Anaglyph 3D", "a red-cyan anaglyph 3D look: the image doubled, a red copy shifted left and a cyan copy shifted right, like an old 3D-glasses print"),
      ("Thermal camera", "a thermal camera look: false colors from deep blue for cold to yellow and white for warm, people glowing orange and yellow, no fine "
                         "texture")])],
  SCENE, {"effect": "a heavy digital glitch effect: strong horizontal displacement bands, red and cyan RGB channel split, blocky pixel corruption, scan lines and data-mosh smears across the frame"}, "Strong RGB split and glitch bands over the cafe (tplx-image-effects-a, 23 Oct).")
A("color-grade", "Color Grade", "Color Grading", "templates", "edit", "Your photo",
  "Six color grades for a photo: teal and orange, vintage film, noir, pastel, B&W, golden hour.",
  "Color grade this photo with {look}; keep every detail and the composition.",
  [sel("look", "Look", [
      ("Teal and orange", "a strong teal and orange cinematic grade, shadows pushed to deep teal, skin tones and highlights warm orange, high contrast, slightly lifted blacks, fine film grain, like a blockbuster movie still"),
      ("Warm vintage film", "a warm vintage film grade, golden-brown midtones, faded blacks, soft contrast, a slight green in the shadows and fine grain"),
      ("Cold noir", "a cold noir grade, heavily desaturated, blue-black shadows, pale cool skin, crushed blacks, hard contrast, a faint cyan tint in the highlights"),
      ("Pastel", "a soft pastel grade, low contrast, lifted shadows, pale pink, mint and lavender tints, bright airy highlights"),
      ("High-contrast B&W", "a high-contrast black and white grade, no color at all, deep blacks, bright whites, strong local contrast and visible grain"),
      ("Golden hour", "a golden hour grade, warm amber light over everything, warm highlights on the skin, a soft orange glow, gentle contrast")])],
  SCENE, {"look": "a strong teal and orange cinematic grade, shadows pushed to deep teal, skin tones and highlights warm orange, high contrast, slightly lifted blacks, fine film grain, like a blockbuster movie still"}, "Teal shadows, orange skin; nothing else changes (tplx-color-grade-a, 23 Oct).")

# ---------------------------------------------------------------- two reference images (edit2: person + garment, scene + person, photo + face)
A("fashion-factory", "Fashion Factory", "Fashion Factory", "portraits", "edit2", "Your photo",
  "A fashion catalog photo of you wearing a garment from a second photo.",
  "A fashion catalog photo: the person from <ref_image_0> wearing the garment from <ref_image_1>, full-length, {scene}. Keep the face identical and the garment's "
  "cut, color and pattern exactly as in its photo.",
  [sel("scene", "Scene", [("Studio cyclorama", "in a white studio cyclorama"), ("City street, golden hour", "on a city street at golden hour"), ("Minimalist loft", "in a minimalist loft"),
                          ("Runway", "walking a runway under spotlights")])],
  WOMAN, {}, "She wears the yellow cardigan; catalog framing.", image2_label="Garment photo", ref2=GARMENT)
A("try-on", "Virtual Try-On", "AI Stylist", "portraits", "edit2", "Your photo",
  "Try a garment on your own photo: same pose, same background, new clothes.",
  "The person from <ref_image_0> wearing the clothing item from <ref_image_1>, same pose, framing and background as <ref_image_0>, natural fit and folds. "
  "Keep the face and everything else identical; keep the garment's color and pattern.",
  [], MAN, {}, "Same photo of him, now in the cardigan.", image2_label="Garment photo", ref2=GARMENT)
A("outfit-swap", "Outfit Swap", "Outfit Swap", "portraits", "edit2", "Your photo",
  "Wear the whole outfit of the person in another photo.",
  "The person from <ref_image_0> now dressed in the complete outfit worn by the person in <ref_image_1>, same pose, framing and background as <ref_image_0>. "
  "Keep the face identical.",
  [], PERSON, {}, "She wears his red jacket, jeans and sneakers.", image2_label="Photo of the outfit", ref2=CHARACTER)
A("outfit-shot", "Outfit Shot", "Outfit Shot", "portraits", "edit2", "Model photo",
  "A studio fashion shot of a garment on a model from your photo.",
  "A studio fashion photo of the person from <ref_image_0> modeling the garment from <ref_image_1}, {pose}, clean studio backdrop, soft light. "
  "Keep the face identical and the garment exactly as in its photo.".replace("<ref_image_1}", "<ref_image_1>"),
  [sel("pose", "Pose", [("Standing", "standing straight, hands relaxed"), ("Walking", "mid-step, walking toward the camera"), ("On a stool", "sitting on a wooden stool")])],
  WOMAN_B, {}, "Studio shot in the cardigan, same face.", image2_label="Garment photo", ref2=GARMENT)
A("character-swap", "Character Swap", "Character Swap", "identity", "edit2", "Scene photo",
  "Replaces the person in a scene with the person from a second photo.",
  "The scene from <ref_image_0> with its main person replaced by the person from <ref_image_1>: same pose, framing, lighting and clothing as the scene; "
  "the new person's face, hair and build.",
  [], SCENE, {}, "The woman sits in the cafe in the man's place and pose.", image2_label="Photo of the new person", ref2=WOMAN)
A("face-swap", "Face Swap", "Face Swap", "identity", "edit2", "Photo to edit",
  "Puts the face from a second photo onto the first; for faces you own or have permission to use.",
  "Give this person exactly the face of the person in image 1: the same eyes, nose, mouth, brows and face shape as image 1. Keep this photo's own "
  "hairline and hair; match its head angle, expression, lighting and skin tone.",
  [], PERSON, {}, "Her portrait with the other woman's face; hair, jacket and background untouched (tplx-face-swap-g, 24 Oct).", image2_label="Photo of the face", ref2=WOMAN,
  help_="Only faces you own or have permission to use.", face_mask=True)

# ---------------------------------------------------------------- video templates (LTX-2.5 image-to-video, with sound)
A("behind-the-scenes", "Behind the Scenes", "Behind the Scenes", "clips", "video", "Your photo",
  "The camera pulls back from your photo to reveal the film set around it.",
  "The camera pulls back from the photo to reveal a film set around it: crew members, a boom microphone, softbox lights and a clapperboard, people moving about; "
  "the sound of a busy set, a director calling \"rolling\".",
  [], PERSON, {"aspect": "16:9 (Widescreen)"}, "A set appears around her as the camera widens.")
A("asmr-product", "ASMR Product", "ASMR Add-On", "ads", "video", "Product photo",
  "Your product in an ASMR clip: tapping, scratching, no music.",
  "An ASMR video: hands with manicured nails slowly tap and scratch the product, turning it under soft light, extreme close-up; crisp tapping and scratching "
  "sounds, no music, no voice.",
  [], PRODUCT, {"aspect": PORTRAIT}, "Hands tap the bottle; tapping sounds.")
A("asmr-whisper", "ASMR Whisper", "ASMR Classic", "clips", "video", "Your photo",
  "You whispering and tapping in a classic ASMR clip.",
  "An ASMR video: the person whispers softly toward the camera and taps their fingers on the table, slow gentle movements, warm low light; soft whispering "
  "and tapping sounds, no music.",
  [], WOMAN, {"aspect": PORTRAIT}, "Whispering and tapping; calm.")
A("asmr-host", "ASMR Host", "ASMR Host", "clips", "video", "Your photo",
  "You hosting an ASMR studio with a big microphone and fairy lights.",
  "The person sits in a cozy ASMR studio with a large microphone in front of them, fairy lights behind, and whispers into the mic while gently handling a soft "
  "brush; close whispering sound.",
  [], MAN, {"aspect": PORTRAIT}, "Studio, mic, whisper.")
A("chameleon", "Chameleon", "Chameleon", "ads", "morph", "Product photo",
  "A chameleon in your product's colors appears on it; the product stays as it is.",
  "A chameleon climbs up onto the product and its skin shifts to the product's own colors and pattern, it blinks and rolls one eye; soft jungle ambience.",
  [txt("colors", "Product colors", "bright white with bold red patches", required=True,
       help_="The product's main colors; the chameleon takes them on, so it blends into the product.")],
  SNEAKER, {"aspect": "landscape", "duration": 4, "colors": "bright white with bold red patches"},
  "A white and red chameleon on the sneaker; the sneaker unchanged (tplx-chameleon-m2, 24 Oct).",
  defaults={"aspect": "landscape"},
  klein="Add a chameleon perched on top of this exact product. The chameleon is {colors} on its head, back and tail, the same colors as the product, "
        "so it blends into it. The product itself unchanged, same background, macro product photo.")
A("magic-button", "Magic Button", "Magic button", "ads", "video", "Product photo",
  "A glowing button turns the scene around your product magical.",
  "A hand presses a big glowing button next to the product; the scene transforms into a magical world with floating sparks and soft light, the product "
  "levitating and turning slowly; a magical chime.",
  [], PRODUCT, {"aspect": PORTRAIT}, "Button, sparks, the bottle floats.")
A("truck-ad", "Truck Ad", "Truck Ad", "ads", "video", "Product photo",
  "A toy delivery truck with your product printed on its side drives up and parks beside it.",
  "The product stays in the center of the frame, in sharp focus, camera locked. A toy-sized white delivery truck drives into the frame along the surface, "
  "this exact product printed on its side panel, and parks beside the product. Soft toy engine sound.",
  [], PRODUCT, {"aspect": "16:9 (Widescreen)", "enhance": False}, "A toy truck with the bottle printed on it parks beside it (tplx-truck-ad-b, 23 Oct).",
  defaults={"enhance": False})
A("kick-ad", "Kick Ad", "Kick Ad", "ads", "video", "Product photo",
  "Plain grey boxes slide at your product and get knocked off screen while it stands still.",
  "The product stands in the exact center of the frame and does not move at all for the whole shot; the camera is locked. Plain grey cardboard boxes "
  "slide in from the left and from the right and are knocked away the moment they touch it, flying off and tumbling out of the frame, while the product "
  "stays still and upright in the center until the last frame. Cartoon whoosh and thud sounds.",
  [], PRODUCT, {"aspect": "16:9 (Widescreen)", "enhance": False}, "Grey boxes fly off; the bottle never moves. No real brands.",
  defaults={"enhance": False})
A("volcano-ad", "Volcano Ad", "Volcano Ad", "ads", "morph", "Product photo",
  "The background turns into an erupting volcano behind your product.",
  "The background behind the product dissolves into an erupting volcano: lava fountains and glowing ash rise behind it while the product stays in the center, "
  "a red glow spreading over it; a deep rumble.",
  [], PRODUCT, {"aspect": "landscape", "duration": 4}, "The kitchen turns into a volcano behind the bottle; the label stays (first run on the morph base).",
  defaults={"aspect": "landscape"},
  klein="Place this exact product on dark volcanic rock in front of an erupting volcano at dusk: lava fountains and glowing ash behind it, a red glow on "
        "the product, the product large and centered, its shape, colors and label unchanged.")
A("roller-coaster", "Roller Coaster", "Roller Coaster", "clips", "morph", "Your photo",
  "You on a roller coaster: the photo turns into the ride, same face.",
  "The scene turns into a roller coaster ride: the car crests the top and drops, the person screams with joy, hands up, hair whipping, the track rushing "
  "behind; clattering track and wind.",
  [], WOMAN, {"aspect": "portrait", "duration": 4}, "Front seat, hands up, same face (tplx-roller-coaster-m, 23 Oct).",
  klein="Put this exact person in the front seat of a roller coaster car at the top of the first drop: a padded safety bar across the chest, hands in the "
        "air, hair blown back, a wide excited grin, the camera mounted on the car facing them, blue sky and the steel track behind. Keep the face identical.")
A("storm-creature", "Storm Creature", "Storm Creature", "clips", "video", "Your photo",
  "A giant made of storm clouds and lightning rises behind your scene.",
  "The storm clouds over the scene gather into the shape of a colossal cloud giant standing behind it: a face, broad shoulders, two arms spreading wide, "
  "lightning flashing inside its chest, the scene small in front of it; rain starts. Thunder and wind.",
  [], STORM, {"aspect": "16:9 (Widescreen)", "enhance": False}, "A cloud giant with lightning in its chest behind the tree (tplx-storm-creature-b, 23 Oct).",
  defaults={"enhance": False})
A("cloud-surf", "Cloud Surf", "Cloud Surf", "clips", "morph", "Your photo",
  "You surfing across pink clouds at sunset, same face.",
  "The scene turns into a ride across pink clouds at sunset: the person carves over the cloud tops on the surfboard, mist spraying, a dynamic tracking "
  "shot staying close to them; wind and a cheerful whoosh.",
  [], MAN, {"aspect": "portrait", "duration": 4}, "Surfboard on pink clouds, same face (tplx-cloud-surf-m, 23 Oct).",
  klein="Put this exact person standing on a surfboard riding across fluffy pink clouds at sunset, knees bent, arms out for balance, cloud mist spraying "
        "around the board, seen from a low dynamic angle, the face large and clear. Keep the face identical.")
A("mukbang", "Mukbang", "Mukbang", "clips", "video", "Your photo",
  "You at a table full of food, eating for the camera.",
  "A mukbang video: the person sits at a table loaded with food in front of a microphone, picks up a piece and eats with relish, nodding at the camera; "
  "crunching and chewing sounds, a short delighted hum.",
  [], MAN, {"aspect": PORTRAIT}, "Food, mic, eating sounds.")
A("melting-doodle", "Melting Doodle", "Melting Doodle", "clips", "video", "Your photo",
  "Cartoon doodles appear over your photo and melt down the frame.",
  "Colorful cartoon doodles appear drawn over the scene, then begin to melt and drip down the frame like wet paint, dripping and merging; a soft squelching "
  "sound.",
  [], STREET, {"aspect": PORTRAIT}, "Doodles drawn, then dripping.")
A("rap-video", "Rap Video", "Rap God", "clips", "video", "Your photo",
  "A rap music video of you: low angle, stage lights, smoke, a beat.",
  "A rap music video: the person performs toward the camera with confident hand gestures, low-angle shot, flashing stage lights and smoke, quick push-ins; "
  "a punchy hip-hop beat.",
  [], MAN, {"aspect": PORTRAIT}, "Performance energy; a beat plays.")
A("idol", "Idol", "Idol", "clips", "video", "Your photo",
  "Your K-pop idol moment: spotlights, wind, confetti, a pose.",
  "A pop idol stage moment: the person stands center stage under spotlights, hair blown by a fan, confetti falling, strikes a pose and smiles at the camera; "
  "crowd cheering and a pop beat.",
  [], WOMAN, {"aspect": PORTRAIT}, "Stage, confetti, pose.")

# ---------------------------------------------------------------- the canvas, a new person, one effect LoRA
A("expand-image", "Expand Image", "Expand Image", "style", "edit", "Your photo",
  "Grows a photo past its edges: FLUX 3 Image Klein draws only the new border, so the original stays as it was.",
  "The outer part of this photo is blurred: redraw it sharp, continuing the scene, its objects, light and perspective naturally out to all "
  "four edges, as if the camera had pulled back. The sharp center stays exactly the same; one continuous photo, no frame, no border, no text.",
  [{"id": "direction", "type": "select", "label": "Expand", "default": "out", "options": [
      {"value": "out", "label": "Zoom out", "sets": pad(192, 192, 192, 192)},
      {"value": "wide", "label": "Wider", "sets": pad(320, 0, 320, 0)},
      {"value": "tall", "label": "Taller", "sets": pad(0, 320, 0, 320)}]}],
  LAKE, {"direction": "out"}, "Does the border continue the lake, rock and sky, with no seam or gray left?", outpaint=True)
def any_(label, pairs, default="", help_=None):
    """A builder select: "Any" (nothing written) plus label → sentence pairs."""
    return sel(label[0], label[1], [("Any", "")] + pairs, default, help_)


def many(label, pairs, default=(), help_=None, max_=3):
    """A builder group that takes several picks at once, as Higgsfield's distinctive traits and accessories do: the sentences of
    the picks, one after the other. None picked writes nothing."""
    d = sel(label[0], label[1], pairs, "", help_)
    d["default"] = list(default)
    d["multiple"] = {"max": max_, "join": " "}
    return d


KIND = sel("kind", "Character type", [
    ("Human", "an ordinary, believable person"),
    ("Bold", "a person with bold, striking, slightly exaggerated features"),
    ("Extreme", "a person with extremely exaggerated, cartoonish features and proportions, still photographed for real"),
    ("Insect", "a character whose whole head is a grasshopper's head, with large compound eyes and long antennae, on a human body: no human face"),
    ("Frog", "a character whose whole head is a green frog's head, with a wide mouth and big round eyes, on a human body: no human face"),
    ("Cat", "an anthropomorphic cat character: a furry cat head on a human body"),
    ("Dog", "an anthropomorphic dog character: a dog head with floppy ears on a human body"),
    ("Rodent", "an anthropomorphic capybara character: a capybara head on a human body"),
    ("Bird", "a character whose whole head is a puffin's head, black and white feathers and a bright orange beak, on a human body: no human face")],
    "an ordinary, believable person", "Shown with an example of each type.")
KIND["gallery"] = True
INFLUENCER = [
    KIND,
    sel("gender", "Gender", [("Woman", "A woman"), ("Man", "A man"), ("Trans man", "A trans man"), ("Trans woman", "A trans woman"),
                             ("Non-binary", "A non-binary person")], "A woman"),
    any_(("age", "Age"), [("Adult", " aged around 28"), ("Mature", " aged around 45"), ("Older", " aged around 70")], " aged around 28"),
    any_(("origin", "Origin"), [("African", " of African descent"), ("East Asian", " of East Asian descent"), ("European", " of European descent"),
                                ("South Asian", " of South Asian descent"), ("Middle Eastern", " of Middle Eastern descent"),
                                ("Latin American", " of Latin American descent"), ("Mixed", " of mixed heritage")], " of Latin American descent"),
    any_(("skin", "Skin tone"), [("Porcelain", "Porcelain skin."), ("Fair", "Fair skin."), ("Olive", "Olive skin."), ("Tan", "Tan skin."),
                                 ("Brown", "Brown skin."), ("Deep brown", "Deep brown skin."), ("Ebony", "Very dark skin.")]),
    any_(("build", "Build"), [("Slim", "Slim build."), ("Athletic", "Athletic build."), ("Muscular", "Muscular build."), ("Curvy", "Curvy build."),
                              ("Heavyset", "Heavyset build."), ("Bodybuilder", "A huge bodybuilder build.")]),
    any_(("stature", "Height"), [("Average", "Average height."), ("Tall", "Tall."), ("Very tall", "Very tall.")]),
    any_(("proportions", "Proportions"), [("Long limbs", "Long arms and legs."), ("Short legs", "Short legs."), ("Broad shoulders", "Broad shoulders."),
                                          ("Narrow waist", "A narrow waist."), ("Egg-shaped", "A round, egg-shaped body.")]),
    any_(("hair", "Hairstyle"), [
        ("Long curly", "Long curly hair."), ("Long straight", "Long straight hair."), ("Short", "Short hair."), ("Bob", "A bob haircut."),
        ("Bald", "A bald head."), ("Buzz cut", "A buzz cut."), ("Bowl cut", "A bowl cut."), ("Mullet", "A mullet."), ("Braids", "Long braids."),
        ("Pigtails", "Two pigtails."), ("Afro", "A big afro."), ("Mohawk", "A mohawk."), ("Voluminous waves", "Big voluminous waves."),
        ("Beehive", "A tall beehive hairdo."), ("Perm", "A tight perm."), ("Layered", "A layered cut."), ("Ringlets", "Long ringlets."),
        ("Mushroom cut", "A mushroom cut."), ("Hair horns", "Hair styled into two horns."), ("Soft-serve swirl", "Hair piled up in a soft-serve swirl."),
        ("Ball of curls", "A round ball of curls."), ("Two buns", "Two round buns on top of the head."), ("Hair wings", "Hair swept out to the sides like wings."),
        ("Spikes", "Spiky hair."), ("Side spiral", "One big spiral curl on the side.")], "Long curly hair."),
    any_(("haircolor", "Hair color"), [("Jet black", "Jet-black hair."), ("Dark brown", "Dark brown hair."), ("Brown", "Brown hair."),
                                       ("Auburn", "Auburn hair."), ("Red", "Bright red hair."), ("Blonde", "Blonde hair."), ("Platinum", "Platinum hair."),
                                       ("Gray", "Gray hair."), ("White", "White hair."), ("Pastel pink", "Pastel pink hair."), ("Lilac", "Lilac hair."),
                                       ("Blue", "Blue hair."), ("Green", "Green hair.")], "Dark brown hair."),
    any_(("head", "Head shape"), [("Long", "A long face."), ("Small", "A very small head."), ("High forehead", "A high forehead."),
                                  ("Heavy brow", "A heavy brow ridge."), ("Chiseled jaw", "A sharply chiseled jawline."), ("Huge jaw", "A huge jaw."),
                                  ("Round", "A round face."), ("Square", "A square face."), ("Heart", "A heart-shaped face.")]),
    any_(("neck", "Neck"), [("Thick", "A thick neck."), ("Long", "A long neck."), ("Short", "A short neck.")]),
    any_(("eyes", "Eye shape"), [("Almond", "Almond-shaped eyes."), ("Round", "Round eyes."), ("Monolid", "Monolid eyes."), ("Close-set", "Close-set eyes."),
                                 ("Wide-set", "Wide-set eyes."), ("Uneven", "Slightly uneven eyes."), ("Big", "Big eyes."), ("Huge", "Huge eyes."),
                                 ("Hooded", "Hooded eyes."), ("Upturned", "Upturned eyes."), ("Downturned", "Downturned eyes.")]),
    any_(("eyecolor", "Eye color"), [("Black", "Black eyes."), ("Brown", "Brown eyes."), ("Hazel", "Hazel eyes."), ("Green", "Green eyes."),
                                     ("Blue", "Blue eyes."), ("Ice blue", "Ice-blue eyes."), ("Amber", "Amber eyes."), ("Gray", "Gray eyes.")]),
    many(("feature", "Facial features"), [
        ("Freckles", "Freckles."), ("Dimples", "Dimples."), ("Dark circles", "Dark circles under the eyes."), ("Rosy cheeks", "Rosy cheeks."),
        ("High cheekbones", "High cheekbones."), ("Full lips", "Full lips."), ("Thick eyebrows", "Thick eyebrows."), ("Beauty mark", "A beauty mark."),
        ("Round nose", "A round nose."), ("Button nose", "A button nose."), ("Pointed nose", "A pointed nose."), ("Tiny nose", "A tiny nose."),
        ("Pouty lips", "Pouty lips."), ("Small mouth", "A small pursed mouth."), ("Wide mouth", "A wide mouth."), ("Unibrow", "A unibrow."),
        ("Thin arched brows", "Thin, high arched eyebrows."), ("Bushy brows", "Bushy eyebrows."), ("Protruding ears", "Ears that stick out."),
        ("Gap teeth", "A gap between the front teeth."), ("Buck teeth", "Slight buck teeth."), ("Pointed chin", "A pointed chin."),
        ("Receding chin", "A receding chin."), ("Big forehead", "A big forehead.")], ["Freckles."], "Up to 3."),
    any_(("facialhair", "Facial hair"), [("Clean-shaven", "Clean-shaven."), ("Stubble", "Stubble."), ("Full beard", "A full beard."),
                                         ("Goatee", "A goatee."), ("Mustache", "A mustache."), ("Pencil mustache", "A thin pencil mustache."),
                                         ("Push-broom", "A thick push-broom mustache."), ("Braided beard", "A braided beard.")]),
    many(("trait", "Distinctive traits"), [("Different eye colors", "Each eye a different color."), ("Small face tattoo", "A small face tattoo."),
                                          ("Nose piercing", "A nose piercing."), ("Ear piercings", "Several ear piercings."),
                                          ("Eyebrow slits", "Shaved slits in one eyebrow."), ("Bleached brows", "Bleached eyebrows."),
                                          ("No eyebrows", "No eyebrows."), ("Gold grill", "A gold grill on the teeth."), ("Braces", "Braces on the teeth."),
                                          ("Eyebrow scar", "A small scar through one eyebrow."), ("Face gems", "Small gems stuck on the cheekbones."),
                                          ("Elf ears", "Pointed elf ears."), ("Long lashes", "Very long eyelashes."), ("Nose strip", "A strip across the nose.")],
         help_="Up to 3."),
    any_(("style", "Style"), [("Casual", "Wearing casual everyday clothes."), ("Streetwear", "Wearing streetwear."), ("Retro", "Wearing 1970s retro clothes."),
                              ("Sporty", "Wearing sporty athletic clothes."), ("Y2K", "Wearing early-2000s Y2K fashion."),
                              ("Theatrical", "Wearing a bold theatrical costume."), ("Gothic", "Wearing gothic black clothes."),
                              ("Suit", "Wearing a tailored suit.")], "Wearing casual everyday clothes."),
    many(("accessory", "Accessories"), [("Glasses", "Glasses."), ("Headphones", "Headphones around the neck."), ("Jewelry", "Jewelry."),
                                        ("Hat", "A hat."), ("Bag", "A bag over one shoulder.")], help_="Up to 3."),
    sel("scene", "Scene", [("Studio", "Standing in a plain light-gray photo studio, full body, soft even light."),
                           ("Fitness", "Stretching on a rooftop at sunrise, full body."),
                           ("Travel", "With a backpack at a viewpoint above a coastal town."),
                           ("Fashion", "Posing on a city street, full body."),
                           ("Food", "Tasting a dish at a busy street food stall at night."),
                           ("Tech", "At a desk with a laptop and a camera on a tripod, warm desk lamp.")],
        "Standing in a plain light-gray photo studio, full body, soft even light."),
]

def from_photo(group: dict) -> dict:
    """The same group for the photo mode, starting at "Any" (or none), so the person keeps what the photo shows until a pick changes it."""
    g = json.loads(json.dumps(group))
    g["default"] = [] if g.get("multiple") else ""
    return g


BY_ID = {g["id"]: g for g in INFLUENCER}
INFLUENCER_PHOTO = [from_photo(BY_ID[i]) for i in ("hair", "haircolor", "build", "facialhair", "feature", "trait", "style", "accessory")] + [BY_ID["scene"]]

A("ai-influencer", "AI Influencer", "AI Influencer", "portraits", "klein", None,
  "Build a made-up influencer trait by trait: type, body, hair, face, style and scene (FLUX 3 Klein).",
  "A vertical photo for social media of a made-up character: {kind}. {gender}{age}{origin}. {skin} {build} {stature} {proportions} {hair} {haircolor} "
  "{head} {neck} {eyes} {eyecolor} {feature} {facialhair} {trait} {style} {accessory} {scene} Natural skin texture with visible pores, "
  "a believable photo. The clothes and shoes are plain, with no letters, prints, labels or logos anywhere.",
  INFLUENCER, None, {}, "A believable person, not a glossy render? The traits picked show?",
  defaults={"aspect": "2:3"}, sidebar=True, modes=["ai-influencer", "ai-influencer-photo"], mode_label="New character")
A("ai-influencer-photo", "AI Influencer · Your Photo", "AI Influencer (your photo)", "portraits", "edit", "Your photo",
  "Your own face as the influencer: change hair, style, extras and scene, the face stays (FLUX 3 Klein, one reference).",
  "A vertical photo for social media of the same person as in <ref_image_0>, as an influencer. {hair} {haircolor} {build} {facialhair} {feature} "
  "{trait} {style} {accessory} {scene} Everything the lines above do not change stays as in the photo: the same face (its shape, eyes, nose, "
  "mouth and marks), skin tone and age, and the same hairstyle and hair length unless a new hairstyle is given. Natural skin texture with visible "
  "pores, a believable photo. The clothes and shoes are plain, with no letters, prints, labels or logos anywhere.",
  INFLUENCER_PHOTO, WOMAN, {"haircolor": "Platinum hair.", "accessory": ["Glasses."], "scene": "Tasting a dish at a busy street food stall at night."},
  "Same face, new platinum hair and glasses at a night food stall? (Runs 21-22 on a city street in streetwear drew sneakers with brand-like marks, "
  "so the example is waist-up.)", sidebar=True,
  modes=["ai-influencer", "ai-influencer-photo"], mode_label="Your photo")
A("bullet-time-scene", "Bullet Time Scene", "Bullet Time Scene", "camera", "effect", "Your photo",
  "Freezes the moment and circles the camera around the subject, in their own scene (Wan 2.1 + Bullet Time LoRA).",
  BULLET_TRIGGER + "The video shows {subject}, frozen in mid-air while the camera circles around them in one direction; the whole scene is frozen too.",
  [txt("subject", "Who or what is in the photo", "a person mid-jump", required=True)],
  "ref-fx-jump-plain", {"subject": "a parkour athlete in a black t-shirt leaping between two rooftops"},
  "Does the camera orbit while the athlete and the city stay frozen?", effect_lora=BULLET_TIME)
A("bullet-time-white", "Bullet Time White", "Bullet Time White", "camera", "effect-klein", "Your photo",
  "Puts the subject mid-jump on a white studio backdrop, then freezes time and circles the camera around them.",
  BULLET_TRIGGER + "The video shows {subject}, frozen in mid-air on a seamless white studio background while the camera circles around them in one direction.",
  [txt("subject", "Who or what is in the photo", "a person mid-jump", required=True)],
  CHARACTER, {"subject": "a man in a red jacket, jeans and white sneakers"},
  "White backdrop, same person and outfit, smooth orbit?", effect_lora=BULLET_TIME,
  klein="Put this exact person on a seamless pure white studio background, mid-jump with arms spread, soft even studio light. "
        "Keep the face, hair and outfit identical.")
A("bullet-time-splash", "Bullet Time Splash", "Bullet Time Splash", "camera", "effect-klein", "Your photo",
  "Bursts frozen water around the subject, then circles the camera through the suspended drops.",
  BULLET_TRIGGER + "The video shows {subject}, frozen in mid-air inside a burst of suspended water droplets while the camera circles around them in one direction.",
  [txt("subject", "Who or what is in the photo", "a person", required=True)],
  "ref-fx-runner-plain", {"subject": "a sprinter in a teal singlet and black shorts"},
  "Do the drops stay frozen in the air while the camera moves?", effect_lora=BULLET_TIME,
  klein="Add a frozen splash of clear water bursting around this exact person, droplets and ribbons of water suspended in the air, "
        "same place and light. Keep the face, hair and outfit identical.")


# ---------------------------------------------------------------- camera LoRAs on Qwen-Image-Edit-2509 (the relight pipeline, other LoRA)
MOVES = [("Move forward", "将镜头向前移动 Move the camera forward."), ("Move back", "将镜头向后移动 Move the camera backward."),
         ("Move left", "将镜头向左移动 Move the camera left."), ("Move right", "将镜头向右移动 Move the camera right."),
         ("Move up", "将镜头向上移动 Move the camera up."), ("Move down", "将镜头向下移动 Move the camera down."),
         ("Rotate 45° left", "将镜头向左旋转45度 Rotate the camera 45 degrees to the left."), ("Rotate 45° right", "将镜头向右旋转45度 Rotate the camera 45 degrees to the right."),
         ("Top-down view", "将镜头转为俯视 Turn the camera to a top-down view."), ("Low angle", "将镜头转为仰视 Turn the camera to a low-angle view looking up.")]
A("angles", "Angles", "Angles 2.0", "camera", "qwen-edit", "Your photo",
  "The same scene from another camera position: move, rotate, look down (Multiple Angles LoRA on Qwen-Image-Edit).",
  "{move}",
  [sel("move", "Camera move", MOVES, default=MOVES[6][1])],
  SCENE, {}, "The cafe seen from 45° to the left; same people and table.", lora="angles")
A("shots", "Shots", "Shots", "camera", "qwen-edit", "Your photo",
  "Nine framings of one image: wide, close-up, top-down, low angle and rotations.",
  "{shot}",
  [sel("shot", "Shot", [("Wide-angle", "将镜头转为广角镜头 Turn the camera to a wide-angle lens."), ("Close-up", "将镜头转为特写镜头 Turn the camera to a close-up."),
                         ("Extreme close-up", "将镜头转为极特写镜头 Turn the camera to an extreme close-up."), ("Top-down", "将镜头转为俯视 Turn the camera to a top-down view."),
                         ("Low angle", "将镜头转为仰视 Turn the camera to a low-angle view looking up."), ("Rotate 45° left", "将镜头向左旋转45度 Rotate the camera 45 degrees to the left."),
                         ("Rotate 45° right", "将镜头向右旋转45度 Rotate the camera 45 degrees to the right."), ("Rotate 90° left", "将镜头向左旋转90度 Rotate the camera 90 degrees to the left."),
                         ("From behind", "将镜头转到人物背后 Move the camera behind the subject.")])],
  LAKE, {"shot": "将镜头转为特写镜头 Turn the camera to a close-up."}, "The hiker large in frame, seen from behind (the wide-angle showcase made him tiny).", lora="angles")
A("zooms", "Zooms", "Zooms", "camera", "qwen-edit", "Your photo",
  "Zoom levels of one image, from a wide view to an extreme close-up.",
  "{zoom}",
  [sel("zoom", "Zoom", [("Much wider", "将镜头大幅向后移动并转为广角镜头 Move the camera far back and turn it to a wide-angle lens."), ("Wider", "将镜头向后移动 Move the camera backward."),
                         ("Closer", "将镜头向前移动 Move the camera forward."), ("Close-up", "将镜头转为特写镜头 Turn the camera to a close-up."),
                         ("Extreme close-up", "将镜头转为极特写镜头 Turn the camera to an extreme close-up.")], default="将镜头转为特写镜头 Turn the camera to a close-up.")],
  STREET, {}, "A close-up of the woman in the raincoat.", lora="angles")
A("whats-next", "What's Next", "What's Next?", "camera", "qwen-edit", "Your photo",
  "The next shot of your scene: 8 cinematic continuations (next-scene LoRA on Qwen-Image-Edit).",
  "Next Scene: {next}",
  [sel("next", "Continuation", [("Pull back to reveal", "the camera pulls back to reveal the wider surroundings"), ("Push in to a close-up", "the camera pushes in to a close-up on the main subject"),
                                 ("Pan right", "the camera pans right, revealing more of the scene"), ("Someone enters", "a new character walks into the frame from the left"),
                                 ("Dusk falls", "time passes and the light turns to dusk, lights coming on"), ("Rain starts", "the weather turns and rain begins to fall"),
                                 ("Tilt up to the sky", "the camera tilts up toward the sky"), ("Reverse angle", "the camera cuts to the reverse angle, looking back the other way")])],
  LAKE, {}, "The next shot of the scene: same hiker and lake, a new angle.", lora="next-scene")


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
        used = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", t["prompt"] + " " + (t["klein"] or "")))
        have = {i["id"] for i in t["inputs"]}
        setters = {i["id"] for i in t["inputs"] if any("sets" in o for o in i.get("options", []))}   # selects that write node fields
        assert used <= have, (t["id"], used - have)
        assert have - setters <= used, (t["id"], have - setters - used)
        for i in t["inputs"]:
            assert i["id"] not in ("image", "image2", "details", "steps", "seed", "width", "height", "duration", "enhance", "aspect", "resolution"), (t["id"], i["id"])
        if t["base"] in ("z-image", "klein"):
            assert t["ref"] is None and t["image_label"] is None
        else:
            assert t["ref"], t["id"]
        assert (t["base"] == "edit2") == bool(t["image2_label"] and t["ref2"]), t["id"]
        assert (t["base"] == "qwen-edit") == (t["lora"] in QWEN_LORAS), t["id"]
        assert (t["base"] in ("morph", "effect-klein")) == bool(t["klein"]), t["id"]
        assert (t["base"] in ("effect", "effect-klein")) == bool(t["effect_lora"]), t["id"]
        assert not t["outpaint"] or t["base"] == "edit", t["id"]
        assert not t["face_mask"] or t["base"] == "edit2", t["id"]
        for k in t["defaults"]:
            assert k in BASES[t["base"]]["keep"], (t["id"], k)
        for k in t["values"]:   # lab values name the template's own inputs or the settings kept from the base app
            assert k in have or k in BASES[t["base"]]["keep"], (t["id"], k)


def manifest(t: dict) -> dict:
    base = BASES[t["base"]]
    src = json.loads((ROOT / "apps" / base["app"] / "app.json").read_text(encoding="utf-8"))
    keep = {i["id"]: i for i in src["inputs"] if i["id"] in base["keep"]}
    inputs = []
    if base["image"]:
        inputs.append({"id": "image", "type": "image", "label": t["image_label"], "required": True, "limits": {"max_mb": 20},
                       **({"help": t["help"]} if t["help"] else {}), "bind": [{"node": base["image"][0], "field": base["image"][1]}]})
    if base.get("image2"):
        inputs.append({"id": "image2", "type": "image", "label": t["image2_label"], "required": True, "limits": {"max_mb": 20},
                       "bind": [{"node": base["image2"][0], "field": base["image2"][1]}]})
    inputs += t["inputs"]
    # the default "" matters: an optional input with no value is skipped everywhere, and the template with it
    binds = [{"node": base["prompt"][0], "field": base["prompt"][1], "template": t["prompt"] + " {details}"}]
    if t["klein"] and re.search(r"\{[a-z]", t["klein"]):   # the Klein instruction takes the template's own inputs too
        binds.append({"node": base["klein"][0], "field": base["klein"][1], "template": t["klein"]})
    # sidebar: a one-line field, so a text-to-image template with many selects opens with its controls in a side column
    inputs.append({"id": "details", "type": "text" if t["sidebar"] else "textarea", "label": "Extra direction", "default": "",
                   "help": "Added at the end of the app's prompt.", "bind": binds})
    inputs += [{**keep[k], "default": t["defaults"][k]} if k in t["defaults"] else keep[k] for k in base["keep"]]
    test = {"image": "test/portrait.png"} if base["image"] else {}
    if base.get("image2"):
        test["image2"] = "test/second.png"
    if base["section"] == "video":
        test["duration"] = 2
    test.update(t["values"])
    models, credits = src["models"], list(src.get("credits", []))
    notes = f"Template app written by tools/template_apps.py: the workflow is apps/{base['app']}'s (built by tools/build_apps.py)"
    if t["base"] == "edit2":
        notes += " plus a second LoadImage on ReferenceMultiLatent's images.image1"
    if t["base"] == "klein":   # the template writes the whole prompt: no upsampler, and no input to turn it on
        models = [m for m in models if "prompt_upsampler" not in m["file"]]
        notes += " without the 9B prompt upsampler (the prompt goes straight to the text encoder)"
    if t["face_mask"]:
        notes += ("; the sampler starts from the first image (scaled to 1 MP, encoded) with a noise mask on the face oval that the native "
                  "MediaPipe nodes find, so only the face is redrawn, and the second image is Klein's only reference")
        models = models + [FACE_MODEL]
        credits = credits + ["MediaPipe Face Landmarker (Google, Apache-2.0), ComfyUI port: Comfy-Org/mediapipe"]
    if t["base"] == "morph":
        notes += f" with a fixed Klein instruction for the last frame (node edit:4: \"{t['klein']}\")"
    if t["base"] in ("effect", "effect-klein"):
        effects = {s["value"] for i in src["inputs"] if i["id"] == "effect" for o in i["options"] for s in o.get("sets", []) if s["field"] == "lora_name"}
        models = [m for m in models if m["file"].split("/")[-1] not in effects or m["file"].split("/")[-1] == t["effect_lora"]]
        notes += f" with {t['effect_lora']} as the effect LoRA (node ff_effect)"
    if t["base"] == "effect-klein":
        edit = json.loads((ROOT / "apps" / "edit" / "app.json").read_text(encoding="utf-8"))
        models = models + edit["models"]
        credits = credits + [c for c in edit.get("credits", []) if c not in credits]
        notes += (f", after FLUX 3 Klein (apps/edit, merged in as edit:*) redraws the photo with a fixed instruction (node edit:4: \"{t['klein']}\"); "
                  "Wan starts from Klein's image")
    if t["outpaint"]:
        notes += ("; the photo, scaled to 1 MP, sits on a stretched and blurred copy of itself as big as ImagePadForOutpaint's canvas (the select "
                  "sets the padding); the sampler starts from that canvas with a noise mask on the border only, and the canvas is Klein's reference")
    if t["lora"]:
        lora = QWEN_LORAS[t["lora"]]
        models = [m for m in models if "Relight" not in m["file"]] + [{"repo": lora["repo"], "file": lora["file"], "dir": "loras", "gb": lora["gb"], "phase": "denoise", "license": lora["license"]}]
        credits = [c for c in credits if "Relight" not in c]
        credits.insert(1, lora["credit"])
        notes += f" with {lora['file']} in place of the Relight LoRA and no Relight trigger"
    notes += "; the prompt below is fixed and \"Extra direction\" is appended to it."
    return {
        "$schema": "../../schema/app.schema.json",
        "id": t["id"], "name": t["name"], "section": base["section"],
        "summary": t["summary"],
        "higgsfield_feature": t["feature"],
        **({"modes": t["modes"]} if t["modes"] else {}),
        **({"mode_label": t["mode_label"]} if t["mode_label"] else {}),
        "pack": base["pack"], "status": "ready", "workflow": "workflow.api.json",
        "source": {**src.get("source", {}), "notes": notes},
        "inputs": inputs,
        "outputs": [{**base["output"], "label": "Result"}],
        "models": models,
        "credits": credits,
        "test": test,
    }


def is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def workflow(t: dict) -> dict:
    """The base app's workflow, with the few edits a base needs."""
    base = BASES[t["base"]]
    api = json.loads((ROOT / "apps" / base["app"] / "workflow.api.json").read_text(encoding="utf-8"))
    if t["base"] == "klein":   # no upsampler: the template's prompt goes straight to the text encoder
        for i, n in api.items():
            for k, v in n["inputs"].items():
                if is_link(v) and v[0] == "18:16":
                    n["inputs"][k] = ["18:17", 0]
        for i in ("18:11", "18:12", "18:14", "18:16"):
            del api[i]
    if t["base"] == "edit2":   # a second reference image into the same ReferenceMultiLatent
        api["12"] = {"class_type": "LoadImage", "inputs": {"image": "second.png"}, "_meta": {"title": "Second reference"}}
        api["17"]["inputs"]["images.image1"] = ["12", 0]
    if t["face_mask"]:   # start from the first image and let the sampler change only the face oval (as found: grown 16 px it reached
                         # the hairline and Klein drew a high bare forehead, run 20261024-032920-l40s)
        api["fm_scale"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["11", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                                                                "resolution_steps": 16}, "_meta": {"title": "First image at 1 MP"}}
        api["fm_model"] = {"class_type": "LoadMediaPipeFaceLandmarker", "inputs": {"model_name": FACE_MODEL["file"].split("/")[-1]},
                           "_meta": {"title": "MediaPipe face model"}}
        api["fm_find"] = {"class_type": "MediaPipeFaceLandmarker", "inputs": {"face_detection_model": ["fm_model", 0], "image": ["fm_scale", 0],
                                                                               "detector_variant": "both", "num_faces": 1, "min_confidence": 0.5,
                                                                               "missing_frame_fallback": "empty"}, "_meta": {"title": "Find the face"}}
        api["fm_mask"] = {"class_type": "MediaPipeFaceMask", "inputs": {"face_landmarks": ["fm_find", 0], "regions": "all"}, "_meta": {"title": "Face oval"}}
        api["fm_grow"] = {"class_type": "GrowMask", "inputs": {"mask": ["fm_mask", 0], "expand": 0, "tapered_corners": True},
                          "_meta": {"title": "Grow or shrink the oval (px)"}}
        api["fm_encode"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["fm_scale", 0], "vae": ["3", 0]}, "_meta": {"title": "Encode the first image"}}
        api["fm_latent"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["fm_encode", 0], "mask": ["fm_grow", 0]},
                            "_meta": {"title": "Only the face is redrawn"}}
        api["7"]["inputs"]["latent_image"] = ["fm_latent", 0]
        api["17"]["inputs"]["images.image0"] = ["12", 0]   # the face photo is the only reference: with both, Klein copied the first face back
        del api["17"]["inputs"]["images.image1"]
    if t["base"] in ("effect", "effect-klein"):
        api["ff_effect"]["inputs"]["lora_name"] = t["effect_lora"]
    if t["base"] == "effect-klein":   # Klein redraws the photo first; Wan's start image and CLIP vision read Klein's output
        edit = json.loads((ROOT / "apps" / "edit" / "workflow.api.json").read_text(encoding="utf-8"))
        for i, n in edit.items():
            node = json.loads(json.dumps(n))
            for k, v in node["inputs"].items():
                if is_link(v):
                    node["inputs"][k] = [f"edit:{v[0]}", v[1]]
            api[f"edit:{i}"] = node
        del api["edit:9"], api["edit:11"]   # Klein's own save, and its own LoadImage: it reads the app's photo
        for i, n in api.items():
            for k, v in n["inputs"].items():
                if is_link(v) and v[0] == "edit:11":
                    n["inputs"][k] = ["52", 0]
                elif is_link(v) and v[0] == "52" and not i.startswith("edit:"):
                    n["inputs"][k] = ["edit:8", 0]
    if t["outpaint"]:   # draw only the border. The canvas around the photo is the photo itself, stretched and blurred: on a flat
                        # gray border (ImagePadForOutpaint's own fill) Klein drew a gray frame around the photo (run 20261024-172353-h100)
        api["op_scale"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["11", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                                                                "resolution_steps": 16}, "_meta": {"title": "Photo at 1 MP"}}
        api["op_pad"] = {"class_type": "ImagePadForOutpaint", "inputs": {"image": ["op_scale", 0], "left": 192, "top": 192, "right": 192, "bottom": 192,
                                                                          "feathering": 24}, "_meta": {"title": "Border to draw (its mask)"}}
        api["op_size"] = {"class_type": "GetImageSize", "inputs": {"image": ["op_pad", 0]}, "_meta": {"title": "Canvas size"}}
        api["op_stretch"] = {"class_type": "ImageScale", "inputs": {"image": ["op_scale", 0], "upscale_method": "bilinear", "width": ["op_size", 0],
                                                                     "height": ["op_size", 1], "crop": "disabled"}, "_meta": {"title": "Photo stretched to the canvas"}}
        api["op_blur"] = {"class_type": "ImageBlur", "inputs": {"image": ["op_stretch", 0], "blur_radius": 31, "sigma": 10.0}, "_meta": {"title": "Blurred"}}
        api["op_fill"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": ["op_blur", 0], "source": ["op_scale", 0], "x": 192, "y": 192,
                                                                           "resize_source": False}, "_meta": {"title": "Photo on its blurred canvas"}}
        api["op_encode"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["op_fill", 0], "vae": ["3", 0]}, "_meta": {"title": "Encode the canvas"}}
        api["op_latent"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["op_encode", 0], "mask": ["op_pad", 1]},
                            "_meta": {"title": "Only the border is drawn"}}
        api["7"]["inputs"]["latent_image"] = ["op_latent", 0]
        api["17"]["inputs"]["images.image0"] = ["op_fill", 0]   # the reference has the canvas's shape, so Klein fills it edge to edge
    if t["base"] in ("morph", "effect-klein"):   # the image Klein draws is fixed per template (placeholders filled with the defaults)
        defaults = {i["id"]: i.get("default", "") for i in t["inputs"]}
        api[base["klein"][0]]["inputs"][base["klein"][1]] = re.sub(r"\{([a-z][a-z0-9_]*)\}", lambda m: str(defaults.get(m.group(1), "")), t["klein"])
    if t["lora"]:   # the relight pipeline with another LoRA; node 14 prepends the Relight trigger, so it is blanked
        api["10:118"]["inputs"]["lora_name"] = QWEN_LORAS[t["lora"]]["file"]
        api["14"]["inputs"]["string_a"] = ""
    for n in api.values():
        if n["class_type"] == "SaveImage" or n["class_type"] == "SaveVideo" or n["class_type"] == "CreateVideo":
            if "filename_prefix" in n["inputs"]:
                n["inputs"]["filename_prefix"] = f"freefield/{t['id']}"
    return api


def cases() -> list[str]:
    j = lambda o: json.dumps(o, ensure_ascii=False)  # noqa: E731
    lines = []
    for rid, (prompt, w, h, note) in REFS.items():
        lines.append(f'    {{"id": "{rid}", "app": "z-image", "values": {j({"prompt": prompt, "width": w, "height": h})},\n     "note": {j(note)}}},')
    lines.append("")
    for t in T:
        vals = ({"image": f"@case:{t['ref']}"} if t["ref"] else {}) | ({"image2": f"@case:{t['ref2']}"} if t["ref2"] else {}) | t["values"]
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
        ins = [x.lower() for x in (t["image_label"], t["image2_label"]) if x] + [i["label"].lower() for i in t["inputs"]]
        base = BASES[t["base"]]["app"] + (f" + {QWEN_LORAS[t['lora']]['repo'].split('/')[1]}" if t["lora"] else "")
        base = "edit + effects" if t["base"] == "effect-klein" else base
        rows.append(f"| `{t['id']}` | {t['feature']} | `{base}` | {', '.join(ins)} |")
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
        (d / "workflow.api.json").write_text(json.dumps(workflow(t), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"apps/: {len(T)} template apps written")
    print(f"lab/cases.json: {write_cases()} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())

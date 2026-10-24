# Freefield

Open-source Higgsfield on ComfyUI: every app is one folder, every model is open weights.

Freefield rebuilds Higgsfield's creative apps (image, video, VFX, audio) on top of ComfyUI and the Comfy SDK.
There is no per-app code. Each app is a folder in `apps/` with an `app.json` manifest and a ComfyUI workflow in API
format; the web UI, the runner, the model downloads, the VRAM map and the tests are all derived from those manifests.

```
browser ──▶ web/ + server/ (Node, Comfy SDK) ──▶ gateway :8000 ──▶ comfy-api-proxy :8189 ──▶ ComfyUI :8188
             menu and forms drawn                 token check,          Comfy API v2              your GPU
             from apps/*/app.json                 unloads the GPU       in front of ComfyUI       (Modal or local)
                                                  when the app changes
```

## Status

| | |
|---|---|
| Apps | 102 manifests, each with a workflow: 29 *ready* that ran on a GPU, 5 IC-LoRA apps with their own workflows (`genjutsu`, `reframe`, `sdr-hdr`, `mixed-media`, `dub`) that ran on an H100 on 22–23 Oct, `morph` (ran on an H100, 23 Oct), 66 template apps (a fixed prompt over the `edit`, `z-image`, `video` or `relight` pipeline, written by `tools/template_apps.py`; all 66 ran on H100s on 22 Oct, see GPU runs; the 15 that came out weak were redone on 23–24 Oct through the `tplx-*` experiments, four of them on a `morph` base: Klein draws the last frame and LTX-2.5 moves the photo into it); `reshoot` was a draft until 24 Oct: its web example showed the warp guide instead of the result (the lab now keeps an app's outputs in their declared order) |
| Workflows | Built from official sources by `tools/build_apps.py` (the two smoke apps are hand-written) and accepted by ComfyUI's validator: ComfyUI `e3bee7f` (0.42.0), ComfyUI-LTXVideo `44c8a36`, ComfyUI-CrossViewWarp `fbb1e93` |
| LoRA lab | 244 cases: one showcase per app (100), one per effect (24), one per look of `mixed-media` (16) and one per transformation of `morph` (15), 33 references the others start from, 12 style-drift experiments (`mmx-*`) and 36 template experiments (`tplx-*`, each with its verdict in the note); the prompt each one would queue (values, overrides and inserted LoRAs) passes the same validator |
| End to end | Web UI → server → gateway on Modal → comfy-api-proxy → ComfyUI on an H100, run from the browser on 23 Oct: `morph` (Astronaut, 160.8 s from the button to the video, 128.7 s of it on the GPU), `mixed-media` (Anime, 149 s / 129.4 s) and `dub` (a Spanish line, 72 s / 67 s; the transcript matches the prompt). Four fixes came out of it, each with a test: links the gateway rewrites are https on a public host (Modal sends no `X-Forwarded-Proto`), an mp4 is a video even when ComfyUI lists it under `images`, the app's declared output nodes come first (core `LoadVideo` reports the clip it was given), and the progress bar is computed by the server from the raw event stream (the proxy's first frames say 1.0 and the SDK drops everything after). The model-free smoke apps cover the same path in CI |
| CI | `.github/workflows/validate.yml` runs all of the above on every push, including a CPU-only ComfyUI that checks every workflow and lab case (about 3 minutes) |
| GPU runs | Showcase lab run on an L40S (`20261020-133620-l40s`): 35 of 36 cases, one example per app; `recast` failed there and passed in a re-run (`20261020-162214-l40s`). Effects on 4 H100s at once (`20261021-140940-h100`, `--shards 4`): 61 of 61 cases in about 31 minutes of GPU, 2 min 52 s per effect on average, peak 30.8 GB. Two more H100 rounds (`20261021-152107-h100`, `20261021-175735-h100`) re-ran the 5 that failed with new photos and tried 7 LoRAs by other authors: Painting, Pirate captain, Zen and Crash zoom out were taken out, Dolly zoom and Bullet time moved to ostris's and joyfox's LoRAs, and Money rain, Clones and Steam from nose and ears were added. A fourth round (`20261021-195731-h100`, 14 of 14 cases) ran the new ones as shipped; after it, Jungle, Samurai, Warrior, Jumpscare, Smoke outfit change and Gothic transformation were taken out to keep the app SFW. That left 35 effects; on 23 Oct five more (Mona Lisa, VIP, Cartoon jaw drop, Selfie with younger self, Clones) were marked mediocre in the web UI (they lose the face or look flat at 480p) and moved to the `morph` app, which keeps the face; the other costume and identity transformations (Assassin, Baby, Bride, Classy, Princess, Robot face reveal) followed the same day for the same reason: 24 effects, each with an example in the gallery. The 66 template apps ran on 22 Oct: the 40 image templates on 2 H100s (`20261022-035128-h100`, 52 of 52 cases, 17 s at most, peak 14.7 GB) and the 26 video and two-reference ones on 3 (`20261022-035829-h100`, 39 of 39, 98 s at most, peak 46.6 GB). The IC-LoRA apps: `20261022-173700-h100` reached 6 of 28 (the gated Lightricks repos needed their licenses accepted first), `20261022-181155-h100` 28 of 28 on an H100 NVL, `20261023-044125-h100` 24 of 24 after the fixes to `reframe` (a per-frame mask) and `dub` (an empty audio latent plus the speaker reference wired into the guider); `mixed-media` took three more rounds (`20261023-124332-h100`, `-131909`, `-140409`) to settle the Klein first frame, the LoRA strength 0.7 and the 16 looks, and `20261023-143551-h100` (30 of 30) ran the looks on the final clip with the first 9 transformations of `morph`; `20261023-162024-h100` (14 of 14, peak 50.2 GB) ran the other 6 and the Cakeify showcase. The weak templates took three H100 rounds of `tplx-*` experiments (`20261023-222828-h100`, `20261023-225832-h100`, `20261024-000821-h100`) and three jobs of the lab queue on an L40S (`20261024-032920-l40s`, `-033622-l40s`, `-034326-l40s`): face swap works since the last two, with MediaPipe's face oval as the mask and the other photo as Klein's only reference. VRAM figures below are weight sizes; the lab's measured peaks show up in the web UI |

## Apps

| App | Rebuilds | Model | On a 24 GB card | Status |
|---|---|---|---|---|
| `z-image` | Create Image | Z-Image Turbo (int8) | fits whole, 12.2 GB | ready |
| `styles` | Image styles | Krea 2 Turbo (int8) + Krea's nine official style LoRAs, picked from a list | fits whole, 19.4 GB | ready |
| `style-reference` | Style transfer | Krea 2 Turbo (int8) + style-reference LoRA | fits whole, 19.4 GB | ready |
| `cinema-studio` | Cinematic Cameras | Z-Image Turbo + camera/lens vocabulary | fits whole, 12.2 GB | ready |
| `edit` | Inpaint / Edit | FLUX 3 Image Klein (int8) | fits whole, 11.0 GB | ready |
| `relight` | Relight | Qwen Image Edit 2509 (fp8) + Relight and Lightning LoRAs, light presets | tight: 21.5 GB largest phase | ready |
| `upscale`, `upscale-video` | Upscale | SeedVR2 3B (int8) | fits whole, 4.0 GB | ready |
| `remove-bg` | Background removal | BiRefNet | fits whole, 0.4 GB | ready |
| `smooth` | Slow motion / smoothing | FILM frame interpolation | fits whole, 0.1 GB | ready |
| `video`, `video-t2v` | Create Video (with audio) | LTX-2.5 22B distilled (int8) | tight: 21.5 GB largest phase | ready |
| `vfx-clean-plate`, `vfx-day-to-night`, `vfx-water` | VFX | LTX-2.5 + official IC-LoRAs | tight: 21.8–22.4 GB | ready |
| `transitions` | Effects / Transitions | LTX-2.5 + transition LoRA (2.3) | tight: 21.9 GB | ready |
| `camera-moves` | Camera Controls | Wan 2.2 Fun Camera (fp8): pans, zooms and rolls on an image, with a 4-step fast preset | fits by phases, 15.3 GB | ready |
| `camera-copy` | Camera Controls | LTX-2.5 + Cameraman v2 IC-LoRA (2.3): copies the camera move of a reference clip | tight: 22.1 GB | ready |
| `genjutsu` | Genjutsu | LTX-2.5 + Ingredients IC-LoRA: one reference sheet (people, props, a place side by side) composed into a clip | tight: 22.8 GB largest phase | ready |
| `reframe` | Reframe | LTX-2.5 + In-Outpainting IC-LoRA (2.3), two stages: a new aspect ratio with the missing parts painted in | tight: 22.8 GB largest phase | ready |
| `sdr-hdr` | SDR to HDR | LTX-2.5 + SDR-to-HDR IC-LoRA and its scene embeddings (no text encoder): a 10-bit HLG master plus a tone-mapped preview | tight: 22.8 GB largest phase | ready |
| `mixed-media` | Mixed Media | FLUX 3 Klein redraws the clip's first frame in one of 16 looks, then LTX-2.5 + Union Control IC-LoRA (2.3), two stages, follows it with the clip's edges (core Canny) as structure | tight: 22.1 GB largest phase | ready |
| `morph` | Effects (transformations) | FLUX 3 Klein redraws the photo as the transformation (15: Renaissance portrait, red carpet, younger self, clones, cartoon, statue, old age, astronaut, knight, assassin, baby, bride, classy, princess, robot face reveal) and LTX-2.5 + the transition LoRA morphs the photo into it: the face stays (all 15 ran on an H100, 23 Oct) | tight: 21.9 GB largest phase | ready |
| `dub` | Lipsync Studio (dub) | LTX-2.5 + DubIt IC-LoRA (2.3): new words in the prompt, the clip as guide and its audio as the speaker reference; Lightricks' DubIt workflow exists only for 2.3, this is a port | needs Modal: 24.0 GB denoise phase (the LoRA is 2.5 GB) | ready |
| `effects` | Effects | Wan 2.1 image-to-video 14B (fp8) + 24 effect LoRAs, 20 of them by Remade-AI (Cakeify, Hydraulic press, Money rain, 360° orbit…): the physical, camera and expression effects, picked from a gallery, with a 6-step fast preset | fits by phases, 16.8 GB | ready |
| `music` | Audio | MiniMax Music 3 | fits whole, 14.3 GB | ready |
| `sfx` | Audio | Stable Audio 3 medium | fits whole, 10.4 GB | ready |
| `recast` | Character swap | SCAIL-2 (int8) + SAM 3.1 tracking: replace a person in a video, or animate a character | fits by phases, 18.6 GB | ready |
| `motion-transfer` | Character / motion swap | Wan Animate 2 (int8) | fits by phases, 16.6 GB | ready |
| `reshoot` | Camera angles | MiniMax H3 + MoGe + CrossView: a clip seen from a new angle, the holes of the reprojection filled in | needs Modal: 27.1 GB text encoder (ran on a 48 GB L40S, peak 44.2 GB) | ready |
| `product-shot` | Product placement | FLUX 3 Image Klein (int8) with product-photography scenes | fits whole, 11.0 GB | ready |
| `speak` | Speak | LTX-2.5 image-to-video voicing a quoted line (voice, lip sync and motion in one pass, no TTS) | tight: 21.5 GB largest phase | ready |
| `character` | Soul ID | FLUX 3 Image Klein, reference image (int8) | fits whole, 11.0 GB | ready |
| `talking` | Lipsync / Speak | LTX-2.5 audio-to-video (int8) | tight: 21.5 GB largest phase | ready |
| `smoke`, `smoke-invert` | — | none | — | ready |

### Template apps

Higgsfield's catalog is mostly fixed prompts over a few pipelines, and so is this: each of these apps is one of
Freefield's pipelines with its prompt baked in, selects that fill parts of it, and an "Extra direction" box appended
to it. The bases: `edit` (FLUX 3 Image Klein, one reference image), `edit` with a second reference (a garment, another
person, a face), `z-image` (text to image), `video` (LTX-2.5 image-to-video with its own audio) and `relight`'s
Qwen-Image-Edit-2509 pipeline with another LoRA (dx8152's Multiple Angles for `angles`, `shots` and `zooms`; lovis93's
next-scene v2 for `whats-next`). `tools/template_apps.py` holds the table and writes the 66 folders (manifest + the
base workflow, with the few edits a base needs) and their lab cases; `--readme` prints this list and `--lab` the
command that makes every example. Add a line to the table there, not a folder by hand.

| App | Rebuilds | Base | Inputs |
|---|---|---|---|
| `poster` | Poster | `edit` | product photo, headline |
| `packshot` | Packshot | `edit` | product photo, backdrop |
| `macro-scene` | Macroshot Scene | `edit` | product photo, setting |
| `macro-product` | Macroshot Product | `edit` | product photo |
| `giant-product` | Giant Product | `edit` | product photo, time of day |
| `billboard` | Billboard Ad | `edit` | your photo, where |
| `graffiti-ad` | Graffiti Ad | `edit` | product photo |
| `fridge-ad` | Fridge Ad | `edit` | product photo |
| `ugc-shot` | Marketing (UGC) | `edit` | product photo, where |
| `headshot` | AI Headshot Generator | `edit` | your selfie, backdrop, outfit |
| `commercial-faces` | Commercial Faces | `edit` | your photo, campaign |
| `style-snap` | Style Snap | `edit` | your photo, style |
| `skin-enhancer` | Skin Enhancer | `edit` | your photo |
| `outfit-vending` | Outfit Vending Machine | `edit` | your photo |
| `glitter-sticker` | Glitter Sticker | `edit` | your photo |
| `game-styles` | Game Dump | `edit` | your photo, game style |
| `plushie` | Plushies | `edit` | your photo |
| `render-3d` | 3D Render | `edit` | your photo |
| `figure-3d` | 3D Figure | `edit` | your photo |
| `pixel-game` | Pixel Game | `edit` | your photo |
| `brick-toy` | Brick Cube | `edit` | your photo |
| `sketch-to-real` | Sketch-to-Real | `edit` | your sketch |
| `paint-app` | Paint App | `edit` | your photo |
| `mural` | Signboard | `edit` | your photo |
| `micro-beasts` | Surrounded by Animals | `edit` | your photo, animals |
| `meme` | Meme Generator | `z-image` | scene, top text, bottom text |
| `j-magazine` | J-Magazine | `edit` | your photo |
| `cafe-60s` | 60s Cafe | `edit` | your photo |
| `victory-card` | Victory Card | `edit` | your photo |
| `j-poster` | J-Poster | `edit` | your photo |
| `mascot` | Mascot | `edit` | your photo, mascot |
| `burning-sunset` | Burning Sunset | `edit` | your photo |
| `comic-book` | Comic Book | `edit` | your photo |
| `giallo` | Giallo Horror | `edit` | your photo |
| `renaissance` | Renaissance | `edit` | your photo |
| `japanese-show` | Japanese Show | `edit` | your photo |
| `breakdown` | Breakdown | `edit` | your photo |
| `edit-text` | Edit Text | `edit` | image with text, text to replace, new text |
| `image-effects` | Image Effects | `edit` | your photo, effect |
| `color-grade` | Color Grading | `edit` | your photo, look |
| `fashion-factory` | Fashion Factory | `edit` | your photo, garment photo, scene |
| `try-on` | AI Stylist | `edit` | your photo, garment photo |
| `outfit-swap` | Outfit Swap | `edit` | your photo, photo of the outfit |
| `outfit-shot` | Outfit Shot | `edit` | model photo, garment photo, pose |
| `character-swap` | Character Swap | `edit` | scene photo, photo of the new person |
| `face-swap` | Face Swap | `edit` | photo to edit, photo of the face |
| `behind-the-scenes` | Behind the Scenes | `video` | your photo |
| `asmr-product` | ASMR Add-On | `video` | product photo |
| `asmr-whisper` | ASMR Classic | `video` | your photo |
| `asmr-host` | ASMR Host | `video` | your photo |
| `chameleon` | Chameleon | `morph` | product photo, product colors |
| `magic-button` | Magic button | `video` | product photo |
| `truck-ad` | Truck Ad | `video` | product photo |
| `kick-ad` | Kick Ad | `video` | product photo |
| `volcano-ad` | Volcano Ad | `morph` | product photo |
| `roller-coaster` | Roller Coaster | `morph` | your photo |
| `storm-creature` | Storm Creature | `video` | your photo |
| `cloud-surf` | Cloud Surf | `morph` | your photo |
| `mukbang` | Mukbang | `video` | your photo |
| `melting-doodle` | Melting Doodle | `video` | your photo |
| `rap-video` | Rap God | `video` | your photo |
| `idol` | Idol | `video` | your photo |
| `angles` | Angles 2.0 | `relight + Qwen-Edit-2509-Multiple-angles` | your photo, camera move |
| `shots` | Shots | `relight + Qwen-Edit-2509-Multiple-angles` | your photo, shot |
| `zooms` | Zooms | `relight + Qwen-Edit-2509-Multiple-angles` | your photo, zoom |
| `whats-next` | What's Next? | `relight + next-scene-qwen-image-lora-2509` | your photo, continuation |

Full table: [`docs/vram-map.md`](docs/vram-map.md) (`python tools/catalog.py vram`). Between two apps with different
base models the gateway calls ComfyUI's `POST /free`, so nothing from the previous app stays in VRAM.

## Run it

You need Node 22.6+, Python 3.10+ and a [Modal](https://modal.com) account.

```sh
# 0. what is missing: Node, Modal login and secrets, Hugging Face license access per model, .env
python tools/doctor.py

# 1. secrets (once). Pick the Modal workspace first: in .env, FREEFIELD_MODAL_PROFILE=<profile from `modal profile list`>
python tools/setup_token.py                       # gateway token: Modal secret "freefield" and .env get the same value
modal secret create huggingface HF_TOKEN=hf_...   # accept the LTX-2.5 and FLUX 3 Klein licenses on the Hub first

# 2. models into the "freefield-models" volume, per pack (see packs/index.json)
python tools/catalog.py packs
modal run infra/modal_app.py::download --pack image

# 3. backend (private: it needs the token)
modal deploy infra/modal_app.py                   # FREEFIELD_GPU=A10G to try the 24 GB plan

# 4. web app
npm install
# in .env (made by step 1): COMFY_BASE_URL = the URL printed by step 3
npm run serve                                     # http://127.0.0.1:3000
npm run app -- z-image --set prompt="a red bicycle against a white wall"   # or from the terminal
```

On Windows PowerShell, environment variables go before the command as `$env:FREEFIELD_GPU = "A10G"; modal deploy ...`.

### The web app

`npm run serve` opens a studio laid out like the one it rebuilds:

- **Explore**: featured apps as video cards, the studios, and one lab example per app.
- **Image** and **Audio**: prompt-first apps. Results fill the page and a floating bar holds the prompt, reference
  images (click **+**, drop or paste them), one chip per setting, the number of generations and **Generate**, which shows
  how long the lab example took on the GPU.
- **Video** (and the upload-first tools): controls in a left column (*Create video*, *Edit video*, *Motion control*),
  results on the right.
- Every app has **History** (what you generated with it), **Library** (the lab example, *Load this example*) and
  **How it works** (models and licenses, VRAM by phase, the download and terminal commands).
- A thumbs-down on any lab example (Explore, Library, the viewer, the effects picker) marks it *mediocre*. The marks
  live in `lab/flags.json` (key `<app>` or `<app>/<input>/<option>`), **Library → Lab examples → Mediocre** lists them,
  and `lab/publish.py` clears a mark when a new run replaces that example. It is how a reviewer tells the lab which
  results need a better model, LoRA or prompt.
- **Apps** lists every app by category; **Library** shows everything you generated; **VRAM map** draws each app's
  weights, largest phase and measured peak against 24 and 48 GB.
- **Compare** (on any result) puts it next to another file side by side, or as a wipe for two images; videos play in
  sync. Drop the result of the same prompt from Higgsfield, or anything else; dropped files never leave the browser.
- The **GPU** pill says whether the backend is warm (asking never wakes it) and wakes it on request, so a cold start
  happens while you prepare the inputs. When warm it shows the VRAM in use and which app is loaded.
- English or Spanish (the globe button); it follows the browser until you pick one.

Runs are recorded before they are submitted and kept in `out/history/<id>/` (inputs, outputs and a `meta.json` with
the values, the seed that was used, and timings), so they survive a closed tab, the backend's retention and a server
restart; runs still going when the server stops are picked up again. *Recreate* puts any result's inputs and settings
back in the form.

Any ComfyUI works as the backend: run `comfy-api-proxy` next to it and `python infra/gateway.py` in front, and point
`COMFY_BASE_URL` at the gateway. Pointing it straight at a `comfy-api-proxy` (or another Comfy API v2 endpoint) works
too; only the unload-between-apps step is skipped. Draft apps stay locked in the UI and the CLI until you set
`FREEFIELD_DRAFTS=1` (or pass `--draft` to `npm run app`).

## The LoRA lab and the gallery

`lab/cases.json` lists experiments: reference images, clips and a song are generated first, then every app and LoRA
runs on them with a fixed seed. Each app has a *showcase* case, so one command makes an example of every app:

```sh
modal run --detach lab/lab_modal.py --showcase    # one example per app + the references they need (36 cases)
modal run lab/lab_modal.py --pull <run_id>        # only if the terminal closed before the end: copy back and publish
```

The effects app has one case per effect (`fx-*`, 24 of them, on synthetic people, objects and scenes made
by `z-image` in the same run). Its effect picker is a *gallery* input, so `lab/publish.py` also keeps one example per
effect (`web/examples/effects/options/`): the picker shows them as cards and *Explore* gets a wall of effects. A run
of a few effects adds to that gallery without replacing the rest.

```sh
modal run --detach lab/lab_modal.py --apps effects --shards 4   # 24 effects + their 19 reference stills, on 4 GPUs at once
modal run lab/lab_modal.py --only fx-cakeify,fx-squish          # re-run a few after changing their prompt
modal run lab/lab_modal.py --only tplx-*                        # a pattern works too (fnmatch)
```

`--shards N` works with any selection: it splits the cases over N GPU containers that run at the same time, keeping
the cases that read the same reference together so each reference is made once (the 24 effects become 4 groups of
6). The GPU time stays about the same, plus loading the models once per container; the wait drops to about 1/N.
The groups write to `<run_id>-s1`, `-s2`… on the volume and come back merged into one `lab/results/<run_id>`, with one
`review.html`; `--pull <run_id>` merges them the same way.

Runs can also come from a queue, so that someone working on the repo (an assistant included) can ask for a run
without waiting for you to type it. You start the watcher once, in a terminal where `modal` is logged in:

```sh
python tools/lab_queue.py            # watches lab/queue/; Ctrl+C stops it, a file lab/queue/STOP pauses it
```

A job is a file `lab/queue/<name>.job.json` such as `{"only": "tpl-face-swap,tplx-face-swap-*", "note": "why"}`. The
watcher runs exactly `modal run lab/lab_modal.py --only <only>` (plus `--shards N` if the job asks, up to 4), one job
at a time, saves the output to `<name>.log` and writes `<name>.done.json` with the exit code, the run id and the
"N/M ok" line. It accepts nothing else: no deploy, no other command, only case ids and patterns that exist in
`lab/cases.json`, at most 60 cases per job and 12 jobs a day (`--max-cases`, `--max-jobs`); a job outside that gets a
`<name>.refused.json` with the reason. Your Modal login never leaves your machine.

`--detach` keeps the GPU job running if the terminal closes; the run id is printed at the start. Missing models are
downloaded first on a CPU container, so no GPU is billed while they arrive (the whole catalog is
close to 300 GB). Then one GPU container runs the cases, recording time and peak VRAM, and keeps going when one fails;
a case whose model could not be downloaded (say, a license not yet accepted) is skipped with the reason. Every output
also gets small web versions (a card, a poster for videos, a web-sized copy). At the end the run is copied to
`lab/results/<run_id>`, `review.html` is built there for rating, and `lab/publish.py` copies one example per app into
`web/examples/` (its output plus the reference files it was given): the web UI uses it as the app's card and video
loop, in *Explore*, in each app's *Library* tab, and for *Load this example*, which puts the same inputs and settings in
the form so you can run it again and compare.

```sh
modal run lab/lab_modal.py                        # every case (LoRA comparisons included) on an L40S
modal run lab/lab_modal.py --apps camera-moves,relight   # only these apps (their reference cases come along)
FREEFIELD_GPU=A10G modal run lab/lab_modal.py --only ic-clean-plate    # 24 GB parity check
python lab/publish.py lab/results/<run_id>        # republish examples from a run you already have
python lab/review.py lab/results/<run_id> --apply-peaks   # measured VRAM into each app.json
python tools/comfy_validate.py --comfy-dir /path/to/ComfyUI --placeholders --lab lab/cases.json   # free, CPU: every case's prompt is valid
```

## Add an app

1. Get the workflow in API format: add a recipe to `tools/build_apps.py` (official template + explicit edits), or
   export it from ComfyUI with *Export (API)*. A fixed prompt over a pipeline that already runs is one line in
   `tools/template_apps.py` instead (see *Template apps* above).
2. Write `apps/<id>/app.json`: inputs and where each one binds (`node` + `field`), outputs, and every model with its
   Hugging Face repo, size and phase. The schema is `schema/app.schema.json`. A `select` option can carry `sets`
   (extra node fields written when it is chosen, like the LoRA file that goes with a style); a string in `sets` may
   use `{input_id}` placeholders like a bind template (each effect writes its LoRA's prompt, with its trigger words, around
   your `{subject}`). `presets` change several fields at once (the 4-step mode of `camera-moves`), and a select marked
   `"gallery": true` is shown as cards with one lab example per option.
3. Check it:
   ```sh
   npm run validate                                # schema, bindings, declared models vs. loaders
   bash tools/ci_comfyui.sh /tmp/comfyui           # once: CPU ComfyUI at the pinned commit + pinned custom nodes
   python tools/comfy_validate.py --comfy-dir /tmp/comfyui --placeholders
   python tools/catalog.py all                     # packs and VRAM map
   npm test
   ```

`tools/comfy_validate.py` creates empty model files and tiny inputs so ComfyUI's own validator can check a workflow on
any machine, CPU included. `tools/ui2api.py` converts UI workflows (with subgraphs and dynamic widgets) to API format
using the node definitions in `tools/object_info.json`.

## Credits and licenses

Code: MIT. Model weights are not in this repository and keep their own licenses, listed in each `app.json`
(Apache-2.0, MIT, LTX-2.x Community License, FLUX Kommunity License, Krea 2 Community License, SAM License, Stable
Audio Community License, MiniMax H3 Community License). Some community LoRAs are research-only or non-commercial (Cameraman v2 in `camera-copy`); their
`app.json` says so and the web UI shows it next to the model. Workflows are adapted from ComfyUI's official templates and Lightricks' ComfyUI-LTXVideo examples;
the cloud text-encoder branch in Lightricks' examples is removed so every app runs on open weights only. Camera and
lens vocabulary in `cinema-studio` comes from [open-higgsfield-ai](https://github.com/sunnychase/open-higgsfield-ai) (MIT).
20 of the 24 effect LoRAs in `effects` are [Remade-AI](https://huggingface.co/Remade-AI)'s; the other 4 are by
[joyfox](https://huggingface.co/joyfox) (Bullet time, Money rain; its repos moved there from valiantcat and laozou),
[ostris](https://huggingface.co/ostris) (Dolly zoom) and
[lvfengchun](https://huggingface.co/lvfengchun) (Steam from nose and ears), all Apache-2.0. Each effect's prompt follows the
example on its model card and keeps its trigger words. Nine of Remade-AI's image-to-video LoRAs are left out: the ones that undress someone, fire a gun, make two
people kiss, or put a franchise character or a religious figure on screen. Four more came out wrong in three lab rounds (Painting,
Pirate captain, Zen, Crash zoom out) and four were taken out to keep the app SFW (Jungle, Samurai, Warrior, Jumpscare); Remade-AI's
Dolly effect and Bullet time were replaced. joyfox's smoke outfit change and gothic transformation LoRAs worked in the lab but were
left out for the same reason: the first dresses people in the outfits of its examples (a bunny suit with a corset, a tight dress,
a school uniform), the second puts gloved hands from someone unseen on the person's shoulders.

Use footage and characters you own or have permission for; the apps are meant for SFW work.

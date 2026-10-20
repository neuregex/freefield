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
| Apps | 29 manifests, each with a workflow: 21 *ready* (an official template with only the edits listed in its recipe) and 8 *drafts* (models or LoRAs combined in ways a GPU run still has to confirm) |
| Workflows | Built from official sources by `tools/build_apps.py` (the two smoke apps are hand-written) and accepted by ComfyUI's validator: ComfyUI `e3bee7f` (0.42.0), ComfyUI-LTXVideo `44c8a36`, ComfyUI-CrossViewWarp `fbb1e93` |
| LoRA lab | 47 cases, one showcase per app; the prompt each one would queue (values, overrides and inserted LoRAs) passes the same validator |
| End to end | Web UI → server → gateway → comfy-api-proxy → ComfyUI tested with the model-free smoke apps; lab chaining tested the same way |
| CI | `.github/workflows/validate.yml` runs all of the above on every push, including a CPU-only ComfyUI that checks every workflow and lab case (about 3 minutes) |
| GPU runs | Not yet. VRAM figures below are weight sizes, not measurements |

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
| `vfx-clean-plate`, `vfx-day-to-night`, `vfx-water` | VFX | LTX-2.5 + official IC-LoRAs | tight: 21.8–22.4 GB | draft |
| `transitions` | Effects / Transitions | LTX-2.5 + transition LoRA (2.3) | tight: 21.9 GB | draft |
| `camera-moves` | Camera Controls | Wan 2.2 Fun Camera (fp8): pans, zooms and rolls on an image, with a 4-step fast preset | fits by phases, 15.3 GB | ready |
| `camera-copy` | Camera Controls | LTX-2.5 + Cameraman v2 IC-LoRA (2.3): copies the camera move of a reference clip | tight: 22.1 GB | draft |
| `music` | Audio | MiniMax Music 3 | fits whole, 14.3 GB | ready |
| `sfx` | Audio | Stable Audio 3 medium | fits whole, 10.4 GB | ready |
| `recast` | Character swap | SCAIL-2 (int8) + SAM 3.1 tracking: replace a person in a video, or animate a character | fits by phases, 18.6 GB | ready |
| `motion-transfer` | Character / motion swap | Wan Animate 2 (int8) | fits by phases, 16.6 GB | draft |
| `reshoot` | Camera angles | MiniMax H3 + MoGe + CrossView | needs Modal: 27.1 GB text encoder | draft |
| `product-shot` | Product placement | FLUX 3 Image Klein (int8) with product-photography scenes | fits whole, 11.0 GB | ready |
| `speak` | Speak | LTX-2.5 image-to-video voicing a quoted line (voice, lip sync and motion in one pass, no TTS) | tight: 21.5 GB largest phase | ready |
| `character` | Soul ID | FLUX 3 Image Klein, reference image (int8) | fits whole, 11.0 GB | ready |
| `talking` | Lipsync / Speak | LTX-2.5 audio-to-video (int8) | tight: 21.5 GB largest phase | draft |
| `smoke`, `smoke-invert` | — | none | — | ready |

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

`--detach` keeps the GPU job running if the terminal closes; the run id is printed at the start. Missing models are
downloaded first on a CPU container, so no GPU is billed while they arrive (the whole catalog is
close to 300 GB). Then one GPU container runs the cases, recording time and peak VRAM, and keeps going when one fails;
a case whose model could not be downloaded (say, a license not yet accepted) is skipped with the reason. Every output
also gets small web versions (a card, a poster for videos, a web-sized copy). At the end the run is copied to
`lab/results/<run_id>`, `review.html` is built there for rating, and `lab/publish.py` copies one example per app into
`web/examples/`: the web UI shows it as the app's thumbnail, as an *Example* block (inputs → output, with the settings
and a *Use these settings* button) and in the **gallery** tab.

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
   export it from ComfyUI with *Export (API)*.
2. Write `apps/<id>/app.json`: inputs and where each one binds (`node` + `field`), outputs, and every model with its
   Hugging Face repo, size and phase. The schema is `schema/app.schema.json`. A `select` option can carry `sets`
   (extra node fields written when it is chosen, like the LoRA file that goes with a style), and `presets` change
   several fields at once (the 4-step mode of `camera-moves`).
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

Use footage and characters you own or have permission for; the apps are meant for SFW work.

# Freefield on a rented GPU: RunPod, Vast.ai, or any Docker host

One Docker image runs everything: ComfyUI at the pinned commit with the pinned custom nodes, `comfy-api-proxy`, the
token gateway and the web studio. You rent a GPU by the hour, start the image, and open a link. Nothing to install on
your computer, and no Modal account.

```
ghcr.io/neuregex/freefield:latest
```

When the container starts it downloads the model files of the packs you ask for into its volume (a restart downloads
only what is missing), starts the backend and the studio, and prints the link to open, with a passcode in it:

```
========================================================================
Freefield is ready on RunPod.
  Open:      https://abc123xyz-3000.proxy.runpod.net/?key=Zq0v…
  Passcode:  Zq0v…   (kept in /workspace/freefield/passcode; FREEFIELD_PASSCODE sets your own)
  …
========================================================================
```

The passcode keeps strangers out: the pod's address is public. Anyone you give the link to can use your GPU, and
everyone with the passcode sees the same history.

## Which GPU, which packs

Apps are grouped in packs by the models they share ([`packs/index.json`](../packs/index.json)). The image downloads
only the packs in `FREEFIELD_PACKS`. The default is `image-flux3,upscale`: 64 apps for 22.9 GB.

| Pack | Apps | Download | Gated (needs `HF_TOKEN`) |
|---|---|---|---|
| `image-flux3` | 58: Create Image, Cinema Studio, AI Influencer, Face Swap, Inpaint, Product Shot, and the image templates | 17.8 GB | yes |
| `upscale` | 6: upscale (image and video), remove background, depth map, smooth | 5.1 GB | — |
| `image` | Z-Image Turbo (fast drafts) | 12.2 GB | — |
| `image-qwen-edit` | angles, relight, shots, what's next, zooms | 31.7 GB | — |
| `image-krea2` | style reference, styles | 23.7 GB | — |
| `video-ltx25` | 32: image and text to video, Mixed Media, Dub, IC-LoRA apps, video templates | 66.0 GB | yes |
| `video-wan-effects` | Effects and Bullet Time | 45.1 GB | yes |
| `video-wan-camera` | camera moves | 40.0 GB | — |
| `video-scail` | Recast (character swap) | 28.6 GB | — |
| `video-wan` | motion transfer | 24.9 GB | — |
| `video-h3` | MiniMax H3: video with audio, extend video, re-shoot | 75.7 GB | — |
| `audio` | music, sound effects | 29.3 GB | — |

`FREEFIELD_PACKS=all` downloads every pack (about 410 GB); `none` downloads nothing (the two smoke apps still run).

- **24 GB** (RTX 3090, 4090, A5000, L4): every app except six that need more memory (`cinema-video`, `h3-video`,
  `h3-photo`, `extend-video`, `dub`, `reshoot`). The *On a 24 GB card* column of [the app table](../README.md#apps)
  and the [VRAM map](vram-map.md) give each app's measured peak.
- **48 GB** (L40S, RTX A6000, RTX 6000 Ada): everything. The lab made every example on an L40S or an H100.
- **NVIDIA driver 580 or newer** (CUDA 13), because the image has the same PyTorch build as the Modal backend. RunPod
  and Vast both let you filter machines by CUDA version: pick 13.0 or higher.

Gated models: accept the licenses with your Hugging Face account first, then give the pod a read token as `HF_TOKEN`:
[FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) (`image-flux3`,
`video-wan-effects`, `video-ltx25`) and [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) with its IC-LoRAs
(`video-ltx25`). The log lists the license page of each gated file it could not get.

## RunPod

1. **Your Hugging Face token as a secret** (once): Settings → Secrets → create `hf_token` with your read token.
2. **Template** (once): Templates → New Template.
   - Container image: `ghcr.io/neuregex/freefield:latest`
   - Container disk: 30 GB. Volume disk: the packs you want plus 10 GB (60 GB for the default), mounted at
     `/workspace`
   - Expose HTTP ports: `3000,8000`
   - Environment variables: `HF_TOKEN` = `{{ RUNPOD_SECRET_hf_token }}`, and `FREEFIELD_PACKS` if you want other packs
3. **Deploy**: Pods → Deploy, choose a GPU (24 or 48 GB, CUDA 13), pick the template, deploy.
4. **Open it**: the pod's Logs show the link when everything is up (the first start takes the download time: a few
   minutes for the default packs). Or Connect → HTTP Service on port 3000, and add `/?key=<passcode>` to the address.
5. **Stop it** when you are done. A stopped pod keeps its volume (models and history) and bills only the storage;
   Terminate deletes the volume too.

## Vast.ai

1. **Your Hugging Face token** (once): Account → Environment Variables → `HF_TOKEN`. Put it there, not in a template:
   variables in a public template are visible to everyone.
2. **Template** (once): Templates → New.
   - Image: `ghcr.io/neuregex/freefield`, tag `latest`
   - Launch mode: **Docker ENTRYPOINT** (the image starts itself; the SSH and Jupyter modes replace its command)
   - Docker options: `-p 3000:3000 -p 8000:8000 -e OPEN_BUTTON_PORT=3000 -e FREEFIELD_TUNNEL=1`, plus
     `-e FREEFIELD_PACKS=…` for other packs
   - Disk space: the packs you want plus 10 GB (60 GB for the default)
3. **Rent**: in Search, filter by GPU memory (24 or 48 GB) and CUDA 13.0 or higher, then rent with the template.
4. **Open it**: the instance log shows the link. With `FREEFIELD_TUNNEL=1` it is an https address on
   `trycloudflare.com` (a free Cloudflare quick tunnel; it changes on every start). Without it, Vast gives a plain
   `http://IP:port` address, which also works.
5. **Stop it** when you are done: a stopped instance keeps its disk and bills only the storage.

## Any Docker host with an NVIDIA GPU

Your own Linux machine or Windows with Docker Desktop (WSL 2), with the NVIDIA Container Toolkit:

```sh
docker run --gpus all -p 3000:3000 -v freefield:/workspace \
  -e HF_TOKEN=hf_... -e FREEFIELD_PACKS=image-flux3,upscale \
  ghcr.io/neuregex/freefield:latest
```

The volume `freefield` keeps the models and the history between runs. Open the link from the log
(`http://127.0.0.1:3000/?key=…`).

## Settings

| Variable | Default | |
|---|---|---|
| `FREEFIELD_PACKS` | `image-flux3,upscale` | packs to download, comma-separated, or `all` or `none` |
| `HF_TOKEN` | — | Hugging Face read token, for the gated packs |
| `FREEFIELD_PASSCODE` | random, kept in the volume | the studio's passcode |
| `FREEFIELD_TOKEN` | random, kept in the volume | the gateway's token on port 8000 (see below) |
| `FREEFIELD_COMFY_ARGS` | — | extra ComfyUI flags, e.g. `--lowvram` |
| `FREEFIELD_TUNNEL` | off | `1`: also open a Cloudflare quick tunnel (https) to the studio |
| `FREEFIELD_DATA` | `/workspace/freefield` | models, history and the two keys |

## Your own studio, the pod's GPU

Port 8000 is the backend alone, behind its token: a studio running on your computer (`npm run serve`) can use the
pod's GPU instead. The log prints both values for your `.env`:

```
COMFY_BASE_URL=https://abc123xyz-8000.proxy.runpod.net
FREEFIELD_TOKEN=…
```

RunPod's proxy closes any request that takes longer than 100 seconds, so a large upload over a slow connection can
fail there. The studio inside the pod does not have that problem: its uploads go from your browser to the pod once.

## When something goes wrong

- **The pod restarts in a loop, or ComfyUI says the CUDA driver is too old**: the machine has a driver older than
  580. Pick one with CUDA 13.0 or higher.
- **An app fails with a missing model file**: its pack is not in `FREEFIELD_PACKS`, or a gated download failed
  (401/403 in the log): accept the license, check `HF_TOKEN`, restart the pod. It downloads only what is missing.
- **"not enough disk"** in the log: make the volume bigger, or ask for fewer packs.
- **Forgot the passcode**: it is in the log of every start, and in `/workspace/freefield/passcode`.

## How it is built and checked

The [`Dockerfile`](../Dockerfile) installs ComfyUI with the same code as `tools/local_backend.py setup`, and
[`infra/pod.py`](../infra/pod.py) starts it with `tools/local_backend.py serve --studio`. On every change that reaches
the image, CI builds a CPU version and runs [`tools/pod_smoke.sh`](../tools/pod_smoke.sh): the passcode door, the
gateway's token, and the model-free smoke app through studio → gateway → ComfyUI. Then it publishes the GPU image
([`.github/workflows/image.yml`](../.github/workflows/image.yml)).

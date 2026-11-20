# Freefield on a rented GPU: RunPod, Vast.ai, or any Docker host

One Docker image runs everything: ComfyUI at the pinned commit with the pinned custom nodes, `comfy-api-proxy`, the
token gateway and the web studio. You rent a GPU by the hour, start the image, and open a link. Nothing to install on
your computer, and no Modal account.

```
ghcr.io/neuregex/freefield:latest
```

When the container starts it begins downloading the model files of the packs you ask for into its volume (a restart
downloads only what is missing), starts the backend and the studio meanwhile, and prints the link to open, with a
passcode in it. The studio shows how the download goes, and each app works as soon as its files are in:

```
========================================================================
Freefield is ready on RunPod.
  Open:      https://abc123xyz-3000.proxy.runpod.net/?key=Zq0v…
  Passcode:  Zq0v…   (kept in /workspace/freefield/passcode; FREEFIELD_PASSCODE sets your own)
  The models are still downloading (22.9 GB): the studio shows how it goes, and each app
  works as soon as its files are in.
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
- **Turing or newer** (RTX 20 series and up, A-series, L-series, H-series). CUDA 13 dropped Volta and older, so a
  V100 or a P100 fails with "no kernel image is available", however cheap the offer. The Vast.ai template leaves them
  out of Search (`compute_cap>=750`); on RunPod, do not pick one.

Gated models: accept the licenses with your Hugging Face account first, then give the pod a read token as `HF_TOKEN`:
[FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) (`image-flux3`,
`video-wan-effects`, `video-ltx25`) and [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) with its IC-LoRAs
(`video-ltx25`). Without a token those files wait, and the rest downloads. The studio's **Models** panel (the notice
under the top bar, or the GPU button) lists the licenses still to accept, takes a read token and downloads what was
waiting, with no restart. It keeps the token in the volume (`/workspace/freefield/hf_token`, mode 600) and uses it
instead of `HF_TOKEN` from then on; *Forget* removes it. The same panel downloads the packs you did not ask for at
the start, when the disk has room. The log lists the license page of each gated file it could not get, too.

## RunPod

[Sign up](https://runpod.io?ref=4nye3bcy) (a referral link: it costs you nothing and helps Freefield).

1. **Your Hugging Face token as a secret** (once, only for the gated packs): Settings → Secrets → create `hf_token`
   with your read token.
2. **Template**: the public one is ready, [Freefield on RunPod](https://console.runpod.io/deploy?template=p7g587ry3j&ref=4nye3bcy)
   (it opens the deploy page with it; go to step 3). To make your own instead: Templates → New Template.
   - Container image: `ghcr.io/neuregex/freefield:latest`
   - Container disk: 30 GB. Volume disk: the packs you want plus 10 GB (60 GB for the default), mounted at
     `/workspace`
   - Expose HTTP ports: `3000,8000`
   - Environment variables: `HF_TOKEN` = `{{ RUNPOD_SECRET_hf_token }}`, and `FREEFIELD_PACKS` if you want other packs
   - GPU compatibility: allowed CUDA versions 13.0 and up, minimum 24 GB of VRAM, minimum 32 GB of RAM
3. **Deploy**: Pods → Deploy, pick the template and a GPU. Under Storage, **Add volume → Volume disk**, 60 GB at
   `/workspace`: the deploy page does not add the template's volume by itself, and without it the models go to the
   container disk. If RunPod answers "There are no longer any instances available with the requested
   specifications", that GPU ran out between the list and the click: pick another.
4. **Open it**: the pod's Logs show the link when everything is up. The first start takes about 5 minutes: about 4 to
   pull the image, then the models (the default packs, 22.9 GB, come down at about 400 MB/s). Or Connect → HTTP
   Service on port 3000, and add `/?key=<passcode>` to the address.
5. **When you are done, Terminate the pod**: that deletes it and its volume, and the bill stops. Next time, deploy
   again: the models come back in about a minute. Stop keeps the volume, but on that one machine, and RunPod may
   have rented its GPU to someone else when you come back ("not enough free GPUs on the host machine"): the pod
   cannot start until it is free again.

To keep the models and the history between pods, use a **Network volume** instead of the volume disk (Storage →
Create volume, about USD 0.07 per GB a month): it lives in one data center and any new pod there can mount it. Pick a
data center that has the GPU you want.

Measured on an L40S (16 Nov 2026): Z-Image 11 s for the first image, model load included; upscale ×2 to 2048×2048
in 10 s.

## Vast.ai

[Sign up](https://cloud.vast.ai/?ref_id=865481) (a referral link: it costs you nothing and helps Freefield).

1. **Your Hugging Face token** (once, only for the gated packs): Account → Environment Variables → `HF_TOKEN`. Put it
   there, not in a template: variables in a public template are visible to everyone.
2. **Template**: the public one is ready, [Freefield on Vast.ai](https://cloud.vast.ai/?ref_id=865481&creator_id=865481&name=Freefield)
   (it opens Search with it selected and the filters below already set; go to step 3). To make your own instead: Templates → New.
   - Image Path:Tag: `ghcr.io/neuregex/freefield:latest` (write the tag in the path: the Version Tag list only knows
     Docker Hub images)
   - Docker Options: `-p 3000:3000 -p 8000:8000 -e OPEN_BUTTON_PORT=3000 -e FREEFIELD_TUNNEL=1`, plus
     `-e FREEFIELD_PACKS=…` for other packs. Vast copies them into the Ports and Environment Variables lists.
   - Launch Mode: **Docker ENTRYPOINT** (the image starts itself; the Jupyter and SSH modes replace its command), and
     untick "Jupyter direct HTTPS", which is on by default and only matters for Jupyter
   - Disk Space: the packs you want plus 10 GB (60 GB for the default)
3. **Rent**: select the template, then in Search set **Min Cuda Version 13** and the GPU memory you need (24 or 48
   GB). Each offer shows its Max CUDA, price and internet speed: the speed decides how long the first start takes.
4. **Open it**: the instance's **View instance logs** (Refresh until it fills) shows the link. With
   `FREEFIELD_TUNNEL=1` it is an https address on `trycloudflare.com` (a free Cloudflare quick tunnel; it changes on
   every start). The plain `http://IP:port` address Vast gives for port 3000 (the IP button lists the ports) works
   too, with the same `?key=`.
5. **Destroy it when you are done**: Stop keeps the disk and bills only the storage, but the GPU may be rented to
   someone else by the time you come back, as on RunPod.

Measured on an RTX 3090 at USD 0.20/hour with 690 Mbps (Czechia, 17 Nov 2026): about 4.5 minutes to pull the image
and about 3.5 more for the default models, Z-Image 15.6 s for the first image, upscale ×2 9.3 s. Vast also bills
the host's traffic ("plus bandwidth"): for that short test it cost more than the GPU (USD 0.38 in all), so for a
quick session prefer an offer with a low download price.

## Any Docker host with an NVIDIA GPU

On Windows, [`start.ps1`](../start.ps1) does all of this in one line of PowerShell: it checks the GPU, the driver and
Docker Desktop and opens the studio while the models download; the studio asks for the Hugging Face token when a model
needs one, as on a rented GPU
([README](../README.md#on-your-own-pc-in-one-line)). By hand, on your own Linux machine or Windows with Docker Desktop
(WSL 2), with the NVIDIA Container Toolkit:

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
| `HF_TOKEN` | — | Hugging Face read token, for the gated packs (or paste it in the studio's Models panel) |
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

- **A red notice about the GPU or its driver**, in the studio and the log: the card is older than CUDA 13 supports
  (a V100, a P100), or the machine's driver is older than 580, and ComfyUI would crawl on the CPU. Stop the pod and
  pick another machine (on RunPod, filter by CUDA 13.0 or higher).
- **An app says "Needs a license"**: one of its models asks you to accept its license on Hugging Face. Open the
  Models panel: it links each license, takes the token and downloads the rest.
- **An app says "Not on this GPU"**: its pack is not in `FREEFIELD_PACKS`. Download it from the Models panel, or add it
  to `FREEFIELD_PACKS` and restart the pod (it downloads only what is missing).
- **An app says "Download failed"**: the Models panel shows the error and tries again.
- **"not enough disk"** in the log: make the volume bigger, or ask for fewer packs.
- **Forgot the passcode**: it is in the log of every start, and in `/workspace/freefield/passcode`.

## How it is built and checked

The [`Dockerfile`](../Dockerfile) installs ComfyUI with the same code as `tools/local_backend.py setup`, and
[`infra/pod.py`](../infra/pod.py) starts it with `tools/local_backend.py serve --studio`. On every change that reaches
the image, CI builds a CPU version and runs [`tools/pod_smoke.sh`](../tools/pod_smoke.sh): the passcode door, the
gateway's token, and the model-free smoke app through studio → gateway → ComfyUI. Then it publishes the GPU image
([`.github/workflows/image.yml`](../.github/workflows/image.yml)).

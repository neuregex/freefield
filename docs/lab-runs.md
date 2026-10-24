# Lab runs

Every GPU run of the lab (`lab/lab_modal.py`) from 20 to 24 Oct 2026, in order. Each run is a folder
`lab/results/<run id>` with `results.jsonl` (one row per case: status, seconds, peak VRAM), `run.json` (GPU, start
time) and `review.html`. Peaks are the highest of the run; on an 80 GB H100 ComfyUI can keep the models of earlier
steps loaded, so a peak there is not the least an app needs. 24 runs, 504 of 527 cases ok: 22 of the 23 failures are
the first IC-LoRA run, before the gated licenses were accepted, and the other is `recast` in the first run.

| Run | GPU | What ran | Cases ok | Longest case | Peak |
|---|---|---|---:|---:|---:|
| `20261020-133620-l40s` | L40S | Showcase: one example for each of the first 27 apps | 35 / 36 | 358 s | 44.4 GB |
| `20261020-162214-l40s` | L40S | `recast` again (a `ComfyMathExpression` had no input) | 3 / 3 | 144 s | 41.5 GB |
| `20261021-140940-h100` | 4 × H100 (`--shards 4`) | `effects`, first round: one case per effect | 61 / 61 | 206 s | 30.8 GB |
| `20261021-152107-h100` | H100 | The 5 effects that failed, on new photos | 10 / 10 | 190 s | 30.8 GB |
| `20261021-175735-h100` | 3 × H100 | 7 effect LoRAs by other authors (`fxtry-*`) | 17 / 17 | 193 s | 41.9 GB |
| `20261021-195731-h100` | 4 × H100 | The new effects as shipped | 14 / 14 | 246 s | 30.8 GB |
| `20261022-032040-h100` | H100 | The 40 image templates, first pass | 52 / 52 | 28 s | 14.5 GB |
| `20261022-035128-h100` | 2 × H100 | The 40 image templates (published) | 52 / 52 | 17 s | 14.7 GB |
| `20261022-035829-h100` | 3 × H100 | The 26 video and two-reference templates, `angles`, `shots`, `zooms`, `whats-next` | 39 / 39 | 98 s | 46.6 GB |
| `20261022-173700-h100` | H100 | The 5 IC-LoRA apps, first try | 6 / 28 | 74 s | 41.8 GB |
| `20261022-181155-h100` | H100 NVL | The 5 IC-LoRA apps, licenses accepted | 28 / 28 | 106 s | 46.2 GB |
| `20261023-044125-h100` | H100 | `reframe` with a per-frame mask, `dub` with an empty audio latent and the speaker reference | 24 / 24 | 125 s | 55.7 GB |
| `20261023-124332-h100` | H100 | `mixed-media`: Klein redraws the first frame | 13 / 13 | 103 s | 55.7 GB |
| `20261023-131909-h100` | H100 | `mixed-media`: LoRA strength (0.7 stays stylized, 1.0 turns photoreal) | 17 / 17 | 98 s | 55.7 GB |
| `20261023-140409-h100` | H100 | `mixed-media`: the last looks | 4 / 4 | 102 s | 55.7 GB |
| `20261023-143551-h100` | H100 | `mixed-media`'s 16 looks on the final clip, the first 9 transformations of `morph` | 30 / 30 | 109 s | 55.7 GB |
| `20261023-162024-h100` | H100 | The other 6 transformations of `morph`, the Cakeify showcase of `effects` | 14 / 14 | 196 s | 50.2 GB |
| `20261023-222828-h100` | H100 | Weak templates, round 1 (`tplx-*`) | 31 / 31 | 89 s | 49.9 GB |
| `20261023-225832-h100` | H100 | Weak templates, round 2 | 26 / 26 | 66 s | 50.3 GB |
| `20261024-000821-h100` | H100 | Weak templates, round 3 | 12 / 12 | 74 s | 50.3 GB |
| `20261024-032920-l40s` | L40S | Queue job 01: face swap without a mask, `chameleon` | 6 / 6 | 101 s | 44.1 GB |
| `20261024-033622-l40s` | L40S | Queue job 02: face swap with MediaPipe's face oval as the mask | 5 / 5 | 20 s | 14.3 GB |
| `20261024-034326-l40s` | L40S | Queue job 03: the face swap example | 3 / 3 | 26 s | 14.3 GB |
| `20261024-035222-l40s` | L40S | Queue job 04: `reshoot`, its example now the result instead of the warp guide | 2 / 2 | 223 s | 44.1 GB |

A run with several GPUs (`--shards N`) splits the cases into N groups that run at the same time and comes back as
one folder. The cases a run lists include the reference images, clips and songs that the others read.

## What the runs changed

- **Effects.** The first round left 5 effects that failed. New photos fixed Inflate; Painting, Pirate
  captain, Zen and Crash zoom out were taken out; Dolly zoom and Bullet time moved to ostris's and joyfox's LoRAs;
  Money rain, Clones and Steam from nose and ears were added. After the fourth round Jungle, Samurai, Warrior,
  Jumpscare, Smoke outfit change and Gothic transformation were taken out to keep the app SFW. On 23 Oct the
  transformations that lose the face or look flat at 480p (Mona Lisa, VIP, Cartoon jaw drop, Selfie with younger self,
  Clones, then Assassin, Baby, Bride, Classy, Princess, Robot face reveal) moved to `morph`, which keeps the face:
  24 effects remain.
- **IC-LoRA apps.** `genjutsu`, `reframe`, `sdr-hdr`, `mixed-media` and `dub` each have a workflow of their own. The
  first run stopped at the gated Lightricks repos; `reframe` needed a mask for every frame and `dub` an empty audio
  latent plus the speaker reference wired into the guider.
- **Templates.** All 66 ran on 22 Oct. 15 came out weak and were redone with the `tplx-*` experiments in
  `lab/cases.json` (each one's note says what its run showed): product ads with the LTX prompt enhancer off and a fixed
  camera, Klein instructions that name what should be in the picture, four apps on a `morph` base (Klein draws the
  last frame, LTX-2.5 moves the photo into it), and face swap with MediaPipe's face oval as the mask and the face photo
  as Klein's only reference (four tries without a mask gave back the first photo).
- **`reshoot`.** Its workflow has two outputs and the warp guide was saved first, so its web example showed the guide
  (the clip from the new angle with the holes in magenta). The lab now saves an app's outputs in the order the app
  declares them; job 04 re-made the example.

## End to end from the browser (23 Oct)

Web UI → server → gateway on Modal → comfy-api-proxy → ComfyUI on an H100: `morph` (Astronaut) 160.8 s from the button
to the video, 128.7 s of it on the GPU; `mixed-media` (Anime) 149 s / 129.4 s; `dub` (a Spanish line) 72 s / 67 s, the
transcript matching the prompt. Four fixes came out of it, each with a test: links the gateway rewrites are https on a
public host (Modal sends no `X-Forwarded-Proto`), an mp4 is a video even when ComfyUI lists it under `images`, the
app's declared output nodes come first (core `LoadVideo` reports the clip it was given), and the server computes the
progress bar from the raw event stream (the proxy's first frames say 1.0 and the SDK drops everything after).

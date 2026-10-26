# Lab runs

Every GPU run of the lab (`lab/lab_modal.py`) from 20 to 26 Oct 2026, in order. Each run is a folder
`lab/results/<run id>` with `results.jsonl` (one row per case: status, seconds, peak VRAM), `run.json` (GPU, start
time) and `review.html`. Peaks are the highest of the run; on an 80 GB H100 ComfyUI can keep the models of earlier
steps loaded, so a peak there is not the least an app needs. 47 runs, 706 of 729 cases ok: 22 of the 23 failures are
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
| `20261024-164414-h100` | H100 | Queue job 05: six candidate portraits for the three woman references (`refx-*`) | 6 / 6 | 50 s | 12.6 GB |
| `20261024-164909-h100` | H100 | Queue job 06: the three new woman references and the 40 examples made from them | 48 / 48 | 215 s | 50.0 GB |
| `20261024-172353-h100` | 2 × H100 | Queue job 07: the ten new apps, `cinema-studio` and `video-t2v` | 20 / 20 | 204 s | 50.5 GB |
| `20261024-174729-h100` | H100 | Queue job 08: `expand-image` on a blurred canvas, `cinema-studio` with looks instead of gear | 3 / 3 | 25 s | 13.2 GB |
| `20261024-180125-h100` | H100 | Queue job 09: the runner reference with a named person, and the two cases that read it | 3 / 3 | 197 s | 39.9 GB |
| `20261024-181216-h100` | H100 | Queue job 10: the runner in a teal and black kit (the red and white one had a brand logo) | 3 / 3 | 189 s | 39.9 GB |
| `20261024-182254-h100` | H100 | Queue job 11: Klein removes the logo from the runner's top; Bullet Time Splash and Hero run re-made | 4 / 4 | 192 s | 40.3 GB |
| `20261024-192222-h100` | 3 × H100 | Queue job 12: brand logos out of the road photo, the athlete, Mascot and Style Snap; `reshoot` without the Turbo LoRA | 16 / 16 | 346 s | 59.0 GB |
| `20261024-230058-l40s` | 3 × L40S | Queue job 13: six prompts on five image models (`cmp-*`); Cinema Studio, AI Influencer and Meme on FLUX 3 Klein; `whats-next` from the lake | 37 / 37 | 37 s | 28.7 GB |
| `20261024-232228-l40s` | L40S | Queue job 14: two soundtracks of two minutes for the demo video | 2 / 2 | 161 s | 37.0 GB |
| `20261025-001104-l40s` | L40S | Queue job 15: AI Influencer asked for unbranded clothes; it drew striped sneakers, so the published example stayed | 1 / 1 | 15 s | 11.3 GB |
| `20261026-002124-l40s` | 2 × L40S | Queue job 16, batch 1 of Higgsfield's image menu: the influencer builder and its 9 character types, Create Image's looks at 1.5K and 2K, Cinema Studio's genre, era, lighting and palette, Relight's controls, Moodboard, Character (3 Photos), Photodump, Inpaint | 24 / 24 | 50 s | 28.6 GB |
| `20261026-003153-l40s` | L40S | Queue job 17: the animal heads asked as whole heads, Photodump with apps/character's wording, Moodboard with 1 MP references | 9 / 9 | 22 s | 12.6 GB |
| `20261026-003753-l40s` | L40S | Queue job 18: Photodump from its own vertical canvas with four framings; insect and bird without human hair | 4 / 4 | 23 s | 14.3 GB |
| `20261026-015446-l40s` | L40S | Queue job 19: Cinema Studio video (Klein first frame + LTX-2.5), one and two camera moves, Single shot and Dynamic tempo, enhancer on and off | 4 / 4 | 100 s | 44.4 GB |
| `20261026-020747-l40s` | L40S | Queue job 20: AI Influencer with two picks in three groups; the photo mode | 3 / 3 | 33 s | 12.6 GB |
| `20261026-021210-l40s` | L40S | Queue job 21: the same with plain clothes and the photo mode keeping the hairstyle | 3 / 3 | 20 s | 12.3 GB |
| `20261026-021507-l40s` | L40S | Queue job 22: the photo mode with plain shoes asked for | 2 / 2 | 18 s | 12.6 GB |
| `20261026-021906-l40s` | L40S | Queue job 23: the photo mode example waist-up at a night food stall | 2 / 2 | 19 s | 13.2 GB |
| `20261026-023750-l40s` | L40S | Queue job 24: for the demo video, AI Influencer's example animated by Image to Video, as *Use in…* does | 2 / 2 | 91 s | 43.9 GB |
| `20261026-034805-l40s` | L40S | Queue job 25: a second Mixed Media clip (a Japanese woman on a cherry blossom street) and its anime look | 2 / 2 | 121 s | 44.2 GB |
| `20261026-040431-l40s` | L40S | Queue job 26: the Anime look asking for anime eyes and each person's own skin tone | 2 / 2 | 117 s | 44.2 GB |
| `20261026-041209-l40s` | L40S | Queue job 27: the shot description also reaching Klein's first frame; the new Mixed Media example | 2 / 2 | 110 s | 44.2 GB |

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

- **References of people.** Z-Image tends to draw an East Asian face when a prompt names no one, and those portraits
  looked synthetic. On 24 Oct the three woman references (`ref-face-a`, `ref-fx-woman-a`, `ref-fx-woman-b`) got
  prompts that say who the person is, plus natural skin texture and no retouching; job 05 tried two candidates for
  each (`refx-*`, the verdict in each note) and job 06 re-made the 40 examples that start from them. The runner
  (`ref-fx-runner`) got the same change in jobs 09 to 11. Z-Image also printed a sports brand logo on her top, in a
  red and white kit and again in a teal one, whatever the prompt said, so Klein removes it (`ref-fx-runner-plain`)
  before Bullet Time Splash and the Hero run effect use the photo.
- **New apps.** Job 07 made the first examples of `depth-map`, `video-remove-bg`, `h3-video`, `h3-photo`,
  `extend-video`, `expand-image`, `ai-influencer` and the three Bullet Time apps. Two came back wrong and were fixed in
  job 08: `expand-image` drew a gray frame on the flat padding (it now starts from a blurred, stretched copy of the
  photo), and `cinema-studio` drew a film camera because its options named camera gear (they now describe the look).
- **The 20 Oct examples.** Reviewed one by one on 24 Oct. `video-t2v` got a new showcase (`t2v-trumpet`) and
  `cinema-studio` the change above; `camera-copy` (it moves forward more than it pans) and `motion-transfer` (the face
  leaves the frame at the end) are weak but kept.

- **Brand logos.** On 24 Oct every published example was checked by eye for brand marks. Z-Image and Klein had
  drawn a Ferrari, badge included, for the red sports car, three stripes and a logo on the parkour athlete, sports
  brand logos on the runner, Adidas marks on Mascot's kit and Nike swooshes on Style Snap's sneakers. Klein now
  repaints those references before other apps use them (`ref-fx-road-plain`, `ref-fx-jump-plain`,
  `ref-fx-runner-plain`), and Mascot and Style Snap ask for unbranded clothes. `whats-next` drew the badge back from
  the car's shape, so it moves to the lake photo.
- **`reshoot` without the Turbo LoRA** (lightx2v's, whose model card states no license): on the same clip, 20 and 30
  plain steps were not better than the 8 Turbo steps, softer with the same holes, and took 249 s and 346 s against
  190 s. The app keeps the Turbo LoRA and shows the license note next to it.

- **The image model.** Run 13 put six prompts on Z-Image Turbo, FLUX 3 Klein (with and without BFL's 9B prompt
  upsampler), Krea 2 Turbo and MOSS-Image, same seed. Klein followed the prompts best: three apples and five lemons
  where Z-Image drew four apples, the label text Krea 2 left out, the top-down view Krea missed, and a JSON prompt read
  as a scene where Z-Image printed its keys on the sign. Create Image, Cinema Studio, AI Influencer and Meme moved to
  Klein; the upsampler added about 8 s on an L40S. The comparison sheet is `docs/media/image-models.jpg`.
- **Soundtrack.** With empty lyrics MiniMax Music 3 made 20 s pieces (job 13); listing the song's sections as tags
  gave 130 s, and Stable Audio 3's music category gave 120 s with a quiet intro and a clean ending (job 14).

- **Batch 1 of Higgsfield's image menu (26 Oct).** The ten entries were read on Higgsfield and compared with the apps
  here. AI Influencer became a builder with the same trait groups; the animal types first came out as masks over a
  human face (frog, insect) or not at all (bird) and needed the whole animal head asked for and no human hair.
  Photodump first pasted the photo on four backgrounds, then kept its pose in two of four; each photo now starts from
  its own vertical canvas with its own framing. Moodboard took the references' look only once they went in at 1 MP
  with the look described first. Inpaint (a brush in the web UI and a noise mask) changed only the painted jacket.
- **Cinema Studio video and AI Influencer, refined (26 Oct).** The video mode draws its first frame with the still's
  graph and moves it with LTX-2.5: the dolly-in and the single take held, and with the Gemma enhancer on the face held
  better, so it defaults to on. Two camera moves in a row did not come out in order (crane down then arc right showed
  only the arc; tracking then whip pan came out reversed), and Dynamic tempo did change the angle once. AI Influencer's
  several picks showed (face gems, glasses, headphones); its first runs drew a "G/O" print on a vest and brand-like
  marks on sneakers until the prompt asked for plain clothes and shoes, and the photo mode cut the hair short until it
  was told to keep the hairstyle unless a new one is picked.
- **Mixed Media's anime, for the demo video (26 Oct).** On a new clip of a Japanese woman on a cherry blossom street the
  anime first frame came out tan, narrow-eyed and heavy-faced: Klein kept her real proportions under warm light. Asking
  the look for anime eyes and each person's own skin tone gave anime eyes but a frown; passing the shot description to
  Klein as well (who is in it: a smiling woman in her twenties) gave the smile back. That clip is now the app's example.

## End to end from the browser (23 Oct)

Web UI → server → gateway on Modal → comfy-api-proxy → ComfyUI on an H100: `morph` (Astronaut) 160.8 s from the button
to the video, 128.7 s of it on the GPU; `mixed-media` (Anime) 149 s / 129.4 s; `dub` (a Spanish line) 72 s / 67 s, the
transcript matching the prompt. Four fixes came out of it, each with a test: links the gateway rewrites are https on a
public host (Modal sends no `X-Forwarded-Proto`), an mp4 is a video even when ComfyUI lists it under `images`, the
app's declared output nodes come first (core `LoadVideo` reports the clip it was given), and the server computes the
progress bar from the raw event stream (the proxy's first frames say 1.0 and the SDK drops everything after).

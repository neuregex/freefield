# Lite versions

A lite version of an app runs the same workflow with some model files swapped for smaller copies of the same
models. The copies are in quantized formats that ComfyUI loads with the same loader node (`UNETLoader`,
`CLIPLoader`, `CheckpointLoaderSimple`…), so nothing in the workflow changes but a file name, and no third-party
node is needed. The formats are the ones in ComfyUI's `QUANTIZATION.md`:

| Format | Weights | Fast on | Elsewhere |
|---|---|---|---|
| `nvfp4` | 4-bit floats, blocks of 16 | RTX 50 series and newer (compute capability 10+) | ComfyUI keeps the 4-bit weights and dequantizes them for each matrix multiplication: the same memory saving, slower |
| `mxfp8` | 8-bit floats, blocks of 32 | RTX 50 series and newer, PyTorch 2.10+ | same as above |
| `w4a8` (`asym_w4a8_int8`) | 4-bit integers, int8 math | any card with int8 support (RTX 20 series and newer) | — |
| `w6a8` (`w6a8_int8`) | 6-bit integers, int8 math | same as `w4a8` | — |
| `fp4 mixed`, `nvfp4 + mxfp8` | most layers in 4 bits, the sensitive ones in 8 | as `nvfp4` | as `nvfp4` |

[`variants.json`](variants.json) says which file replaces which, keyed by the base name of the file an `app.json`
loads. `source: "official"` copies come from the model's own repo (or Comfy-Org's); `source: "freefield"` copies are
made by `tools/quantize.py` and published under the Freefield account, with the license of the model they come from.

What uses it:

- `server/registry.ts` attaches each copy to its model as `lite`; `server/variants.ts` picks the files of a version.
- `server/runner.ts` swaps the file names when an app runs lite (`POST /api/apps/:id/run?variant=lite`).
- `tools/catalog.py` writes `packs/<pack>-lite.json` (download only what the lite version loads) and the VRAM map
  for 8, 12, 16, 24, 32, 48 and 80 GB cards, for both versions.

Where it runs:

- **Your own GPU or a pod** (`FREEFIELD_BACKEND_NAME` is set): the studio's Models panel downloads `<pack>-lite`
  next to the full pack, and the form of each app with a lite version offers *Full* and *Lite*.
- **Modal** runs the full versions. To run the lite ones there too, download their packs into the volume
  (`modal run infra/modal_app.py::download --pack video-ltx25-lite`) and set `FREEFIELD_LITE=1` where
  `npm run serve` runs.
- The **My GPU** chip in the studio's top bar: pick your card size and RAM (on your own GPU or a pod it is read from
  the backend), and every app card, form and the VRAM map say whether the app fits as it is, fits in its lite version,
  or runs keeping part of its weights in RAM (slower). Those verdicts are estimates from the model sizes until a lab
  run on that card size measures them (`docs/vram-measured.json`).

A model with no smaller copy stays as it is in the lite version: an app is lite when at least one of its files is.
The official copies are listed as their makers publish them; the lab has not compared them with the full versions
yet.

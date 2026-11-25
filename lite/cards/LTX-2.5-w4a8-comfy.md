---
license: other
license_name: ltx-2.x-community-license-agreement
license_link: LICENSE
base_model:
- Lightricks/LTX-2.5
base_model_relation: quantized
pipeline_tag: image-to-video
tags:
- comfyui
- quantized
- w4a8
- ltx-2
- video
- audio
---

# LTX-2.5 22B distilled, w4a8 for ComfyUI

4-bit copies of [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The files weigh 23.1 GB in all, 34% of the 68.3 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `diffusion_models/ltx-2.5-22b-distilled-transformer-w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 12.5 GB | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` (42.0 GB) or `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (21.5 GB) |
| `text_encoders/gemma4-12b-with-proj-ltx-2.5-w4a8.safetensors` | `ComfyUI/models/text_encoders/` | 10.6 GB | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` (26.3 GB) or `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` (15.4 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `ltx-2.5-22b-distilled-transformer-w4a8.safetensors`: 1440 layers in w4a8, the ones `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.074.
- `gemma4-12b-with-proj-ltx-2.5-w4a8.safetensors`: 328 layers in w4a8, the ones `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- Checked: the same image-to-video workflow and seed as with the int8 files these replace (a portrait turning her head, 4 s with audio, on an L40S): the same motion and framing, small differences in hair and skin detail.

## Memory

Measured on an NVIDIA L40S with ComfyUI limited to each card size (`--reserve-vram`, a PyTorch memory cap and `--disable-dynamic-vram`), each run in a freshly started ComfyUI. RAM is the most the ComfyUI process used: below a certain card size it keeps part of the weights there. Times are for the L40S; a smaller card is slower. On a real card the CUDA context and some kernels also take memory outside that cap, so close to the limit ComfyUI keeps a little more in RAM.

**image to video, 4 s with audio, two stages**.

| Card | Original files | With these files |
|---|---|---|
| 8 GB | ✓ runs · 64 s · 50 GB RAM | ✓ runs · 60 s · 39 GB RAM |
| 12 GB | ✓ runs · 69 s · 52 GB RAM | ✓ runs · 64 s · 40 GB RAM |
| 16 GB | ✓ runs · 232 s · 61 GB RAM | ✓ runs · 70 s · 42 GB RAM |
| 24 GB | ✓ runs · 71 s · 57 GB RAM | ✓ runs · 60 s · 33 GB RAM |

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `ltx-2.5-22b-distilled-transformer-w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`); pick `gemma4-12b-with-proj-ltx-2.5-w4a8.safetensors` in **Load CLIP** (`CLIPLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

These files are a modified version of [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) by Lightricks: a Derivative of LTX-2.x, distributed under the **LTX-2.x Community License Agreement**, included in full as [LICENSE](LICENSE).

- Use of LTX-2.x and of any Derivative of it is subject to Section 4 and Attachment A of that agreement, including all of its use restrictions and acceptable use policies.
- A Commercial Entity (annual revenues of at least US$10,000,000) needs a paid commercial license from Lightricks before any use of LTX-2.x or its Derivatives, unless the use is a Non-Commercial Purpose as the agreement defines it.
- These files were changed: their weights were quantized as described above. Nothing else was changed.
- The text encoder holds the weights of Gemma 4 12B by Google, released under the Apache License 2.0 ([Gemma 4 license](https://ai.google.dev/gemma/docs/gemma_4_license)), with LTX-2.5's projection layers.

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

---
license: apache-2.0
base_model:
- Comfy-Org/Wan-Animate-2
base_model_relation: quantized
pipeline_tag: image-to-video
tags:
- comfyui
- quantized
- w4a8
- wan
- video
- animation
---

# Wan Animate 2 (distilled), w4a8 for ComfyUI

4-bit copies of [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The file weighs 9.6 GB in all, 29% of the 32.8 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `diffusion_models/wan_animate_2_distill_w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 9.6 GB | `wan_animate_2_distill_bf16.safetensors` (32.8 GB) or `wan_animate_2_distill_int8_convrot.safetensors` (16.6 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `wan_animate_2_distill_w4a8.safetensors`: 480 layers in w4a8, the ones `wan_animate_2_distill_int8_convrot.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- Checked: a motion transfer (a character photo moved by a walking clip, on an L40S) gave a coherent clip; not compared side by side with the original file yet.

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `wan_animate_2_distill_w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

Quantized from [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2), released under the **Apache License 2.0**, included as [LICENSE](LICENSE). These files were changed: their weights were quantized as described above. Nothing else was changed.

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

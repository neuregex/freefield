---
license: apache-2.0
base_model:
- Wan-AI/Wan2.1-I2V-14B-480P
base_model_relation: quantized
pipeline_tag: image-to-video
tags:
- comfyui
- quantized
- w4a8
- wan
- video
---

# Wan 2.1 I2V 14B 480p, w4a8 for ComfyUI

4-bit copies of [Wan-AI/Wan2.1-I2V-14B-480P](https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The file weighs 9.2 GB in all, 28% of the 32.8 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `diffusion_models/wan2.1_i2v_480p_14B_w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 9.2 GB | `wan2.1_i2v_480p_14B_bf16.safetensors` (32.8 GB) or `wan2.1_i2v_480p_14B_fp8_scaled.safetensors` (16.4 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `wan2.1_i2v_480p_14B_w4a8.safetensors`: 488 layers in w4a8, the ones `wan2.1_i2v_480p_14B_fp8_scaled.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- Checked: the same workflow and seed as with the fp8 file this replaces (image to video with the Cakeify effect LoRA, 81 frames, on an L40S): the effect plays out the same way; the cut and the cake inside differ in detail.

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `wan2.1_i2v_480p_14B_w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

Quantized from [Wan-AI/Wan2.1-I2V-14B-480P](https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P), released under the **Apache License 2.0**, included as [LICENSE](LICENSE). These files were changed: their weights were quantized as described above. Nothing else was changed.

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

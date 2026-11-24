---
license: apache-2.0
base_model:
- Qwen/Qwen-Image-Edit-2509
base_model_relation: quantized
pipeline_tag: image-to-image
tags:
- comfyui
- quantized
- w4a8
- qwen-image
- image-editing
---

# Qwen-Image-Edit 2509, w4a8 for ComfyUI

4-bit copies of [Qwen/Qwen-Image-Edit-2509](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The file weighs 11.6 GB in all, 28% of the 40.9 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `diffusion_models/qwen_image_edit_2509_w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 11.6 GB | `qwen_image_edit_2509_bf16.safetensors` (40.9 GB) or `qwen_image_edit_2509_fp8_e4m3fn.safetensors` (20.5 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `qwen_image_edit_2509_w4a8.safetensors`: 840 layers in w4a8, the ones `qwen_image_edit_2509_int8_convrot.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `qwen_image_edit_2509_w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

Quantized from [Qwen/Qwen-Image-Edit-2509](https://huggingface.co/Qwen/Qwen-Image-Edit-2509), released under the **Apache License 2.0**, included as [LICENSE](LICENSE). These files were changed: their weights were quantized as described above. Nothing else was changed.

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

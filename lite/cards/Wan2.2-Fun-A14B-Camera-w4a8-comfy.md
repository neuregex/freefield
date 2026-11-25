---
license: apache-2.0
base_model:
- alibaba-pai/Wan2.2-Fun-A14B-Control-Camera
base_model_relation: quantized
pipeline_tag: image-to-video
tags:
- comfyui
- quantized
- w4a8
- wan
- video
- camera-control
---

# Wan 2.2 Fun A14B Control Camera, w4a8 for ComfyUI

4-bit copies of [alibaba-pai/Wan2.2-Fun-A14B-Control-Camera](https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control-Camera) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The files weigh 18.1 GB in all, 31% of the 59.2 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `diffusion_models/wan2.2_fun_camera_high_noise_14B_w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 9.1 GB | `wan2.2_fun_camera_high_noise_14B_bf16.safetensors` (29.6 GB) or `wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors` (15.3 GB) |
| `diffusion_models/wan2.2_fun_camera_low_noise_14B_w4a8.safetensors` | `ComfyUI/models/diffusion_models/` | 9.1 GB | `wan2.2_fun_camera_low_noise_14B_bf16.safetensors` (29.6 GB) or `wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors` (15.3 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `wan2.2_fun_camera_high_noise_14B_w4a8.safetensors`: 406 layers in w4a8, the ones `wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- `wan2.2_fun_camera_low_noise_14B_w4a8.safetensors`: 406 layers in w4a8, the ones `wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- Checked: the same workflow and seed as with the fp8 files these replace (a zoom-in camera move through a library, 81 frames at 832×480, on an L40S): the same move and scene, the frames almost identical.

## Memory

Measured on an NVIDIA L40S with ComfyUI limited to each card size (`--reserve-vram`, a PyTorch memory cap and `--disable-dynamic-vram`), each run in a freshly started ComfyUI. RAM is the most the ComfyUI process used: below a certain card size it keeps part of the weights there. Times are for the L40S; a smaller card is slower. On a real card the CUDA context and some kernels also take memory outside that cap, so close to the limit ComfyUI keeps a little more in RAM.

**image to video with a zoom-in camera move, 81 frames at 832×480**.

| Card | Original files | With these files |
|---|---|---|
| 8 GB | ✗ out of memory | ✓ runs · 337 s · 37 GB RAM |
| 12 GB | ✗ out of memory | ✓ runs · 327 s · 37 GB RAM |
| 16 GB | ✗ out of memory | ✓ runs · 330 s · 32 GB RAM |
| 24 GB | ✓ runs · 364 s · 42 GB RAM | ✓ runs · 324 s · 31 GB RAM |

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `wan2.2_fun_camera_high_noise_14B_w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`); pick `wan2.2_fun_camera_low_noise_14B_w4a8.safetensors` in **Load Diffusion Model** (`UNETLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

Quantized from [alibaba-pai/Wan2.2-Fun-A14B-Control-Camera](https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control-Camera), released under the **Apache License 2.0**, included as [LICENSE](LICENSE). These files were changed: their weights were quantized as described above. Nothing else was changed.

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

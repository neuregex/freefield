---
license: other
license_name: minimax-music3-community-license
license_link: LICENSE
base_model:
- MiniMaxAI/MiniMax-Music3
base_model_relation: quantized
pipeline_tag: text-to-audio
tags:
- comfyui
- quantized
- w4a8
- minimax
- music
---

# MiniMax Music 3 text encoder, w4a8 for ComfyUI

4-bit copies of [MiniMaxAI/MiniMax-Music3](https://huggingface.co/MiniMaxAI/MiniMax-Music3) in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader nodes, no custom nodes. The file weighs 5.9 GB in all, 35% of the 16.7 GB of bf16 weights they come from.

## Files

| File | Put it in | Size | Instead of |
|---|---|---:|---|
| `text_encoders/minimax_music3_text_encoder_pruned_w4a8.safetensors` | `ComfyUI/models/text_encoders/` | 5.9 GB | `minimax_music3_text_encoder_pruned_bf16.safetensors` (16.7 GB) or `minimax_music3_text_encoder_pruned_int8_convrot.safetensors` (9.2 GB) |

## How they were made

- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with Comfy Kitchen 0.2.39, the library ComfyUI runs them with.
- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.
- `minimax_music3_text_encoder_pruned_w4a8.safetensors`: 160 layers in w4a8, the ones `minimax_music3_text_encoder_pruned_int8_convrot.safetensors` quantized. Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean 0.073, max 0.073.
- Checked: the same workflow and seeds as with the int8 file this replaces (a 10-second folk song with a female vocal, seeds 42, 7 and 1234, on an L40S), listened to side by side: the songs made with it sound as good; with the same seed the song comes out different, about as different as another seed makes it.

## Memory

Measured on an NVIDIA L40S with ComfyUI limited to each card size (`--reserve-vram`, a PyTorch memory cap and `--disable-dynamic-vram`), each run in a freshly started ComfyUI. RAM is the most the ComfyUI process used: below a certain card size it keeps part of the weights there. Times are for the L40S; a smaller card is slower. On a real card the CUDA context and some kernels also take memory outside that cap, so close to the limit ComfyUI keeps a little more in RAM.

**a 10-second song with vocals**.

| Card | Original files | With these files |
|---|---|---|
| 8 GB | ✓ runs · 80 s · 24 GB RAM | ✓ runs · 30 s · 16 GB RAM |
| 12 GB | ✓ runs · 39 s · 15 GB RAM | ✓ runs · 35 s · 14 GB RAM |
| 16 GB | ✓ runs · 50 s · 15 GB RAM | ✓ runs · 37 s · 14 GB RAM |
| 24 GB | ✓ runs · 45 s · 14 GB RAM | ✓ runs · 42 s · 14 GB RAM |

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `minimax_music3_text_encoder_pruned_w4a8.safetensors` in **Load CLIP** (`CLIPLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

These files are a modified version of [MiniMax Music 3](https://huggingface.co/MiniMaxAI/MiniMax-Music3), Copyright (c) 2026 MiniMax, distributed under the **MiniMax-Music3 Community License**, included in full as [LICENSE](LICENSE), together with its Acceptable Use Policy (Exhibit A). Its commercial terms apply: a commercial product or service that uses it shows "MiniMax-Music3" on its user interface, and one with yearly revenue above US$20 million needs written authorization from MiniMax. These files were changed: their weights were quantized as described above. MiniMax Music 3 was fine-tuned from Qwen3-8B (Apache License 2.0).

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

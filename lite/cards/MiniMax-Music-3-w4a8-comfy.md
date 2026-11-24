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

## Use

1. Put each file in the folder of the table above.
2. In your workflow, pick `minimax_music3_text_encoder_pruned_w4a8.safetensors` in **Load CLIP** (`CLIPLoader`). Nothing else changes.
3. ComfyUI from 2026-10-19 or newer (tested on commit `e3bee7f`, after 0.42.0). RTX 30 series cards and newer run them with int8 kernels; older cards dequantize each layer before multiplying (the same memory, slower).

## License

These files are a modified version of [MiniMax Music 3](https://huggingface.co/MiniMaxAI/MiniMax-Music3), Copyright (c) 2026 MiniMax, distributed under the **MiniMax-Music3 Community License**, included in full as [LICENSE](LICENSE), together with its Acceptable Use Policy (Exhibit A). Its commercial terms apply: a commercial product or service that uses it shows "MiniMax-Music3" on its user interface, and one with yearly revenue above US$20 million needs written authorization from MiniMax. These files were changed: their weights were quantized as described above. MiniMax Music 3 was fine-tuned from Qwen3-8B (Apache License 2.0).

## Community

Questions, results and other quantized models: [Discord](https://discord.gg/HxfP9TnctJ).

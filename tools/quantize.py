#!/usr/bin/env python3
"""A smaller copy of a model file in ComfyUI's own w4a8 format, for the apps' lite versions (lite/README.md).

    python tools/quantize.py SOURCE.safetensors --ref OFFICIAL.safetensors --out COPY.safetensors [--report report.json]

SOURCE is the model in bf16. REF is a quantized file of the same model made by its makers or by Comfy-Org (an int8
convrot file with `comfy_quant` entries, or an older scaled-fp8 file): the layers it quantized are the ones quantized
here, everything else is copied as it is. A layer the w4a8 format cannot hold (an embedding, a shape it does not
divide) keeps the reference's own quantized tensors when the reference has them in `comfy_quant` form, else bf16.

Each quantized layer is `asym_w4a8_int8` (ComfyUI's QUANTIZATION.md): Hadamard rotation in groups of 256 (64 or 16
when the width needs it), 4-bit codes on a Lloyd-Max codebook, fp8 scales every 16 weights and an fp32 scale per
output row, made with Comfy Kitchen's quantizer, the library ComfyUI loads the format with. ComfyUI runs it on
RTX 30 series cards and newer with int8 kernels; older cards dequantize it for each matrix multiplication.

The report says, for every quantized layer, the relative error of its weights after a round trip,
‖W − dequant(quant(W))‖ / ‖W‖, and the sizes before and after.

Needs torch, safetensors and comfy-kitchen (the ComfyUI image of infra/common.py has them); a GPU makes it fast.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

FORMAT = "asym_w4a8_int8"
GROUP_SIZE = 16
ROTATION_GROUPS = (256, 64, 16)          # powers of four; the first that divides K
# module names of embedding tables: the w4a8 format is for linear layers only
EMBEDDING = re.compile(r"(^|\.)(embed_tokens\w*|wte|word_embeddings|tok_embeddings|shared|embedding|embeddings)$")


def comfy_quant_tensor(config: dict):
    import torch
    return torch.tensor(list(json.dumps(config).encode("utf-8")), dtype=torch.uint8)


def read_comfy_quant(t) -> dict:
    return json.loads(bytes(t.cpu().numpy().tolist()).decode("utf-8"))


def reference_layers(ref_path: str) -> dict[str, dict | None]:
    """Module → its comfy_quant config (None for a scaled-fp8 weight), for every layer the reference quantized."""
    from safetensors import safe_open
    out: dict[str, dict | None] = {}
    with safe_open(ref_path, "pt", device="cpu") as f:
        keys = list(f.keys())
        for k in keys:
            if k.endswith(".comfy_quant"):
                out[k[: -len(".comfy_quant")]] = read_comfy_quant(f.get_tensor(k))
        if not out:   # an older scaled-fp8 file: its fp8 weights are the quantized layers
            for k in keys:
                if k.endswith(".weight") and str(f.get_slice(k).get_dtype()).upper().startswith("F8"):
                    out[k[: -len(".weight")]] = None
    return out


def rotation_group(k: int) -> int | None:
    if k % GROUP_SIZE:
        return None
    return next((g for g in ROTATION_GROUPS if k % g == 0), None)


def plan(src_path: str, ref_path: str) -> dict[str, list]:
    """Which modules become w4a8, which take the reference's tensors, which stay as they are."""
    from safetensors import safe_open
    ref = reference_layers(ref_path)
    w4a8, from_ref, kept = [], [], []
    with safe_open(src_path, "pt", device="cpu") as f:
        src_keys = set(f.keys())
        for module, conf in sorted(ref.items()):
            key = f"{module}.weight"
            if key not in src_keys:
                raise SystemExit(f"the reference quantized {module}, which the source does not have: "
                                 "are they files of the same model?")
            shape = f.get_slice(key).get_shape()
            k = shape[-1]
            if len(shape) == 2 and not EMBEDDING.search(module) and rotation_group(k):
                w4a8.append((module, rotation_group(k)))
            elif conf is not None:
                from_ref.append(module)
            else:
                kept.append(module)
    return {"w4a8": w4a8, "from_ref": from_ref, "kept": kept}


def quantize_file(src_path: str, ref_path: str, out_path: str, device: str | None = None, log=print) -> dict:
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file
    from comfy_kitchen.tensor import AsymW4A8Int8Layout, QuantizedTensor

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    t0 = time.time()
    p = plan(src_path, ref_path)
    w4a8 = dict(p["w4a8"])
    from_ref = set(p["from_ref"])
    log(f"{Path(src_path).name}: {len(w4a8)} layers to {FORMAT}, {len(from_ref)} from the reference, "
        f"{len(p['kept'])} kept (the reference had them in an older format); device {device}")
    out: dict = {}
    errors: list[tuple[str, float]] = []
    bytes_in = bytes_out = 0

    with safe_open(src_path, "pt", device="cpu") as f, safe_open(ref_path, "pt", device="cpu") as ref:
        metadata = dict(f.metadata() or {})
        ref_keys = list(ref.keys())
        for i, key in enumerate(f.keys()):
            t = f.get_tensor(key)
            bytes_in += t.numel() * t.element_size()
            module = key.rsplit(".", 1)[0] if "." in key else ""
            if module in from_ref:
                continue   # taken from the reference below, scales included
            if key.endswith(".weight") and module in w4a8:
                w = t.to(device=device, dtype=torch.bfloat16)
                qt = QuantizedTensor.from_float(w, "AsymW4A8Int8Layout", group_size=GROUP_SIZE,
                                                convrot_groupsize=w4a8[module])
                deq = AsymW4A8Int8Layout.dequantize(qt._qdata, qt._params).float()
                err = (torch.linalg.norm(w.float() - deq) / torch.linalg.norm(w.float()).clamp_min(1e-12)).item()
                errors.append((module, err))
                for name, v in qt.state_dict(key).items():
                    out[name] = v.detach().to("cpu").contiguous()
                out[f"{module}.comfy_quant"] = comfy_quant_tensor(
                    {"format": FORMAT, "group_size": GROUP_SIZE, "convrot_groupsize": w4a8[module]})
                del w, qt, deq
            else:
                out[key] = t.contiguous()
            if (i + 1) % 200 == 0:
                log(f"  {i + 1} tensors, {time.time() - t0:.0f}s")
        for module in sorted(from_ref):
            for k in ref_keys:
                if k.startswith(f"{module}."):
                    out[k] = ref.get_tensor(k).contiguous()

    bytes_out = sum(v.numel() * v.element_size() for v in out.values())
    metadata["freefield_quantization"] = json.dumps({"format": FORMAT, "group_size": GROUP_SIZE,
                                                     "source": Path(src_path).name, "reference": Path(ref_path).name})
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{out_path}.partial"
    save_file(out, tmp, metadata=metadata)
    Path(tmp).replace(out_path)

    errs = sorted(e for _, e in errors)
    report = {
        "source": Path(src_path).name, "reference": Path(ref_path).name, "output": Path(out_path).name,
        "format": FORMAT, "group_size": GROUP_SIZE,
        "rotation_groups": {str(g): sum(1 for v in w4a8.values() if v == g) for g in ROTATION_GROUPS if g in w4a8.values()},
        "layers_w4a8": len(w4a8), "layers_from_reference": sorted(from_ref), "layers_kept": p["kept"],
        "gb_in": round(bytes_in / 1e9, 2), "gb_out": round(Path(out_path).stat().st_size / 1e9, 2),
        "tensors_gb_out": round(bytes_out / 1e9, 2),
        "relative_error": {
            "mean": round(sum(errs) / len(errs), 4) if errs else None,
            "median": round(errs[len(errs) // 2], 4) if errs else None,
            "p95": round(errs[min(len(errs) - 1, math.ceil(0.95 * len(errs)) - 1)], 4) if errs else None,
            "max": round(errs[-1], 4) if errs else None,
            "worst": [[m, round(e, 4)] for m, e in sorted(errors, key=lambda x: -x[1])[:8]],
        },
        "seconds": round(time.time() - t0, 1),
    }
    log(f"  → {report['output']}: {report['gb_in']} GB → {report['gb_out']} GB, "
        f"relative error mean {report['relative_error']['mean']}, max {report['relative_error']['max']} "
        f"({report['seconds']}s)")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--ref", required=True, help="a quantized file of the same model (comfy_quant or scaled fp8)")
    ap.add_argument("--out", help="the file to write (not needed with --plan)")
    ap.add_argument("--report", help="write the report here as JSON")
    ap.add_argument("--device", help="cuda or cpu (default: cuda when there is one)")
    ap.add_argument("--plan", action="store_true", help="only say which layers would be quantized")
    a = ap.parse_args(argv)
    if a.plan:
        p = plan(a.source, a.ref)
        print(json.dumps({"w4a8": len(p["w4a8"]), "from_ref": p["from_ref"], "kept": p["kept"]}, indent=2))
        return 0
    if not a.out:
        ap.error("--out is required unless --plan")
    report = quantize_file(a.source, a.ref, a.out, device=a.device)
    if a.report:
        Path(a.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

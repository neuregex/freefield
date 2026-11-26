"""tools/quantize.py on a tiny made-up model: the layers its reference quantized become w4a8, an embedding keeps the
reference's own int8 tensors, the rest is copied. Needs torch, safetensors and comfy-kitchen (skipped without them):

    python test/quantize_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
try:
    import torch
    from safetensors.torch import load_file, save_file
    import comfy_kitchen  # noqa: F401
except ImportError as e:
    print(f"skipped: {e}")
    sys.exit(0)
import quantize  # tools/quantize.py


def cq(conf: dict):
    return torch.tensor(list(json.dumps(conf).encode()), dtype=torch.uint8)


def main() -> int:
    torch.manual_seed(0)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = {"blocks.0.q.weight": torch.randn(256, 512, dtype=torch.bfloat16) * 0.02,
               "blocks.0.q.bias": torch.randn(256, dtype=torch.bfloat16),
               "blocks.0.norm.weight": torch.ones(256, dtype=torch.bfloat16),
               "model.embed_tokens.weight": torch.randn(1000, 256, dtype=torch.bfloat16),
               "head.weight": torch.randn(16, 256, dtype=torch.bfloat16)}
        save_file(src, d / "src.safetensors", metadata={"config": "{}"})
        ref = {"blocks.0.q.weight": torch.zeros(256, 512, dtype=torch.int8), "blocks.0.q.weight_scale": torch.ones(()),
               "blocks.0.q.comfy_quant": cq({"format": "int8_tensorwise"}),
               "model.embed_tokens.weight": torch.ones(1000, 256, dtype=torch.int8), "model.embed_tokens.weight_scale": torch.ones(()),
               "model.embed_tokens.comfy_quant": cq({"format": "int8_tensorwise"})}
        save_file(ref, d / "ref.safetensors")
        r = quantize.quantize_file(str(d / "src.safetensors"), str(d / "ref.safetensors"), str(d / "out.safetensors"),
                                   device="cpu", log=lambda *_: None)
        out = load_file(d / "out.safetensors")
        assert r["layers_w4a8"] == 1 and r["layers_from_reference"] == ["model.embed_tokens"], r
        assert json.loads(bytes(out["blocks.0.q.comfy_quant"].tolist()))["format"] == "asym_w4a8_int8"
        assert out["blocks.0.q.weight"].dtype == torch.int8 and tuple(out["blocks.0.q.weight"].shape) == (256, 256)
        assert {"blocks.0.q.weight_s_rel", "blocks.0.q.weight_s_channel", "blocks.0.q.bias"} <= set(out)
        assert torch.equal(out["model.embed_tokens.weight"], ref["model.embed_tokens.weight"])   # the reference's, as it was
        assert torch.equal(out["head.weight"], src["head.weight"]) and torch.equal(out["blocks.0.norm.weight"], src["blocks.0.norm.weight"])
        assert 0 < r["relative_error"]["max"] < 0.15, r["relative_error"]
    print("quantize: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

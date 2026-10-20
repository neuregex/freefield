#!/usr/bin/env python3
"""Check API workflows against a running ComfyUI without a GPU or real model files.

ComfyUI validates every prompt when it is queued: node types, required inputs, value
ranges, links, and that each model file name is in its folder list. With --placeholders,
this script creates empty files with the expected names (models and example inputs) so
that check can run on any machine, even a CPU-only container. A prompt that passes is
cancelled right away so nothing heavy runs.

    python tools/comfy_validate.py --url http://127.0.0.1:8188 --comfy-dir /path/to/ComfyUI --placeholders
    python tools/comfy_validate.py --url ... apps/z-image/workflow.api.json other.api.json

With no workflow paths, it checks every apps/*/app.json that has a workflow, applying the
app's test values, with no preset and with each preset. With --lab, it checks the prompts a lab run would submit
(values, overrides and inserted LoRAs included), with tiny placeholders for chained inputs:

    python tools/comfy_validate.py --url ... --comfy-dir ... --placeholders --lab lab/cases.json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_EXT = (".safetensors", ".gguf", ".pt", ".pth", ".bin", ".ckpt", ".sft")
MODEL_DIRS = ["diffusion_models", "text_encoders", "vae", "loras", "checkpoints", "clip_vision",
              "latent_upscale_models", "upscale_models", "model_patches", "geometry_estimation",
              "background_removal", "frame_interpolation", "audio_encoders", "unet", "clip"]
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv")
AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body.decode(errors="replace")[:500]}


def _tiny_png(path: Path) -> None:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    w = h = 64
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def _tiny_wav(path: Path) -> None:
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)


def _tiny_mp4(path: Path) -> bool:
    try:
        import av  # ships with ComfyUI's requirements
        import numpy as np
    except ImportError:
        return False
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=24)
        s.width, s.height, s.pix_fmt = 64, 64, "yuv420p"
        for i in range(24):
            frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i * 8, dtype=np.uint8), format="rgb24")
            for p in s.encode(frame):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return True


def strings_in(api: dict) -> set[str]:
    out = set()
    for node in api.values():
        for v in node.get("inputs", {}).values():
            if isinstance(v, str):
                out.add(v)
    return out


def make_placeholders(api: dict, comfy_dir: Path) -> None:
    for s in strings_in(api):
        name = Path(s).name
        low = name.lower()
        if low.endswith(MODEL_EXT):
            for d in MODEL_DIRS:
                p = comfy_dir / "models" / d / s
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_bytes(b"")
        elif low.endswith(IMAGE_EXT + VIDEO_EXT + AUDIO_EXT) and "/" not in s:
            p = comfy_dir / "input" / s
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                continue
            if low.endswith(IMAGE_EXT):
                _tiny_png(p)
            elif low.endswith(AUDIO_EXT):
                _tiny_wav(p)
            elif not _tiny_mp4(p):
                p.write_bytes(b"")


def validate(url: str, api: dict, label: str) -> bool:
    status, body = _post(f"{url}/prompt", {"prompt": api, "client_id": "freefield-validate"})
    if status == 200 and "prompt_id" in body:
        _post(f"{url}/queue", {"delete": [body["prompt_id"]]})
        _post(f"{url}/interrupt", {})
        print(f"✓ {label}")
        return True
    print(f"✗ {label}")
    err = body.get("error") or {}
    if err:
        print(f"    {err.get('type', '')}: {err.get('message', '')} {err.get('details', '')}".rstrip())
    for nid, ne in (body.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            print(f"    node {nid} ({ne.get('class_type')}): {e.get('message')} — {e.get('details', '')}")
    if not err and not body.get("node_errors"):
        print(f"    HTTP {status}: {json.dumps(body)[:300]}")
    return False


def app_variants(app_dir: Path) -> list[tuple[str, dict]]:
    """The app's workflow with its test values applied, once per preset (or once with none)."""
    manifest = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
    if not manifest.get("workflow") or not (app_dir / manifest["workflow"]).exists():
        return []
    base = json.loads((app_dir / manifest["workflow"]).read_text(encoding="utf-8"))
    test = manifest.get("test") or {}
    values = {i["id"]: test.get(i["id"], i.get("default")) for i in manifest.get("inputs", [])}
    for i in manifest.get("inputs", []):   # the runner turns -1 into a random seed; any fixed one will do here
        if i["type"] == "seed" and values.get(i["id"]) in (None, -1, "-1"):
            values[i["id"]] = 42

    def render(t: str) -> str:
        import re
        return re.sub(r"\{([a-z][a-z0-9_]*)\}", lambda m: "" if values.get(m.group(1)) is None else str(values[m.group(1)]), t)

    def apply(api: dict, preset: dict | None) -> dict:
        api = json.loads(json.dumps(api))
        for inp in manifest.get("inputs", []):
            v = values.get(inp["id"])
            if v is None:
                continue
            for b in inp.get("bind", []):
                if inp["type"] in ("image", "video", "audio"):
                    api[b["node"]]["inputs"][b["field"]] = Path(str(v)).name
                else:
                    api[b["node"]]["inputs"][b["field"]] = render(b["template"]) if b.get("template") else v
            for opt in inp.get("options") or []:
                if opt["value"] == v:
                    for s in opt.get("sets", []):
                        api[s["node"]]["inputs"][s["field"]] = s["value"]
        for s in (preset or {}).get("sets", []):
            api[s["node"]]["inputs"][s["field"]] = s["value"]
        return api

    # no preset is a valid choice in the UI too, so check it alongside every preset
    return [(manifest["id"], apply(base, None))] + \
        [(f"{manifest['id']} [{p['id']}]", apply(base, p)) for p in manifest.get("presets") or []]


def lab_variants(cases_path: Path) -> list[tuple[str, dict]]:
    """Every lab case as the prompt the lab would queue; file inputs become placeholders."""
    sys.path.insert(0, str(ROOT / "lab"))
    import core  # lab/core.py
    ext = {"image": "png", "video": "mp4", "audio": "wav"}
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    out = []
    for c in cases:
        _, api, _ = core.build_case(ROOT / "apps", c, lambda _cid, _raw, kind: f"freefield_check_{kind}.{ext[kind]}")
        out.append((f"lab:{c['id']} ({c['app']})", api))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflows", nargs="*", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--comfy-dir", type=Path, help="ComfyUI folder, needed for --placeholders")
    ap.add_argument("--placeholders", action="store_true", help="create empty model files and tiny example inputs")
    ap.add_argument("--lab", type=Path, help="check the prompts of a lab cases file instead of the apps")
    a = ap.parse_args(argv)

    jobs: list[tuple[str, dict]] = []
    if a.lab:
        jobs = lab_variants(a.lab)
    elif a.workflows:
        for p in a.workflows:
            jobs.append((str(p), json.loads(p.read_text(encoding="utf-8"))))
    else:
        for app_dir in sorted((ROOT / "apps").iterdir()):
            if (app_dir / "app.json").exists():
                jobs += app_variants(app_dir)
    ok = 0
    for label, api in jobs:
        if a.placeholders:
            if not a.comfy_dir:
                print("--placeholders needs --comfy-dir", file=sys.stderr)
                return 2
            make_placeholders(api, a.comfy_dir)
        ok += validate(a.url.rstrip("/"), api, label)
        time.sleep(0.2)
    print(f"{ok}/{len(jobs)} workflows valid")
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    sys.exit(main())

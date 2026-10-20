"""Freefield backend on Modal: ComfyUI + comfy-api-proxy behind a token gateway.

One-time setup (in your terminal, from the repo root):
    python tools/setup_token.py                               # gateway token, same value in the secret and in .env
    modal secret create huggingface HF_TOKEN=hf_...          # accept the LTX-2.5 and FLUX 3 Klein licenses on the Hub first
    python tools/catalog.py packs

Models (once per pack; they stay in the "freefield-models" volume):
    modal run infra/modal_app.py::download --pack image
    modal run infra/modal_app.py::download --pack video-ltx25

Backend (private until you share the URL and token):
    FREEFIELD_GPU=L40S modal deploy infra/modal_app.py       # or A10G / L4 to test the 24 GB plan
    → https://<workspace>--freefield-serve.modal.run   (put it in .env as COMFY_BASE_URL)

Refresh the node definitions used by tools/ui2api.py:
    modal run infra/modal_app.py::object_info > tools/object_info.full.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from infra.common import (COMFY_DIR, build_image, ensure_models, freefield_secret, hf_secret,  # noqa: E402
                          models_volume, start_comfyui, wait_port)

GPU = os.environ.get("FREEFIELD_GPU", "L40S")
COMFY_ARGS = os.environ.get("FREEFIELD_COMFY_ARGS", "")   # e.g. "--reserve-vram 1" or "--disable-smart-memory"

app = modal.App("freefield")
image = build_image().add_local_python_source("infra")


@app.function(image=image, volumes={"/models": models_volume}, secrets=[hf_secret], timeout=4 * 3600, cpu=4, memory=8192)
def download(pack: str) -> dict:
    """Fetch every model a pack needs into the volume. Safe to re-run; existing files are skipped."""
    spec = json.loads(Path(f"/freefield/packs/{pack}.json").read_text())
    print(f"pack {pack}: {len(spec['models'])} files, {spec['download_gb']:.1f} GB")
    fetched, failed = ensure_models(spec["models"])
    models_volume.commit()   # keep what did arrive
    if failed:
        raise RuntimeError(f"{len(failed)} of {len(spec['models'])} files could not be downloaded:\n"
                           + "\n".join(f"  {k}: {v}" for k, v in failed.items()))
    return {"pack": pack, "fetched": fetched, "total_files": len(spec["models"])}


@app.function(
    image=image,
    gpu=GPU,
    volumes={"/models": models_volume},
    secrets=[freefield_secret],
    timeout=24 * 3600,
    scaledown_window=600,      # stays warm 10 min after the last request
    max_containers=1,          # one ComfyUI owns the GPU; the gateway queues the rest
)
@modal.concurrent(max_inputs=64)
@modal.web_server(8000, startup_timeout=900)
def serve():
    start_comfyui(8188, COMFY_ARGS)
    subprocess.Popen(["comfy-api-proxy", "--comfyui", "http://127.0.0.1:8188", "--port", "8189",
                      "--comfyui-base-dir", COMFY_DIR])
    wait_port(8189)
    env = {**os.environ, "COMFYUI_URL": "http://127.0.0.1:8188", "PROXY_URL": "http://127.0.0.1:8189", "GATEWAY_PORT": "8000"}
    subprocess.Popen(["python", "/freefield/infra/gateway.py"], env=env)


@app.function(image=image, timeout=1800, cpu=4, memory=8192)
def object_info() -> str:
    """Node definitions of exactly this image (custom nodes included), as JSON."""
    import urllib.request
    proc = start_comfyui(8188, "--cpu")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=120) as r:
            return r.read().decode()
    finally:
        proc.terminate()


@app.local_entrypoint()
def main():
    print(__doc__)


@app.local_entrypoint()
def save_object_info(out: str = "tools/object_info.full.json"):
    """modal run infra/modal_app.py::save_object_info  → writes the deployed image's node definitions."""
    Path(out).write_text(object_info.remote(), encoding="utf-8")
    print(f"wrote {out}")

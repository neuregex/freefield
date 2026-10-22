"""Pieces shared by the backend (infra/modal_app.py) and the LoRA lab (lab/lab_modal.py).

The image pins the exact ComfyUI commit the workflows in apps/ were validated against,
and installs every custom node pack the manifests declare. Model weights never go into
the image: they live in the "freefield-models" volume and are fetched per pack.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import modal

from infra.modal_profile import enforce as _enforce_profile

ROOT = Path(__file__).resolve().parent.parent
if modal.is_local():   # on your machine, before modal run/deploy creates anything; never inside containers
    _enforce_profile(ROOT)
COMFYUI_COMMIT = "e3bee7ffcb7d6547ed0bcd15221792f3b8646b17"   # 2026-10-19, ComfyUI 0.42.0+
COMFY_API_PROXY = "comfy-api-proxy==0.1.6"
COMFY_DIR = "/comfyui"
MODELS_DIR = "/models"
MODEL_DIRS = ["diffusion_models", "text_encoders", "vae", "loras", "checkpoints", "clip_vision",
              "latent_upscale_models", "upscale_models", "model_patches", "geometry_estimation",
              "background_removal", "frame_interpolation", "audio_encoders", "embeddings"]

models_volume = modal.Volume.from_name("freefield-models", create_if_missing=True)
lab_volume = modal.Volume.from_name("freefield-lab", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")        # HF_TOKEN, for gated repos (LTX-2.5, FLUX 3 Klein)
freefield_secret = modal.Secret.from_name("freefield")   # FREEFIELD_TOKEN, the gateway's bearer token


def custom_nodes() -> dict[str, str]:
    """repo URL → commit, from every packs/*.json (run tools/catalog.py packs first)."""
    out: dict[str, str] = {}
    for f in sorted((ROOT / "packs").glob("*.json")):
        if f.name == "index.json":
            continue
        for c in json.loads(f.read_text(encoding="utf-8")).get("custom_nodes", []):
            out[c["repo"]] = c["commit"]
    return out


def extra_model_paths() -> str:
    lines = ["freefield:", f"  base_path: {MODELS_DIR}"] + [f"  {d}: {d}" for d in MODEL_DIRS]
    return "\n".join(lines) + "\n"


def build_image() -> modal.Image:
    img = (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
        .run_commands(
            f"git clone https://github.com/Comfy-Org/ComfyUI.git {COMFY_DIR}",
            f"cd {COMFY_DIR} && git checkout {COMFYUI_COMMIT}",
            f"pip install -r {COMFY_DIR}/requirements.txt",
        )
        .pip_install(COMFY_API_PROXY, "aiohttp", "huggingface_hub[hf-xet]")   # hf-xet: fast downloads (hf_transfer is gone in hub 1.x)
    )
    for repo, commit in custom_nodes().items():
        name = repo.rstrip("/").rsplit("/", 1)[-1]
        target = f"{COMFY_DIR}/custom_nodes/{name}"
        img = img.run_commands(
            f"git clone {repo} {target} && cd {target} && git checkout {commit}",
            f"if [ -f {target}/requirements.txt ]; then pip install -r {target}/requirements.txt; fi",
        )
    yaml = extra_model_paths().replace("\n", "\\n")
    img = img.run_commands(f"printf '{yaml}' > {COMFY_DIR}/extra_model_paths.yaml")
    # code last, so editing it does not rebuild the layers above
    return (img.add_local_dir(ROOT / "apps", "/freefield/apps")
               .add_local_dir(ROOT / "packs", "/freefield/packs")
               .add_local_dir(ROOT / "infra", "/freefield/infra")
               .add_local_dir(ROOT / "lab", "/freefield/lab", ignore=["results", "assets"]))


# ---------------------------------------------------------------- runtime helpers (run inside containers)
def ensure_models(models: list[dict], token: str | None = None) -> tuple[list[str], dict[str, str]]:
    """Download any missing model file into the volume.

    Returns (names fetched, {name: reason} for files that could not be fetched). One failure
    does not stop the others: a gated repo whose license was not accepted only costs the
    apps that need it.
    """
    from huggingface_hub import hf_hub_download

    fetched: list[str] = []
    failed: dict[str, str] = {}
    tmp = Path(MODELS_DIR) / ".incoming"
    for m in models:
        name = m["file"].rsplit("/", 1)[-1]
        dest = Path(MODELS_DIR) / m["dir"] / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            path = hf_hub_download(repo_id=m["repo"], filename=m["file"], local_dir=tmp / m["repo"].replace("/", "__"),
                                   token=token or os.environ.get("HF_TOKEN"))
        except Exception as e:  # gated, renamed upstream, network
            reason = f"{type(e).__name__}: {(str(e).strip().splitlines() or [''])[0][:200]}"
            failed[name] = f"{m['repo']}: {reason}"
            print(f"  ✗ {name}  {failed[name]}")
            if "401" in reason or "403" in reason or "gated" in reason.lower():
                print(f"    accept the license at https://huggingface.co/{m['repo']} with the account behind HF_TOKEN")
            continue
        shutil.move(path, dest)
        fetched.append(name)
        print(f"  ↓ {name}  {m.get('gb', 0):.2f} GB  {time.time() - t0:.0f}s")
    shutil.rmtree(tmp, ignore_errors=True)
    return fetched, failed


def start_comfyui(port: int = 8188, extra_args: str = "") -> subprocess.Popen:
    cmd = ["python", "main.py", "--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch",
           "--extra-model-paths-config", f"{COMFY_DIR}/extra_model_paths.yaml"] + extra_args.split()
    proc = subprocess.Popen(cmd, cwd=COMFY_DIR)
    wait_http(f"http://127.0.0.1:{port}/system_stats", proc=proc)
    return proc


def wait_port(port: int, timeout_s: float = 60) -> None:
    import socket
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"port {port} not open after {timeout_s:.0f}s")


def wait_http(url: str, timeout_s: float = 900, proc: subprocess.Popen | None = None) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"process exited with {proc.returncode} before {url} came up")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"{url} not up after {timeout_s:.0f}s")

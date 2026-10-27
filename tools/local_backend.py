#!/usr/bin/env python3
"""Freefield's backend on your own GPU, without Modal.

The same three processes infra/modal_app.py runs in its container: ComfyUI at the pinned commit with the pinned
custom nodes, comfy-api-proxy (Comfy API v2) next to it, and infra/gateway.py in front (token check, unloads the
GPU when the app changes).

    python tools/local_backend.py setup  D:/freefield-comfy               # once: ComfyUI, custom nodes, comfy-api-proxy
    python tools/local_backend.py download D:/freefield-comfy image-flux3  # the model files of one or more packs
    python tools/local_backend.py serve  D:/freefield-comfy               # ComfyUI :8188, proxy :8189, gateway :8000

Run it in a virtualenv that already has the PyTorch build for your GPU (https://pytorch.org); setup installs ComfyUI's
other requirements but leaves torch alone. Models go to <dir>/models unless --models says otherwise. Gated repos
(LTX-2.5, FLUX 3 Klein) need their license accepted on Hugging Face and HF_TOKEN set, or `hf auth login`.
serve reads FREEFIELD_TOKEN from the environment or from .env (python tools/setup_token.py --env-only writes one);
then COMFY_BASE_URL=http://127.0.0.1:8000 in .env and `npm run serve`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "infra" / "common.py").read_text(encoding="utf-8")   # read, not imported: it needs modal
COMFYUI_COMMIT = re.search(r'^COMFYUI_COMMIT = "([0-9a-f]+)"', COMMON, re.M)[1]
COMFY_API_PROXY = re.search(r'^COMFY_API_PROXY = "([^"]+)"', COMMON, re.M)[1]
MODEL_DIRS = re.findall(r'"(\w+)"', re.search(r"^MODEL_DIRS = \[(.*?)\]", COMMON, re.M | re.S)[1])


def sh(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def pip(*args: str | Path) -> None:
    sh([sys.executable, "-m", "pip", "install", *args])


def packs() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "packs").glob("*.json"))
            if p.name != "index.json"}


def setup(comfy: Path, models: Path) -> None:
    try:
        import torch  # noqa: F401
    except ImportError:
        sys.exit("install the PyTorch build for your GPU in this environment first: https://pytorch.org")
    if not (comfy / ".git").exists():
        sh(["git", "clone", "https://github.com/Comfy-Org/ComfyUI.git", comfy])
    sh(["git", "checkout", "--quiet", COMFYUI_COMMIT], cwd=comfy)
    pip("-r", comfy / "requirements.txt")
    pinned = {c["repo"]: c["commit"] for p in packs().values() for c in p.get("custom_nodes", [])}
    for repo, commit in sorted(pinned.items()):
        dst = comfy / "custom_nodes" / repo.rstrip("/").rsplit("/", 1)[-1]
        if not dst.exists():
            sh(["git", "clone", repo, dst])
        sh(["git", "checkout", "--quiet", commit], cwd=dst)
        if (dst / "requirements.txt").exists():
            pip("-r", dst / "requirements.txt")
    pip(COMFY_API_PROXY, "aiohttp", "huggingface_hub[hf-xet]")
    lines = ["freefield:", f"  base_path: {models.as_posix()}"] + [f"  {d}: {d}" for d in MODEL_DIRS]
    (comfy / "extra_model_paths.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nComfyUI {COMFYUI_COMMIT[:7]} with {len(pinned)} custom nodes in {comfy}; models in {models}")
    print(f"next: python tools/local_backend.py download {comfy} <pack> (packs: {', '.join(packs())})")


def download(models: Path, names: list[str], dry_run: bool) -> None:
    all_packs = packs()
    unknown = [n for n in names if n != "all" and n not in all_packs]
    if unknown:
        sys.exit(f"unknown pack {unknown}; packs: {', '.join(all_packs)}")
    wanted = list(all_packs) if "all" in names else names
    files = {(m["repo"], m["file"]): m for n in wanted for m in all_packs[n]["models"]}
    todo = [m for m in files.values() if not (models / m["dir"] / m["name"]).exists()]
    print(f"{len(files)} files in {', '.join(wanted)}; {len(todo)} missing, {sum(m['gb'] for m in todo):.1f} GB")
    if dry_run:
        for m in todo:
            print(f"  {m['dir']}/{m['name']}  {m['gb']:.2f} GB  {m['repo']}{'  (gated)' if m.get('gated') else ''}")
        return
    from huggingface_hub import hf_hub_download
    tmp = models / ".incoming"
    failed = []
    for m in todo:
        dest = models / m["dir"] / m["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            path = hf_hub_download(repo_id=m["repo"], filename=m["file"], local_dir=tmp / m["repo"].replace("/", "__"))
        except Exception as e:  # gated, renamed upstream, network
            failed.append(m)
            print(f"  ✗ {m['name']}  {type(e).__name__}: {(str(e).strip().splitlines() or [''])[0][:160]}")
            if m.get("gated"):
                print(f"    accept the license at https://huggingface.co/{m['repo']} and set HF_TOKEN")
            continue
        shutil.move(path, dest)
        print(f"  ↓ {m['dir']}/{m['name']}  {m['gb']:.2f} GB")
    shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        sys.exit(f"{len(failed)} files could not be downloaded")


def wait_http(url: str, proc: subprocess.Popen, timeout_s: float = 600) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            sys.exit(f"{url}: the process exited with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(1)
    sys.exit(f"{url} did not answer in {timeout_s:.0f} s")


def wait_port(port: int, proc: subprocess.Popen, timeout_s: float = 120) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            sys.exit(f"port {port}: the process exited with code {proc.returncode}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(1)
    sys.exit(f"nothing listens on port {port} after {timeout_s:.0f} s")


def env_token() -> str:
    tok = os.environ.get("FREEFIELD_TOKEN", "")
    env = ROOT / ".env"
    if not tok and env.exists():
        m = re.search(r"^FREEFIELD_TOKEN=(\S+)\s*$", env.read_text(encoding="utf-8"), re.M)
        tok = m[1] if m else ""
    if not tok:
        sys.exit("no FREEFIELD_TOKEN: python tools/setup_token.py --env-only writes one to .env, "
                 "which npm run serve also reads")
    return tok


def serve(comfy: Path, comfy_args: list[str], port: int) -> None:
    token = env_token()
    proxy = shutil.which("comfy-api-proxy")
    if not proxy:
        sys.exit("comfy-api-proxy is not installed here: run setup first, in this same environment")
    procs = []
    try:
        cmd = [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch",
               "--extra-model-paths-config", str(comfy / "extra_model_paths.yaml"), *comfy_args]
        procs.append(subprocess.Popen(cmd, cwd=comfy))
        wait_http("http://127.0.0.1:8188/system_stats", procs[-1])
        procs.append(subprocess.Popen([proxy, "--comfyui", "http://127.0.0.1:8188", "--port", "8189",
                                       "--comfyui-base-dir", str(comfy)]))
        wait_port(8189, procs[-1])
        env = {**os.environ, "FREEFIELD_TOKEN": token, "COMFYUI_URL": "http://127.0.0.1:8188",
               "PROXY_URL": "http://127.0.0.1:8189", "GATEWAY_PORT": str(port)}
        procs.append(subprocess.Popen([sys.executable, str(ROOT / "infra" / "gateway.py")], env=env))
        wait_http(f"http://127.0.0.1:{port}/health", procs[-1], 120)
        print(f"\nbackend ready: COMFY_BASE_URL=http://127.0.0.1:{port} in .env, then npm run serve (Ctrl+C stops all)",
              flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        sys.exit("a backend process exited; the others are stopped")
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "download", "serve"):
        p = sub.add_parser(name)
        p.add_argument("dir", type=Path, help="where ComfyUI lives (setup clones it there)")
        p.add_argument("--models", type=Path, help="model folder (default: <dir>/models)")
        if name == "download":
            p.add_argument("packs", nargs="+", help="pack names from packs/index.json, or all")
            p.add_argument("--dry-run", action="store_true", help="list the missing files and stop")
        if name == "serve":
            p.add_argument("--port", type=int, default=8000, help="gateway port (default 8000)")
            p.add_argument("comfy_args", nargs=argparse.REMAINDER, help="extra ComfyUI flags after --, e.g. -- --lowvram")
    a = ap.parse_args()
    comfy = a.dir.expanduser().resolve()
    models = (a.models.expanduser().resolve() if a.models else comfy / "models")
    if a.cmd == "setup":
        setup(comfy, models)
    elif a.cmd == "download":
        download(models, a.packs, a.dry_run)
    else:
        serve(comfy, [x for x in a.comfy_args if x != "--"], a.port)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Freefield in one container, for a GPU rented by the hour: RunPod, Vast.ai, or any Docker host with an NVIDIA GPU.

The Docker image (Dockerfile at the repo root) runs this when the container starts:

1. downloads the model files of FREEFIELD_PACKS into FREEFIELD_DATA/models, skipping what is already there (a pod's
   volume keeps them, so a restart downloads nothing);
2. starts ComfyUI + comfy-api-proxy + the gateway, and the web studio in front (tools/local_backend.py serve --studio);
3. prints the link to open, with the passcode in it, and writes it to FREEFIELD_DATA/link.txt.

Environment, all optional:
  FREEFIELD_PACKS       packs to download, comma-separated, or `all` or `none` (default: image-flux3,upscale)
  HF_TOKEN              for gated models (FLUX 3 Klein, LTX-2.5): accept their licenses on Hugging Face first
  FREEFIELD_PASSCODE    the studio's passcode (default: a random one, kept in FREEFIELD_DATA/passcode)
  FREEFIELD_TOKEN       the gateway's token, for a studio on your own computer pointed at port 8000
                        (default: a random one, kept in FREEFIELD_DATA/token)
  FREEFIELD_DATA        models, history and the two keys (default /workspace/freefield: RunPod's volume)
  FREEFIELD_COMFY_ARGS  extra ComfyUI flags, e.g. "--lowvram" or "--cpu"
  FREEFIELD_TUNNEL=1    also open a Cloudflare quick tunnel (https) to the studio: for hosts that only give a plain
                        http IP:port, like Vast.ai
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMFY = Path(os.environ.get("FREEFIELD_COMFY_DIR", "/comfyui"))
DATA = Path(os.environ.get("FREEFIELD_DATA", "/workspace/freefield"))
MODELS = DATA / "models"
STUDIO_PORT = 3000
GATEWAY_PORT = 8000
DEFAULT_PACKS = "image-flux3,upscale"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def kept_secret(name: str, env: str) -> str:
    """The value of `env`, else the one kept in DATA/<name>, else a new random one kept there for the next start."""
    if os.environ.get(env, "").strip():
        return os.environ[env].strip()
    f = DATA / name
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(18)
    f.write_text(value + "\n", encoding="utf-8")
    f.chmod(0o600)
    return value


def packs() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "packs").glob("*.json"))
            if p.name != "index.json"}


def wanted_packs() -> list[str]:
    raw = os.environ.get("FREEFIELD_PACKS", DEFAULT_PACKS).replace(" ", "")
    if raw.lower() in ("", "none", "0"):
        return []
    known = packs()
    if raw.lower() == "all":
        return [p for p in known if p != "core"]
    names = [n for n in raw.split(",") if n]
    unknown = [n for n in names if n not in known]
    if unknown:
        say(f"! unknown pack {', '.join(unknown)} in FREEFIELD_PACKS (packs: {', '.join(known)}); skipped")
    return [n for n in names if n in known and n != "core"]


def download(names: list[str]) -> None:
    if not names:
        say("FREEFIELD_PACKS=none: no models downloaded (the smoke apps still run)")
        return
    all_packs = packs()
    files = {(m["repo"], m["file"]): m for n in names for m in all_packs[n]["models"]}
    todo = [m for m in files.values() if not (MODELS / m["dir"] / m["name"]).exists()]
    need = sum(m["gb"] for m in todo)
    free = shutil.disk_usage(DATA).free / 1e9
    say(f"packs {', '.join(names)}: {len(files)} files, {len(todo)} to download ({need:.1f} GB); "
        f"{free:.0f} GB free in {DATA}")
    if need > free - 2:
        say(f"! not enough disk for all of it: give the pod a volume of at least {need + 10:.0f} GB "
            f"(RunPod: Volume Disk; Vast: Disk Space), or fewer packs in FREEFIELD_PACKS")
    hf = os.environ.get("HF_TOKEN", "").strip()   # a pasted token often brings a space or a newline along
    if hf:
        os.environ["HF_TOKEN"] = hf
    if hf and any(m.get("gated") for m in todo) and not (hf.startswith("hf_") and len(hf) >= 30):
        say(f"! HF_TOKEN does not look like a Hugging Face token ({len(hf)} characters; a read token is hf_ and about "
            "34 more): the gated models will fail. Copy it again from https://huggingface.co/settings/tokens")
    if any(m.get("gated") for m in todo) and not hf:
        gated = sorted({m["repo"] for m in todo if m.get("gated")})
        say("! some of these models are gated and HF_TOKEN is not set: accept the licenses with your Hugging Face "
            "account, then set HF_TOKEN (a read token) on the pod:")
        for repo in gated:
            say(f"    https://huggingface.co/{repo}")
    if not todo:
        return
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "local_backend.py"), "download", str(COMFY),
                        "--models", str(MODELS), *names])
    if r.returncode:
        say("! some files could not be downloaded (above): the apps that need them will fail until they are there; "
            "fix it and restart the pod, which downloads only what is still missing")
    else:
        say(f"models ready in {time.time() - t0:.0f} s")


def model_paths() -> None:
    """Point ComfyUI at DATA/models, wherever FREEFIELD_DATA says it is (the image was built for the default)."""
    common = (ROOT / "infra" / "common.py").read_text(encoding="utf-8")
    dirs = re.findall(r'"(\w+)"', re.search(r"^MODEL_DIRS = \[(.*?)\]", common, re.M | re.S)[1])
    lines = ["freefield:", f"  base_path: {MODELS.as_posix()}"] + [f"  {d}: {d}" for d in dirs]
    (COMFY / "extra_model_paths.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for d in dirs:
        (MODELS / d).mkdir(parents=True, exist_ok=True)


def where() -> tuple[str, str | None, str | None]:
    """(provider name, the studio's public base URL if known, the gateway's) from what the provider sets."""
    pod = os.environ.get("RUNPOD_POD_ID")
    if pod:
        return "RunPod", f"https://{pod}-{STUDIO_PORT}.proxy.runpod.net", f"https://{pod}-{GATEWAY_PORT}.proxy.runpod.net"
    if os.environ.get("VAST_CONTAINERLABEL"):
        ip = os.environ.get("PUBLIC_IPADDR")
        sp, gp = os.environ.get(f"VAST_TCP_PORT_{STUDIO_PORT}"), os.environ.get(f"VAST_TCP_PORT_{GATEWAY_PORT}")
        return ("Vast.ai", f"http://{ip}:{sp}" if ip and sp else None, f"http://{ip}:{gp}" if ip and gp else None)
    return "this computer", f"http://127.0.0.1:{STUDIO_PORT}", None   # your own machine, or any other Docker host


def tunnel() -> tuple[subprocess.Popen | None, str | None]:
    """A Cloudflare quick tunnel to the studio (https://<random>.trycloudflare.com), or (None, None)."""
    exe = shutil.which("cloudflared")
    if not exe:
        say("! FREEFIELD_TUNNEL=1 but cloudflared is not in this image")
        return None, None
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{STUDIO_PORT}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    found: list[str] = []
    ready = threading.Event()

    def read() -> None:
        for line in proc.stderr:   # keep draining, or cloudflared blocks on a full pipe
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not found:
                found.append(m[0])
                ready.set()
    threading.Thread(target=read, daemon=True).start()
    ready.wait(60)
    if not found:
        say("! the Cloudflare tunnel did not give an address in 60 s; use the provider's own link instead")
    return proc, (found[0] if found else None)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    say(f"Freefield pod · data in {DATA}")
    passcode = kept_secret("passcode", "FREEFIELD_PASSCODE")
    token = kept_secret("token", "FREEFIELD_TOKEN")
    model_paths()
    download(wanted_packs())

    provider, studio_url, gateway_url = where()
    env = {**os.environ, "FREEFIELD_TOKEN": token, "FREEFIELD_PASSCODE": passcode, "FREEFIELD_OUT": str(DATA / "out"),
           "FREEFIELD_SHARED_HISTORY": "1",   # one owner: every browser with the passcode sees the same history
           "FREEFIELD_BACKEND_NAME": os.environ.get("FREEFIELD_BACKEND_NAME", provider),
           "FREEFIELD_MAX_UPLOAD_MB": os.environ.get("FREEFIELD_MAX_UPLOAD_MB", "1024"),
           "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0"}   # no second copy of the weights in a download cache
    serve = subprocess.Popen([sys.executable, str(ROOT / "tools" / "local_backend.py"), "serve", str(COMFY),
                              "--port", str(GATEWAY_PORT), "--studio", "--studio-host", "0.0.0.0",
                              "--studio-port", str(STUDIO_PORT), "--", *os.environ.get("FREEFIELD_COMFY_ARGS", "").split()],
                             cwd=ROOT, env=env)
    children = [serve]

    def stop(*_):
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    # the studio answers once ComfyUI, the proxy and the gateway are up (serve starts it last)
    import urllib.error
    import urllib.request
    deadline = time.time() + 1800
    while time.time() < deadline and serve.poll() is None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{STUDIO_PORT}/api/gpu", timeout=3)
            break
        except urllib.error.HTTPError:   # 401 without the passcode: it is up
            break
        except Exception:
            time.sleep(2)
    if serve.poll() is not None:
        sys.exit(serve.returncode or 1)

    if os.environ.get("FREEFIELD_TUNNEL") == "1":
        proc, url = tunnel()
        if proc:
            children.append(proc)
        if url:
            studio_url = url
    lines = ["", "=" * 72, f"Freefield is ready on {provider}."]
    if studio_url:
        lines.append(f"  Open:      {studio_url}/?key={passcode}")
    else:
        lines.append(f"  Open port {STUDIO_PORT} of this pod in your browser and add /?key={passcode} to the address")
    if studio_url and studio_url.startswith("http://127.0.0.1"):
        lines.append("  (from another computer on your network: this machine's IP address instead of 127.0.0.1)")
    lines.append(f"  Passcode:  {passcode}   (kept in {DATA / 'passcode'}; FREEFIELD_PASSCODE sets your own)")
    here = "this machine" if provider == "this computer" else "this pod"
    lines.append(f"  Your own studio instead, in its .env: COMFY_BASE_URL={gateway_url or f'<port {GATEWAY_PORT} of {here}>'}"
                 f" and FREEFIELD_TOKEN={token}")
    if provider == "this computer":
        lines.append("  `docker stop <container>` stops it; the models and the history stay in the volume.")
    else:
        lines.append("  The GPU is billed while the pod runs: stop it when you are done (models and history stay on the volume).")
    lines.append("=" * 72)
    say("\n".join(lines))
    (DATA / "link.txt").write_text("\n".join(lines[3:-1]) + "\n", encoding="utf-8")

    code = serve.wait()
    stop()
    sys.exit(code)


if __name__ == "__main__":
    main()

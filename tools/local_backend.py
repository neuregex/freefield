#!/usr/bin/env python3
"""Freefield's backend on your own GPU, without Modal.

The same three processes infra/modal_app.py runs in its container: ComfyUI at the pinned commit with the pinned
custom nodes, comfy-api-proxy (Comfy API v2) next to it, and infra/gateway.py in front (token check, unloads the
GPU when the app changes).

    python tools/local_backend.py setup  D:/freefield-comfy               # once: ComfyUI, custom nodes, comfy-api-proxy
    python tools/local_backend.py download D:/freefield-comfy image-flux3  # the model files of one or more packs
    python tools/local_backend.py serve  D:/freefield-comfy               # ComfyUI :8188, proxy :8189, gateway :8000
    python tools/local_backend.py serve  D:/freefield-comfy --studio      # the same, plus the web studio on :3000

Run it in a virtualenv that already has the PyTorch build for your GPU (https://pytorch.org); setup installs ComfyUI's
other requirements but leaves torch alone. Models go to <dir>/models unless --models says otherwise. Gated repos
(LTX-2.5, FLUX 3 Klein) need their license accepted on Hugging Face and HF_TOKEN set, or `hf auth login`, or a token
pasted in the studio's Models panel (serve keeps it in <models>/.hf_token). download notes what it could not get and
why in <models>/.downloads.json, which the panel shows.
serve reads FREEFIELD_TOKEN from the environment or from .env (python tools/setup_token.py --env-only writes one);
then COMFY_BASE_URL=http://127.0.0.1:8000 in .env and `npm run serve`, or add --studio and serve starts it too
(Node 22.6+ and `npm ci` in the repo first). infra/pod.py runs serve --studio inside the Docker image for RunPod/Vast.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
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


STATUS_FILE = ".downloads.json"   # in the model folder, next to .incoming
NO_TOKEN_EXIT = 3                  # download's exit code when the only files missing are waiting for a token


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def proc_start(pid: int) -> str | None:
    """When a process started (Linux, /proc), so a pid reused after a restart is not taken for this download."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat[stat.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError):
        return None


class Status:
    """<models>/.downloads.json: the files the downloads could not fetch and why, and the download running now, written
    as it goes. The gateway reads it for the studio's Models panel (infra/gateway.py); nothing else depends on it."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data.get("failed"), dict):
            self.data["failed"] = {}

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)   # whoever reads it sees the old file or the new one, never half of one


@contextlib.contextmanager
def one_at_a_time(lock: Path):
    """Two downloads at once would share .incoming: a second one waits for the first (on Linux and macOS; on Windows
    the gateway starts them one at a time anyway)."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    with open(lock, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another download is running here: this one starts when it ends", flush=True)
            fcntl.flock(f, fcntl.LOCK_EX)
        yield


def download(models: Path, names: list[str], dry_run: bool) -> None:
    all_packs = packs()
    unknown = [n for n in names if n != "all" and n not in all_packs]
    if unknown:
        sys.exit(f"unknown pack {unknown}; packs: {', '.join(all_packs)}")
    wanted = list(all_packs) if "all" in names else names
    files = {(m["repo"], m["file"]): m for n in wanted for m in all_packs[n]["models"]}
    missing = lambda: [m for m in files.values() if not (models / m["dir"] / m["name"]).exists()]  # noqa: E731
    todo = missing()
    print(f"{len(files)} files in {', '.join(wanted)}; {len(todo)} missing, {sum(m['gb'] for m in todo):.1f} GB", flush=True)
    if dry_run:
        for m in todo:
            print(f"  {m['dir']}/{m['name']}  {m['gb']:.2f} GB  {m['repo']}{'  (gated)' if m.get('gated') else ''}")
        return
    sys.path.insert(0, str(ROOT / "infra"))
    import hf  # infra/hf.py: which token, and what Hugging Face says about it

    models.mkdir(parents=True, exist_ok=True)
    with one_at_a_time(models / ".download.lock"):
        todo = missing()   # what is still missing once it is our turn
        status = Status(models / STATUS_FILE)
        tok, source = hf.token()
        problem = hf.env_problem()
        if problem and source != "studio":
            print(f"! {problem}", flush=True)
        job = {"state": "running", "pid": os.getpid(), "pid_start": proc_start(os.getpid()), "packs": wanted, "files": [f"{m['dir']}/{m['name']}" for m in todo],
               "gb": round(sum(m["gb"] for m in todo), 2), "done_gb": 0.0, "current": None, "started": now(), "ended": None}
        status.data["job"] = job
        status.save()

        waiting = [m for m in todo if m.get("gated") and not tok]
        if waiting:
            repos = sorted({m["repo"] for m in waiting})
            print(f"! {len(waiting)} files ({sum(m['gb'] for m in waiting):.1f} GB) are from models that ask you to accept "
                  "their license on Hugging Face, and there is no token yet: skipped. Accept the licenses, then paste a "
                  "read token in the studio's Models panel (or set HF_TOKEN):", flush=True)
            for repo in repos:
                print(f"    {hf.license_page(repo)}", flush=True)
            for m in waiting:
                status.data["failed"][f"{m['dir']}/{m['name']}"] = {"repo": m["repo"], "file": m["file"], "gated": True,
                                                                    "reason": "token_missing", "at": now()}
                job["done_gb"] = round(job["done_gb"] + m["gb"], 2)
            status.save()

        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import logging as hf_logging
        hf_logging.set_verbosity_error()   # no "unauthenticated requests" advice: this log says what is missing itself
        tmp = models / ".incoming"
        failed = 0
        told = set()   # each hint once, not once per file of the same repo
        for m in todo:
            if m in waiting:
                continue
            key = f"{m['dir']}/{m['name']}"
            dest = models / m["dir"] / m["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            job["current"] = {"file": key, "gb": m["gb"]}
            status.save()
            get = lambda t: hf_hub_download(repo_id=m["repo"], filename=m["file"],  # noqa: E731
                                            local_dir=tmp / m["repo"].replace("/", "__"), token=t)
            try:
                try:
                    path = get(tok or False)
                except Exception as e:
                    # a token Hugging Face refuses fails public files too: those still come without it
                    if not (tok and not m.get("gated") and getattr(getattr(e, "response", None), "status_code", None) == 401):
                        raise
                    path = get(False)
            except Exception as e:  # gated, renamed upstream, network
                failed += 1
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code == 401:
                    reason = "token_invalid" if tok else "token_missing"
                elif code == 403 and m.get("gated"):
                    reason = "license"
                else:
                    reason = "failed"
                first = (str(e).strip().splitlines() or [""])[0][:160]
                print(f"  ✗ {m['name']}  {type(e).__name__}: {first}", flush=True)
                if (reason, m["repo"]) in told:
                    pass
                elif reason == "token_invalid":
                    print(f"    Hugging Face did not take the token ({'HF_TOKEN' if source == 'env' else source}): paste a "
                          f"read token from {hf.TOKENS_PAGE} in the studio's Models panel", flush=True)
                elif reason == "token_missing":
                    print("    there is no Hugging Face token: paste one in the studio's Models panel, or set HF_TOKEN",
                          flush=True)
                elif reason == "license":
                    print(f"    this Hugging Face account has not accepted the license yet: {hf.license_page(m['repo'])} "
                          "(then Check again in the studio's Models panel)", flush=True)
                told.add((reason, m["repo"]))
                status.data["failed"][key] = {"repo": m["repo"], "file": m["file"], "gated": bool(m.get("gated")),
                                              "reason": reason, "error": f"{type(e).__name__}: {first}", "at": now()}
            else:
                shutil.move(path, dest)
                status.data["failed"].pop(key, None)
                print(f"  ↓ {key}  {m['gb']:.2f} GB", flush=True)
            job["done_gb"] = round(job["done_gb"] + m["gb"], 2)
            job["current"] = None
            status.save()
        shutil.rmtree(tmp, ignore_errors=True)
        job.update(state="done", ended=now(), failed=failed, waiting=len(waiting))
        status.save()
    if failed:
        sys.exit(f"{failed} files could not be downloaded")
    if waiting:
        sys.exit(NO_TOKEN_EXIT)


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


def find_proxy() -> str | None:
    """comfy-api-proxy next to this Python (a venv's Scripts/ or bin/, activated or not), else on PATH."""
    exe = "comfy-api-proxy.exe" if os.name == "nt" else "comfy-api-proxy"
    here = Path(sys.executable).parent / exe
    return str(here) if here.exists() else shutil.which("comfy-api-proxy")


def studio_command() -> list[str]:
    """node running server/server.ts as `npm run serve` does, or exit saying what is missing."""
    node = shutil.which("node")
    if not node:
        sys.exit("--studio needs Node 22.6+ on PATH (https://nodejs.org)")
    if not (ROOT / "node_modules" / "@comfyorg" / "sdk").exists():
        sys.exit(f"--studio needs the studio's packages: run npm ci in {ROOT}")
    return [node, "--env-file-if-exists=.env", "--experimental-strip-types", "--disable-warning=ExperimentalWarning",
            "server/server.ts"]


def serve(comfy: Path, models: Path, comfy_args: list[str], port: int, studio: tuple[str, int] | None = None) -> None:
    token = env_token()
    proxy = find_proxy()
    studio_cmd = studio_command() if studio else None

    def stop(*_):   # a plain kill, a closed terminal tab, a service manager: stop all three, as Ctrl+C does
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    if not proxy:
        sys.exit("comfy-api-proxy is not installed here: run setup first, in this same environment")
    procs = []
    try:
        # ComfyUI reads extra_model_paths.yaml next to its main.py by itself: passing it again listed every path twice
        cmd = [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch", *comfy_args]
        procs.append(subprocess.Popen(cmd, cwd=comfy))
        wait_http("http://127.0.0.1:8188/system_stats", procs[-1])
        procs.append(subprocess.Popen([proxy, "--comfyui", "http://127.0.0.1:8188", "--port", "8189",
                                       "--comfyui-base-dir", str(comfy)]))
        wait_port(8189, procs[-1])
        # FREEFIELD_MODELS turns on the gateway's downloads (the studio's Models panel): pasting a Hugging Face token
        # there keeps it in FREEFIELD_HF_TOKEN_FILE (in the pod's volume; next to the models on your own machine)
        env = {**os.environ, "FREEFIELD_TOKEN": token, "COMFYUI_URL": "http://127.0.0.1:8188",
               "PROXY_URL": "http://127.0.0.1:8189", "GATEWAY_PORT": str(port),
               "FREEFIELD_MODELS": str(models), "FREEFIELD_COMFY_DIR": str(comfy),
               "FREEFIELD_HF_TOKEN_FILE": os.environ.get("FREEFIELD_HF_TOKEN_FILE") or str(models / ".hf_token")}
        procs.append(subprocess.Popen([sys.executable, str(ROOT / "infra" / "gateway.py")], env=env))
        wait_http(f"http://127.0.0.1:{port}/health", procs[-1], 120)
        if studio_cmd and studio:
            host, sport = studio
            # values set here win over .env (Node's --env-file never overrides the environment); .env still adds the rest
            senv = {**env, "COMFY_BASE_URL": f"http://127.0.0.1:{port}", "FREEFIELD_HOST": host, "PORT": str(sport)}
            senv.setdefault("FREEFIELD_BACKEND_NAME", "this computer")   # never sleeps: the GPU pill says so
            procs.append(subprocess.Popen(studio_cmd, cwd=ROOT, env=senv))
            wait_port(sport, procs[-1], 60)
            shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
            if not os.environ.get("FREEFIELD_POD"):   # in the image, infra/pod.py prints the link with its passcode
                print(f"\nready: open http://{shown}:{sport} (Ctrl+C stops all)", flush=True)
        else:
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
    if hasattr(sys.stdout, "reconfigure"):   # a Windows console or pipe in cp1252 must not stop on ✗ or ↓
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="serve passes anything after -- to ComfyUI, e.g. serve DIR -- --lowvram")
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
            p.add_argument("--studio", action="store_true", help="also start the web studio, pointed at this backend")
            p.add_argument("--studio-port", type=int, default=3000, help="studio port (default 3000)")
            p.add_argument("--studio-host", default="127.0.0.1",
                           help="studio address (default 127.0.0.1; 0.0.0.0 to reach it from other machines: "
                                "set FREEFIELD_PASSCODE then)")
    # ComfyUI's own flags go after --; split them off first: an argparse REMAINDER positional also swallowed
    # serve's options written after the folder (`serve DIR --studio` sent --studio to ComfyUI)
    argv = sys.argv[1:]
    comfy_args: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, comfy_args = argv[:cut], argv[cut + 1:]
    a = ap.parse_args(argv)
    comfy = a.dir.expanduser().resolve()
    models = (a.models.expanduser().resolve() if a.models else comfy / "models")
    if a.cmd == "setup":
        setup(comfy, models)
    elif a.cmd == "download":
        download(models, a.packs, a.dry_run)
    else:
        serve(comfy, models, comfy_args, a.port,
              (a.studio_host, a.studio_port) if a.studio else None)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Pre-flight check before the first GPU run: what is missing, and the command that fixes it.

    python tools/doctor.py                      # everything: all packs and the lab's LoRAs
    python tools/doctor.py --pack video-ltx25   # only the models of these packs (comma-separated)

It checks Node and the npm install, the Modal CLI and its two secrets, that your Hugging Face
token can download every gated model the packs need (one HEAD request per file, nothing is
downloaded), and the .env the web app reads. Tokens are never printed; the Hugging Face token
is only sent to huggingface.co and FREEFIELD_TOKEN only to your own COMFY_BASE_URL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, BAD, WARN = "✓", "✗", "!"
results: list[tuple[str, str, str]] = []


def report(mark: str, what: str, fix: str = "") -> None:
    results.append((mark, what, fix))
    print(f"{mark} {what}" + (f"\n    → {fix}" if fix else ""))


def run(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def check_node() -> None:
    code, out = run(["node", "--version"])
    m = re.match(r"v(\d+)\.(\d+)", out) if code == 0 else None
    if not m:
        report(BAD, "Node.js not found", "install Node 22.6 or newer from https://nodejs.org")
    elif (int(m[1]), int(m[2])) < (22, 6):
        report(BAD, f"Node {out} is too old", "install Node 22.6 or newer")
    else:
        report(OK, f"Node {out}")
    if (ROOT / "node_modules" / "@comfyorg" / "sdk").exists():
        report(OK, "npm packages installed")
    else:
        report(BAD, "npm packages missing", "npm install")


def check_modal() -> None:
    code, out = run([sys.executable, "-m", "modal", "--version"])
    if code != 0:
        report(BAD, "Modal CLI not installed for this Python", f"{Path(sys.executable).name} -m pip install modal")
        return
    report(OK, f"Modal CLI {out.split()[-1] if out else ''}".strip())
    code, out = run([sys.executable, "-m", "modal", "secret", "list", "--json"], timeout=90)
    if code != 0:
        report(BAD, "Modal is not logged in (or unreachable)", "modal setup")
        return
    try:
        names = {s.get("Name") or s.get("name") for s in json.loads(out)}
    except json.JSONDecodeError:
        names = set(re.findall(r"\b(freefield|huggingface)\b", out))
    fixes = {
        "freefield": "python tools/setup_token.py   (same token in the secret and in .env)",
        "huggingface": "modal secret create huggingface HF_TOKEN=hf_...",
    }
    for name, fix in fixes.items():
        if name in names:
            report(OK, f'Modal secret "{name}"')
        else:
            report(BAD, f'Modal secret "{name}" missing', fix)


def hf_token() -> str | None:
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    f = home / "token"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def head(url: str, token: str | None) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"authorization": f"Bearer {token}"} if token else {})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def check_hf(packs: list[str], with_lab: bool) -> None:
    token = hf_token()
    if token:
        report(OK, "Hugging Face token found (HF_TOKEN or huggingface-cli login)")
    else:
        report(WARN, "No Hugging Face token here; gated models cannot be checked",
               "set HF_TOKEN (the same one you put in the Modal secret) or run: huggingface-cli login")
    # access is granted per repo, so one file per repo is enough
    repos: dict[str, tuple[str, bool | None, str]] = {}   # repo -> (file, gated, where)
    for pack in packs:
        for m in json.loads((ROOT / "packs" / f"{pack}.json").read_text(encoding="utf-8")).get("models", []):
            repos.setdefault(m["repo"], (m["file"], bool(m.get("gated")), pack))
    if with_lab:   # LoRAs only the lab uses; their gating is not recorded, so ask the Hub
        for c in json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]:
            for l in c.get("loras", []) + c.get("loras_download", []):
                repos.setdefault(l["repo"], (l["file"], None, "lab"))
    for repo, (file, gated, where) in sorted(repos.items(), key=lambda kv: (kv[1][2], kv[0])):
        if gated is False:
            continue
        if not token:
            if gated:
                report(WARN, f"{where}: {repo} is gated", f"accept its license at https://huggingface.co/{repo}")
            continue
        status = head(f"https://huggingface.co/{repo}/resolve/main/{file}", token)
        if status in (200, 302, 307):
            report(OK, f"{where}: access to {repo}")
        elif status in (401, 403):
            report(BAD, f"{where}: no access to {repo}", f"accept the license at https://huggingface.co/{repo}")
        elif status == 404:
            report(BAD, f"{where}: {repo}/{file} not found", "the file was renamed upstream; update the app.json or lab case")
        else:
            report(WARN, f"{where}: could not check {repo} (HTTP {status})")


def check_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        report(BAD, ".env missing (the web app reads COMFY_BASE_URL and FREEFIELD_TOKEN from it)",
               "python tools/setup_token.py   (creates .env with the same token as the Modal secret)")
        return
    values = dict(re.findall(r"^\s*([A-Z_]+)\s*=\s*(.*?)\s*$", env.read_text(encoding="utf-8"), flags=re.M))
    base, token = values.get("COMFY_BASE_URL", ""), values.get("FREEFIELD_TOKEN", "")
    if not base or "YOUR-WORKSPACE" in base:
        report(BAD, "COMFY_BASE_URL not set in .env", "paste the URL printed by: modal deploy infra/modal_app.py")
        return
    if not token:
        report(BAD, "FREEFIELD_TOKEN empty in .env", "python tools/setup_token.py   (writes one token to .env and the Modal secret)")
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/health", timeout=20) as r:
            report(OK, f"backend answers at {base} (HTTP {r.status})")
    except Exception as e:  # a cold Modal container can take a while; this is only a hint
        report(WARN, f"backend at {base} did not answer /health ({type(e).__name__})",
               "deploy it (modal deploy infra/modal_app.py) or wait for a cold start and retry")
        return
    if token:
        req = urllib.request.Request(f"{base.rstrip('/')}/freefield/status", headers={"authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                report(OK, f"gateway accepts the token (HTTP {r.status})")
        except urllib.error.HTTPError as e:
            report(BAD, f"gateway refused the token (HTTP {e.code})",
                   "python tools/setup_token.py, then modal deploy infra/modal_app.py so the backend gets the new token")
        except Exception as e:
            report(WARN, f"could not reach /freefield/status ({type(e).__name__})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", default="", help="comma-separated packs to check (default: all)")
    ap.add_argument("--skip", default="", help="comma-separated sections to skip: node, modal, hf, env")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    all_packs = sorted(p.stem for p in (ROOT / "packs").glob("*.json") if p.name != "index.json")
    packs = [p for p in a.pack.split(",") if p] or all_packs
    unknown = set(packs) - set(all_packs)
    if unknown:
        print(f"unknown pack(s): {', '.join(sorted(unknown))}; known: {', '.join(all_packs)}", file=sys.stderr)
        return 2
    skip = set(a.skip.split(","))
    with_lab = not a.pack   # a full check also covers the LoRAs the lab downloads
    for name, fn in [("node", check_node), ("modal", check_modal), ("hf", lambda: check_hf(packs, with_lab)), ("env", check_env)]:
        if name not in skip:
            print(f"\n[{name}]")
            fn()
    bad = sum(1 for m, _, _ in results if m == BAD)
    warn = sum(1 for m, _, _ in results if m == WARN)
    if bad:
        print(f"\n{bad} problem(s)" + (f", {warn} more to check" if warn else ""))
    elif warn:
        print(f"\nnothing blocking found; {warn} thing(s) above could not be checked")
    else:
        print("\nready for a GPU run")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

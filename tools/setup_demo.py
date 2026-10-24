#!/usr/bin/env python3
"""The passcode of the hosted demo (infra/web_app.py), and the link to share.

    python tools/setup_demo.py           # new passcode → Modal secret "freefield-demo" and .env (FREEFIELD_DEMO_PASSCODE)
    python tools/setup_demo.py --link    # print the link: the deployed demo URL with ?key=<passcode>

The hosted web UI reads FREEFIELD_PASSCODE from the Modal secret; .env keeps the same value under another name
(FREEFIELD_DEMO_PASSCODE) so that `npm run serve` on your machine stays open. Run it again to change the passcode,
then `modal deploy infra/web_app.py` so the container picks it up; anyone holding the old link is locked out.
"""
from __future__ import annotations

import argparse
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = "FREEFIELD_DEMO_PASSCODE"


def read_env(env: Path) -> str:
    return env.read_text(encoding="utf-8") if env.exists() else ""


def link(env: Path) -> int:
    m = re.search(rf"^{KEY}=(\S+)\s*$", read_env(env), flags=re.M)
    if not m:
        print(f"no {KEY} in .env yet: run  python tools/setup_demo.py", file=sys.stderr)
        return 1
    try:
        import modal
        url = modal.Function.from_name("freefield-web", "web").get_web_url()
    except Exception as e:  # noqa: BLE001 - not deployed yet, or no Modal login here
        print(f"could not find the deployed demo ({e}); deploy it with  modal deploy infra/web_app.py", file=sys.stderr)
        return 1
    print(f"{url.rstrip('/')}/?key={m[1]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--link", action="store_true", help="print the link to share and change nothing")
    a = ap.parse_args(argv)
    env = ROOT / ".env"
    if a.link:
        return link(env)

    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        print("created .env from .env.example")
    sys.path.insert(0, str(ROOT))
    from infra.modal_profile import check
    active, pinned, ok = check(ROOT)
    if not ok:
        print(f'Modal profile "{active}" is active, but .env pins "{pinned}"; nothing changed. '
              f"Switch with:  modal profile activate {pinned}", file=sys.stderr)
        return 1

    passcode = secrets.token_urlsafe(12)
    cmd = [sys.executable, "-m", "modal", "secret", "create", "freefield-demo", f"FREEFIELD_PASSCODE={passcode}", "--force"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"could not run the Modal CLI ({e}); nothing changed", file=sys.stderr)
        return 1
    if r.returncode != 0:
        print((r.stderr or r.stdout).strip(), file=sys.stderr)
        print('the Modal secret "freefield-demo" was not updated, so .env was left as it was', file=sys.stderr)
        return 1
    print(f'stored a new passcode in the Modal secret "freefield-demo" of profile "{active}"')

    text = read_env(env)
    line = f"{KEY}={passcode}"
    if re.search(rf"^{KEY}=.*$", text, flags=re.M):
        text = re.sub(rf"^{KEY}=.*$", line, text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    with open(env, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"wrote it to .env as {KEY}")
    print("next: modal deploy infra/web_app.py   then   python tools/setup_demo.py --link")
    return 0


if __name__ == "__main__":
    sys.exit(main())

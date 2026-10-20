#!/usr/bin/env python3
"""One gateway token, written to the two places that need it.

    python tools/setup_token.py              # new token → Modal secret "freefield" and .env
    python tools/setup_token.py --env-only   # only .env (when the backend is not on Modal)

The backend's gateway reads FREEFIELD_TOKEN from the Modal secret; the web app and the CLI read
the same value from .env. This creates .env from .env.example when it is missing, stores a fresh
random token in the secret (overwriting it), and only then writes it to .env, so the two never
disagree. The token is not printed; .env is ignored by git. Run it again to rotate the token,
then redeploy the backend so new containers pick it up.
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env-only", action="store_true", help="write .env without touching the Modal secret")
    a = ap.parse_args(argv)

    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        print("created .env from .env.example")
    token = secrets.token_urlsafe(32)

    if not a.env_only:
        sys.path.insert(0, str(ROOT))
        from infra.modal_profile import check
        active, pinned, ok = check(ROOT)
        if not ok:
            print(f'Modal profile "{active}" is active, but .env pins "{pinned}"; nothing changed. '
                  f"Switch with:  modal profile activate {pinned}", file=sys.stderr)
            return 1
        cmd = [sys.executable, "-m", "modal", "secret", "create", "freefield", f"FREEFIELD_TOKEN={token}", "--force"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"could not run the Modal CLI ({e}); nothing changed", file=sys.stderr)
            return 1
        if r.returncode != 0:
            print((r.stderr or r.stdout).strip(), file=sys.stderr)
            print('the Modal secret "freefield" was not updated, so .env was left as it was', file=sys.stderr)
            return 1
        print(f'stored the token in the Modal secret "freefield" of profile "{active}"')

    text = env.read_text(encoding="utf-8")
    line = f"FREEFIELD_TOKEN={token}"
    if re.search(r"^FREEFIELD_TOKEN=.*$", text, flags=re.M):
        text = re.sub(r"^FREEFIELD_TOKEN=.*$", line, text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    with open(env, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote the same token to .env")
    if "YOUR-WORKSPACE" in text or not re.search(r"^COMFY_BASE_URL=\S+", text, flags=re.M):
        print("next: put the backend URL from `modal deploy infra/modal_app.py` in .env as COMFY_BASE_URL")
    return 0


if __name__ == "__main__":
    sys.exit(main())

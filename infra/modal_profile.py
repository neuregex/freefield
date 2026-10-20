"""Which Modal profile a command will act on, and whether it is the one this repo is pinned to.

Modal takes the profile from MODAL_PROFILE, otherwise from the section marked `active = true`
in ~/.modal.toml (MODAL_CONFIG_PATH moves that file). Freefield pins its own with
FREEFIELD_MODAL_PROFILE, in the environment or in .env, so a deploy, a download or a lab run
cannot land in another workspace by accident. Only section names are read, never tokens.
No Modal import here: tools/doctor.py and tools/setup_token.py use it too.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def active_profile() -> str | None:
    """The profile Modal will use, or None when explicit tokens (MODAL_TOKEN_ID) override profiles."""
    if os.environ.get("MODAL_TOKEN_ID"):
        return None
    if os.environ.get("MODAL_PROFILE"):
        return os.environ["MODAL_PROFILE"].strip()
    path = Path(os.environ.get("MODAL_CONFIG_PATH") or Path.home() / ".modal.toml")
    if not path.exists():
        return None
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        header = re.match(r"""^\[\s*["']?([^"'\]]+?)["']?\s*\]$""", line)
        if header:
            section = header[1]
        elif section and re.match(r"^active\s*=\s*true$", line, flags=re.I):
            return section
    return "default"   # Modal's own fallback when no section is marked active


def pinned_profile(root: Path = ROOT) -> str | None:
    """FREEFIELD_MODAL_PROFILE from the environment, else from .env; None when not set."""
    value = os.environ.get("FREEFIELD_MODAL_PROFILE", "").strip()
    if not value and (root / ".env").exists():
        m = re.search(r"^\s*FREEFIELD_MODAL_PROFILE\s*=\s*(\S+)\s*$", (root / ".env").read_text(encoding="utf-8"), flags=re.M)
        value = m[1].strip("\"'") if m else ""
    return value or None


def check(root: Path = ROOT) -> tuple[str | None, str | None, bool]:
    """(active, pinned, ok). ok is False only when both are known and differ."""
    active, pinned = active_profile(), pinned_profile(root)
    return active, pinned, pinned is None or active is None or active == pinned


def enforce(root: Path = ROOT) -> None:
    """Stop before Modal creates anything in the wrong workspace; otherwise say where things go."""
    active, pinned, ok = check(root)
    if not ok:
        raise SystemExit(f'Modal profile "{active}" is active, but this repo is pinned to "{pinned}" '
                         f"(FREEFIELD_MODAL_PROFILE). Switch with:  modal profile activate {pinned}")
    where = active if active else "chosen by MODAL_TOKEN_ID"
    hint = "" if pinned else "   (pin it with FREEFIELD_MODAL_PROFILE=<profile> in .env)"
    print(f"Modal profile: {where}{hint}", file=sys.stderr)

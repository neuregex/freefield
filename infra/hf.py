"""Hugging Face access, shared by the downloader (tools/local_backend.py), the pod (infra/pod.py) and the gateway.

Which token, in this order:
  1. one pasted in the studio's Models panel, kept in FREEFIELD_HF_TOKEN_FILE (mode 600; the pod keeps it in its volume)
  2. HF_TOKEN from the environment (a RunPod secret, Vast's account variables, `docker run -e HF_TOKEN`)
  3. the one `hf auth login` saved on this machine
Pasting one in the studio is the latest thing the owner did, so it wins; "Forget" in the panel goes back to the others.

Only the standard library, so the pod can use it before anything else is up, and no answer from Hugging Face blocks
for long: every call has a timeout and says "unknown" when there is no answer.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
SITE = "https://huggingface.co"          # links for people always go to the real site, even with a mirror endpoint
TOKENS_PAGE = f"{SITE}/settings/tokens"


def license_page(repo: str) -> str:
    return f"{SITE}/{repo}"


def token_file() -> Path | None:
    p = os.environ.get("FREEFIELD_HF_TOKEN_FILE", "").strip()
    return Path(p) if p else None


def unresolved(value: str) -> bool:
    """A template placeholder the host did not fill in: RunPod passes `{{ RUNPOD_SECRET_hf_token }}` as it is when the
    account has no secret by that name."""
    return "{{" in value or "RUNPOD_SECRET" in value


def looks_like_token(value: str) -> bool:
    return value.startswith("hf_") and len(value) >= 30 and value.isascii() and value.isprintable() and " " not in value


def _login_file() -> Path:
    try:
        from huggingface_hub import constants
        return Path(constants.HF_TOKEN_PATH)
    except Exception:  # an older huggingface_hub, or none at all
        return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "token"


def _read(path: Path | None) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() if path and path.is_file() else ""
    except OSError:
        return ""


def token() -> tuple[str, str]:
    """(token, where it came from: "studio", "env" or "login"), or ("", "") when there is none."""
    saved = _read(token_file())
    if saved:
        return saved, "studio"
    env = os.environ.get("HF_TOKEN", "").strip()   # a pasted token often brings a space or a newline along
    if env and not unresolved(env):
        return env, "env"
    login = _read(_login_file())
    return (login, "login") if login else ("", "")


def env_problem() -> str | None:
    """What is wrong with HF_TOKEN as the host set it, in one line for the log, or None."""
    env = os.environ.get("HF_TOKEN", "").strip()
    if not env:
        return None
    if unresolved(env):
        return ("HF_TOKEN is the RunPod template's placeholder: this account has no secret named hf_token yet. A token "
                "pasted in the studio's Models panel works too, and the secret saves pasting it on the next pods")
    if not looks_like_token(env):
        return (f"HF_TOKEN does not look like a Hugging Face token ({len(env)} characters; a read token is hf_ and about "
                f"34 more): copy it again from {TOKENS_PAGE}, or paste it in the studio's Models panel")
    return None


def save(value: str) -> None:
    f = token_file()
    if not f:
        raise RuntimeError("FREEFIELD_HF_TOKEN_FILE is not set")
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(value.strip() + "\n")
    try:
        f.chmod(0o600)   # an older file keeps its old mode through O_TRUNC
    except OSError:
        pass


def forget() -> bool:
    f = token_file()
    if f and f.exists():
        f.unlink()
        return True
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):   # a 302 to the CDN already says the file can be read
        return None


def _ask(url: str, tok: str, method: str = "GET", timeout: float = 15) -> tuple[int, bytes]:
    headers = {"User-Agent": "freefield"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.status, (r.read() if method == "GET" else b"")
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, b""


def whoami(tok: str) -> tuple[str, str]:
    """("ok", account name), ("bad", "") when Hugging Face refuses the token, ("unknown", "") without an answer."""
    code, body = _ask(f"{ENDPOINT}/api/whoami-v2", tok)
    if code == 200:
        try:
            return "ok", str(json.loads(body).get("name") or "?")
        except ValueError:
            return "ok", "?"
    return ("bad", "") if code == 401 else ("unknown", "")


def access(repo: str, file: str, tok: str) -> str:
    """Can this token read the file? "ok"; "token" (no token, or one Hugging Face does not take); "license" (the
    account has not accepted the repo's license, or the token is fine-grained without access to gated repos);
    "missing" (the file is gone upstream); "unknown" (no answer)."""
    code, _ = _ask(f"{ENDPOINT}/{repo}/resolve/main/{urllib.parse.quote(file)}", tok, "HEAD")
    if 200 <= code < 400:
        return "ok"
    return {401: "token", 403: "license", 404: "missing"}.get(code, "unknown")

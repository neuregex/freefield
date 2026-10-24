"""Freefield's web UI on Modal: a private link that anyone with the passcode can use (the judges' "live link").

    python tools/setup_demo.py            # once: a passcode → Modal secret "freefield-demo" and .env
    modal deploy infra/modal_app.py       # the GPU backend, if it is not deployed yet
    modal deploy infra/web_app.py         # this: the web UI, CPU only, scales to zero
    python tools/setup_demo.py --link     # the link to share: https://<workspace>--freefield-demo.modal.run/?key=…

It is the same `npm run serve` as on your machine, with server/guard.ts switched on: every page and API call needs
the passcode (the link sets it as a cookie), runs are capped per UTC day (FREEFIELD_MAX_RUNS_PER_DAY, default 30)
and at the same time (FREEFIELD_MAX_ACTIVE, default 2), lab marks are read-only and uploads stop at 100 MB. The
limits are read from your environment when you deploy:

    FREEFIELD_MAX_RUNS_PER_DAY=15 modal deploy infra/web_app.py
    (PowerShell: $env:FREEFIELD_MAX_RUNS_PER_DAY = "15"; modal deploy infra/web_app.py)

It talks to the backend of the "freefield" app (function serve) with the gateway token of the "freefield" secret.
History and the run count live in the "freefield-web" volume, so they survive the container going to sleep.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
if modal.is_local():   # the same guard as infra/modal_app.py: never deploy into another Modal workspace
    sys.path.insert(0, str(ROOT))
    from infra.modal_profile import enforce
    enforce(ROOT)
LIMITS = {
    "FREEFIELD_MAX_RUNS_PER_DAY": os.environ.get("FREEFIELD_MAX_RUNS_PER_DAY", "30"),
    "FREEFIELD_MAX_ACTIVE": os.environ.get("FREEFIELD_MAX_ACTIVE", "2"),
}
BACKEND_URL = os.environ.get("FREEFIELD_BACKEND_URL", "")   # empty: look up the deployed "freefield" app

app = modal.App("freefield-web")
web_volume = modal.Volume.from_name("freefield-web", create_if_missing=True)
image = (
    modal.Image.from_registry("node:22.12.0-bookworm-slim", add_python="3.12")
    .add_local_file(ROOT / "package.json", "/freefield/package.json", copy=True)
    .add_local_file(ROOT / "package-lock.json", "/freefield/package-lock.json", copy=True)
    .run_commands("cd /freefield && npm ci --omit=dev --no-audit --no-fund")
    # code last, so editing it does not reinstall the packages
    .add_local_dir(ROOT / "server", "/freefield/server")
    .add_local_dir(ROOT / "web", "/freefield/web")
    .add_local_dir(ROOT / "apps", "/freefield/apps")
    .add_local_dir(ROOT / "schema", "/freefield/schema")
    .add_local_file(ROOT / "docs" / "vram-map.json", "/freefield/docs/vram-map.json")
)
if (ROOT / "lab" / "flags.json").exists():   # the lab's "mediocre" marks, shown read-only
    image = image.add_local_file(ROOT / "lab" / "flags.json", "/freefield/lab/flags.json")


def keep_committing(every: float = 20.0) -> None:
    """History files and the run count reach the volume even if the container stops without warning."""
    while True:
        time.sleep(every)
        try:
            web_volume.commit()
        except Exception as e:  # noqa: BLE001 - a missed commit is retried on the next turn
            print(f"volume commit failed: {e}")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("freefield"),        # FREEFIELD_TOKEN, the gateway's bearer token
             modal.Secret.from_name("freefield-demo"),   # FREEFIELD_PASSCODE, from tools/setup_demo.py
             modal.Secret.from_dict({**LIMITS, "BACKEND_URL": BACKEND_URL})],
    volumes={"/data": web_volume},
    cpu=1.0,
    memory=1024,
    max_containers=1,          # one history and one run count
    scaledown_window=900,
    timeout=24 * 3600,
)
@modal.concurrent(max_inputs=100)
@modal.web_server(3000, startup_timeout=120, label="freefield-demo")
def web():
    if not os.environ.get("FREEFIELD_PASSCODE"):
        raise RuntimeError('the Modal secret "freefield-demo" has no FREEFIELD_PASSCODE: run python tools/setup_demo.py')
    backend = os.environ.get("BACKEND_URL") or modal.Function.from_name("freefield", "serve").get_web_url()
    env = {**os.environ, "COMFY_BASE_URL": backend, "FREEFIELD_OUT": "/data/out", "FREEFIELD_HOST": "0.0.0.0",
           "PORT": "3000"}
    subprocess.Popen(["node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", "server/server.ts"],
                     cwd="/freefield", env=env)
    threading.Thread(target=keep_committing, daemon=True).start()

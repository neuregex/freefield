"""LoRA lab on Modal: launch a batch of cases, then download the results for review.

    modal run lab/lab_modal.py                                   # every case in lab/cases.json, on an L40S
    FREEFIELD_GPU=A10G modal run lab/lab_modal.py --only ic-clean-plate,ic-day-to-night   # 24 GB parity check
    modal run lab/lab_modal.py --apps camera-moves,relight       # every case of these apps
    modal volume get freefield-lab <run_id> lab/results/<run_id>
    python lab/review.py lab/results/<run_id>                    # opens a gallery to rate each result

Missing model files are downloaded into the "freefield-models" volume first (gated repos
need the "huggingface" secret and an accepted license). Results and a results.jsonl with
time and peak VRAM per case are written to the "freefield-lab" volume as they finish, so a
partial run is still useful.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from infra.common import build_image, ensure_models, hf_secret, lab_volume, models_volume, start_comfyui  # noqa: E402

GPU = os.environ.get("FREEFIELD_GPU", "L40S")
COMFY_ARGS = os.environ.get("FREEFIELD_COMFY_ARGS", "")

app = modal.App("freefield-lab")
image = build_image().add_local_python_source("infra")


@app.function(image=image, gpu=GPU, volumes={"/models": models_volume, "/lab": lab_volume},
              secrets=[hf_secret], timeout=8 * 3600)
def run(cases: list[dict], run_id: str, assets: dict[str, bytes]) -> list[dict]:
    sys.path.insert(0, "/freefield/lab")
    from core import Lab, models_for_cases  # noqa: E402

    needed = models_for_cases(cases, Path("/freefield/apps"))
    fetched, failed = ensure_models(needed)
    if fetched:
        models_volume.commit()
    if failed:
        print(f"{len(failed)} model file(s) missing; the cases that need them will be skipped")
    assets_dir = Path("/tmp/lab-assets")
    assets_dir.mkdir(exist_ok=True)
    for name, data in assets.items():
        (assets_dir / name).write_bytes(data)
    proc = start_comfyui(8188, COMFY_ARGS)
    try:
        lab = Lab("http://127.0.0.1:8188", Path("/comfyui/input"), Path("/comfyui/output"), Path("/lab") / run_id,
                  apps_dir=Path("/freefield/apps"), assets_dir=assets_dir, on_case_done=lab_volume.commit,
                  missing=failed)
        results = lab.run_all(cases)
    finally:
        proc.terminate()
    lab_volume.commit()
    return results


def with_dependencies(spec: list[dict], keep: set[str]) -> list[dict]:
    """The chosen cases plus every case they read an output from (transitively), in file order."""
    by_id = {c["id"]: c for c in spec}
    todo, seen = list(keep), set()
    while todo:
        cid = todo.pop()
        if cid in seen or cid not in by_id:
            continue
        seen.add(cid)
        todo += [v[len("@case:"):] for v in by_id[cid].get("values", {}).values()
                 if isinstance(v, str) and v.startswith("@case:")]
    return [c for c in spec if c["id"] in seen]


@app.local_entrypoint()
def main(cases: str = "lab/cases.json", only: str = "", apps: str = "", run_id: str = ""):
    """--only case,ids  or  --apps app,ids  (their reference cases come along)."""
    spec = json.loads(Path(cases).read_text(encoding="utf-8"))["cases"]
    keep = set(filter(None, only.split(","))) | {c["id"] for c in spec if c["app"] in set(filter(None, apps.split(",")))}
    if only or apps:
        unknown = set(filter(None, only.split(","))) - {c["id"] for c in spec}
        if unknown:
            raise SystemExit(f"unknown case id(s): {', '.join(sorted(unknown))}")
        spec = with_dependencies(spec, keep)
        if not spec:
            raise SystemExit("no case matches --only/--apps")
    assets = {}
    for c in spec:
        for v in c.get("values", {}).values():
            if isinstance(v, str) and v.startswith("asset:"):
                name = v[len("asset:"):]
                assets[name] = (Path("lab/assets") / name).read_bytes()
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + f"-{GPU.lower()}"
    print(f"run {run_id}: {len(spec)} cases on {GPU}")
    results = run.remote(spec, run_id, assets)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"\n{ok}/{len(results)} ok")
    print(f"download:  modal volume get freefield-lab {run_id} lab/results/{run_id}")
    print(f"review:    python lab/review.py lab/results/{run_id}")

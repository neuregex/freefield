"""LoRA lab on Modal: launch a batch of cases, download the results, review and publish them.

    modal run lab/lab_modal.py --showcase                        # one example per app (+ the references they need)
    modal run lab/lab_modal.py                                   # every case in lab/cases.json, on an L40S
    modal run lab/lab_modal.py --apps camera-moves,relight       # every case of these apps
    FREEFIELD_GPU=A10G modal run lab/lab_modal.py --only ic-clean-plate,ic-day-to-night   # 24 GB parity check
    modal run lab/lab_modal.py --pull <run_id>                   # copy back and publish a run that finished without you

Missing model files are downloaded first on a CPU container (no GPU billed while they
arrive) into the "freefield-models" volume; gated repos need the "huggingface" secret and an
accepted license. Results, a results.jsonl with time and peak VRAM per case, and small web
versions of every output go to the "freefield-lab" volume as each case finishes, so a partial
run is still useful. At the end the run is copied to lab/results/<run_id>, review.html is
built there, and the examples the web UI shows are refreshed (--no-publish to skip).
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


@app.function(image=image, volumes={"/models": models_volume}, secrets=[hf_secret], timeout=4 * 3600, cpu=4, memory=8192)
def fetch(models: list[dict]) -> dict[str, str]:
    """Download the models a run needs, on CPU. Returns {file: reason} for those that failed."""
    fetched, failed = ensure_models(models)
    if fetched:
        models_volume.commit()
    return failed


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


def download_run(run_id: str, dest: Path) -> int:
    """Copy /<run_id> from the lab volume to dest; files already there with the same size are kept."""
    n = 0
    for entry in lab_volume.iterdir(f"/{run_id}", recursive=True):
        if int(entry.type) != 1:   # 1 = file
            continue
        rel = entry.path.lstrip("/")
        rel = rel[len(run_id) + 1:] if rel.startswith(run_id + "/") else rel
        target = dest / rel
        if target.exists() and target.stat().st_size == entry.size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            for chunk in lab_volume.read_file(entry.path):
                f.write(chunk)
        n += 1
    return n


def finish(run_id: str, publish: bool) -> None:
    """Copy the run to lab/results/<run_id>, build review.html there and publish the examples."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    dest = Path("lab/results") / run_id
    print(f"downloading the run to {dest} ...")
    print(f"  {download_run(run_id, dest)} new files")
    import review  # lab/review.py
    review.main([str(dest)])
    print(f"review:    {dest / 'review.html'}")
    if publish:
        import publish as publisher  # lab/publish.py
        publisher.main([str(dest)])


@app.local_entrypoint()
def main(cases: str = "lab/cases.json", only: str = "", apps: str = "", showcase: bool = False,
         run_id: str = "", publish: bool = True, pull: str = ""):
    """--showcase (one case per app), --only case,ids or --apps app,ids; their reference cases come along.
    --pull <run_id> only copies an earlier run back (say, after the terminal closed) and publishes it."""
    if pull:
        finish(pull, publish)
        return
    spec = json.loads(Path(cases).read_text(encoding="utf-8"))["cases"]
    keep = set(filter(None, only.split(","))) | {c["id"] for c in spec if c["app"] in set(filter(None, apps.split(",")))}
    if showcase:
        keep |= {c["id"] for c in spec if c.get("showcase")}
    if only or apps or showcase:
        unknown = set(filter(None, only.split(","))) - {c["id"] for c in spec}
        if unknown:
            raise SystemExit(f"unknown case id(s): {', '.join(sorted(unknown))}")
        spec = with_dependencies(spec, keep)
        if not spec:
            raise SystemExit("no case matches --only/--apps/--showcase")
    assets = {}
    for c in spec:
        for v in c.get("values", {}).values():
            if isinstance(v, str) and v.startswith("asset:"):
                name = v[len("asset:"):]
                assets[name] = (Path("lab/assets") / name).read_bytes()
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + f"-{GPU.lower()}"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import core  # lab/core.py: which models these cases load
    needed = core.models_for_cases(spec, Path(__file__).resolve().parent.parent / "apps")
    print(f"run {run_id}: {len(spec)} cases; making sure {len(needed)} model files are in the volume (CPU)")
    failed = fetch.remote(needed)
    if failed:
        print(f"{len(failed)} file(s) could not be downloaded; the cases that need them will be skipped:")
        for name, reason in failed.items():
            print(f"  {name}: {reason}")
    print(f"running on {GPU}")
    results = run.remote(spec, run_id, assets)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"\n{ok}/{len(results)} ok")
    finish(run_id, publish)

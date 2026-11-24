"""Lite versions on Modal: make the w4a8 copies, then measure every base model at four card sizes (lite/README.md).

    modal run --detach lab/lite_modal.py                       # both steps; the results come back here if you stay
    modal run lab/lite_modal.py --step quantize                 # only the copies of lite/quantize.json, into the volume
    modal run lab/lite_modal.py --step measure                  # only the measurements of lite/measure.json
    modal run lab/lite_modal.py --step pull --run-id <run_id>   # copy back a run that finished without you

Quantizing: the bf16 sources are downloaded on a CPU container into the volume's .sources folder; then one L40S per
file runs tools/quantize.py and writes the copy where ComfyUI looks for it (diffusion_models/, text_encoders/),
with its report in .lite-reports/; the source is deleted after. A copy already in the volume is not made again.

Measuring: one L40S per card size runs ComfyUI as if the card had that much memory. --reserve-vram leaves ComfyUI
the card's budget, a PyTorch cap (torch.cuda.set_per_process_memory_fraction, from a one-file custom node) makes any
allocation past it fail as it would on the card, and --disable-dynamic-vram keeps ComfyUI's own word for what it
had to keep in RAM ("loaded partially"). Each case of lite/measure.json runs in its full and its lite version
(lite/variants.json, plus the copies made above); the inputs it reads are made first, at full size, and are not
measured. Results go to the "freefield-lab" volume as each case ends; at the end they are copied to
lab/results/<run_id>, with review.html, and lab/review.py --tiers writes docs/vram-measured.json from them.

Cost, at Modal's L40S rate: about 15 minutes of GPU per copy, and up to 2.5 hours per card size (cases are capped at
lite/measure.json's case_timeout_s); a container that reaches its limit keeps what it measured.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # lab/core.py and lab/lab_modal.py's helpers
from infra.common import (MODELS_DIR, build_image, ensure_models, hf_secret, lab_volume, models_volume,  # noqa: E402
                          start_comfyui)

GPU = os.environ.get("FREEFIELD_GPU", "L40S")
ROOT = Path(__file__).resolve().parent.parent
app = modal.App("freefield-lite")
image = build_image().add_local_python_source("infra")
REPORTS = f"{MODELS_DIR}/.lite-reports"
CONTEXT_GB = 0.45     # what a CUDA context takes on any card, outside PyTorch's allocator
SMOKE_CASE = "ref-face-a"   # Z-Image Turbo, full and lite: a minute, before the long runs
COMFY_RESERVE_GB = 0.4   # ComfyUI's own default reserve on Linux


# ---------------------------------------------------------------- quantize
@app.function(image=image, volumes={"/models": models_volume}, secrets=[hf_secret], timeout=4 * 3600, cpu=4, memory=8192)
def fetch(models: list[dict]) -> dict[str, str]:
    """Download what is missing, on CPU (no GPU billed while it arrives). Returns {file: reason} for failures."""
    fetched, failed = ensure_models(models)
    if fetched:
        models_volume.commit()
    return failed


@app.function(image=image, gpu=GPU, volumes={"/models": models_volume}, timeout=2 * 3600, memory=49152)
def quantize(target: dict) -> dict:
    sys.path.insert(0, "/freefield/tools")
    import quantize as q  # tools/quantize.py

    out = Path(MODELS_DIR) / target["dir"] / target["name"]
    report_path = Path(REPORTS) / f"{target['name']}.json"
    if out.exists() and report_path.exists():
        return {**json.loads(report_path.read_text()), "skipped": "already in the volume"}
    src = Path(MODELS_DIR) / ".sources" / target["source"]["file"].rsplit("/", 1)[-1]
    ref = Path(MODELS_DIR) / target["ref"]["dir"] / target["ref"]["file"].rsplit("/", 1)[-1]
    for p in (src, ref):
        if not p.exists():
            return {"output": target["name"], "error": f"{p} is not in the volume"}
    report = q.quantize_file(str(src), str(ref), str(out))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    src.unlink()   # the bf16 source is 2-4 times the copy and nothing loads it; downloading it again is cheap
    if target["ref"]["dir"] == ".sources":
        ref.unlink()
    models_volume.commit()
    return report


def quantize_all(only: list[str]) -> list[dict]:
    spec = json.loads((ROOT / "lite" / "quantize.json").read_text(encoding="utf-8"))["files"]
    targets = [t for t in spec if not only or any(o in t["name"] for o in only)]
    need = [{**t["source"], "dir": ".sources"} for t in targets] + [{**t["ref"]} for t in targets]
    print(f"quantize: {len(targets)} files; downloading the sources and references that are missing (CPU) ...")
    failed = fetch.remote(need)
    for name, reason in failed.items():
        print(f"  ✗ {name}: {reason}")
    reports = []
    for t, r in zip(targets, quantize.map(targets, return_exceptions=True)):
        if isinstance(r, Exception):
            r = {"output": t["name"], "error": f"{type(r).__name__}: {r}"}
        reports.append(r)
        if r.get("error"):
            print(f"  ✗ {t['name']}: {r['error']}")
        else:
            e = r.get("relative_error", {})
            print(f"  ✓ {t['name']}: {r.get('gb_in')} → {r.get('gb_out')} GB, weight error mean {e.get('mean')} max {e.get('max')}"
                  + (f" ({r['skipped']})" if r.get("skipped") else ""))
    return reports


# ---------------------------------------------------------------- measure
CAP_NODE = '''"""Freefield lab: cap PyTorch's memory on this GPU to FREEFIELD_VRAM_CAP_GB, as if the card had that much."""
import os
import torch
NODE_CLASS_MAPPINGS = {}
_cap = float(os.environ.get("FREEFIELD_VRAM_CAP_GB") or 0)
if _cap and torch.cuda.is_available():
    _total = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
    torch.cuda.set_per_process_memory_fraction(min(1.0, _cap / _total), 0)
    print(f"[freefield] PyTorch memory capped to {_cap:.2f} of {_total:.2f} GiB")
'''


def gpu_total_gib() -> float:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout
    return int(out.split()[0]) / 1024


@app.function(image=image, gpu=GPU, volumes={"/models": models_volume, "/lab": lab_volume},
              secrets=[hf_secret], timeout=int(2.5 * 3600), memory=81920)
def measure(cases: list[dict], run_id: str, assets: dict[str, bytes], tier: int, missing: dict[str, str]) -> list[dict]:
    sys.path.insert(0, "/freefield/lab")
    from core import Lab  # noqa: E402

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    assets_dir = Path("/tmp/lab-assets")
    assets_dir.mkdir(exist_ok=True)
    for name, data in assets.items():
        (assets_dir / name).write_bytes(data)
    lab = Lab("http://127.0.0.1:8188", Path("/comfyui/input"), Path("/comfyui/output"), Path("/lab") / run_id,
              apps_dir=Path("/freefield/apps"), assets_dir=assets_dir, on_case_done=lab_volume.commit, missing=missing)
    inputs = [c for c in cases if not c.get("measure")]
    measured = [c for c in cases if c.get("measure")]
    results = []
    if inputs:   # the files the measured cases read, at full size
        proc = start_comfyui(8188)
        try:
            results += lab.run_all(inputs, last=False)
        finally:
            proc.terminate()
            proc.wait(timeout=60)
    # ComfyUI as if the card had `tier` GB, started anew for every measured case: in one process, the models of the
    # case before stay in VRAM or in pinned RAM (/free is only a flag ComfyUI reads between prompts), and a run that
    # follows another measures both (the first lite run, 2026-11-23, used more RAM than the full one it followed)
    total = gpu_total_gib()
    card = tier - 0.1                                  # a "16 GB" card reports a little under 16 GiB
    reserve = total - card + COMFY_RESERVE_GB          # ComfyUI plans with the card's memory, less its usual reserve
    cap = card - CONTEXT_GB                            # PyTorch may use the card's memory, less the CUDA context
    Path("/comfyui/custom_nodes/freefield_vram_cap.py").write_text(CAP_NODE)
    log = Path(f"/tmp/comfyui-{tier}.log")
    print(f"card size {tier} GB on a {total:.1f} GiB GPU: --reserve-vram {reserve:.2f}, PyTorch cap {cap:.2f} GiB")
    for case in measured:
        proc = start_comfyui(8188, f"--disable-dynamic-vram --reserve-vram {reserve:.2f}",
                             env={"FREEFIELD_VRAM_CAP_GB": f"{cap:.2f}"}, log_path=log)
        lab.attach(proc.pid, log)
        lab.last_key = None                            # nothing loaded yet: nothing to unload
        try:
            results += lab.run_all([{**case, "own_comfyui": True}], last=False)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)
    lab.vram.stop()
    lab.ram.stop()
    # run_all wrote run.json for its last case alone: the whole container's run, for merge_shards
    (lab.results_dir / "run.json").write_text(json.dumps({"gpu": lab.vram.gpu_name, "started": started,
                                                         "cases": len(results)}, indent=2), encoding="utf-8")
    lab_volume.commit()
    return results


def measure_cases(spec_path: Path) -> tuple[list[dict], list[int], int]:
    """lite/measure.json → every case to run in one container (inputs first, then full and lite per case)."""
    import core  # lab/core.py
    from lab_modal import with_dependencies   # lab/lab_modal.py
    conf = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in spec}
    unknown = [c for c in conf["cases"] if c not in by_id]
    if unknown:
        raise SystemExit(f"lite/measure.json names cases lab/cases.json does not have: {', '.join(unknown)}")
    read = {src for cid in conf["cases"] for src in core.reads(by_id[cid])}
    inputs = with_dependencies(spec, read) if read else []   # what the measured cases read, and what that reads
    copies = core.lite_copies()
    measured = []
    for cid in conf["cases"]:
        c = by_id[cid]
        manifest = json.loads((ROOT / "apps" / c["app"] / "app.json").read_text(encoding="utf-8"))
        has_lite = any(m["file"].rsplit("/", 1)[-1] in copies for m in manifest.get("models", []) if not m.get("optional"))
        for variant in ["full", "lite"] if has_lite else ["full"]:
            measured.append({**c, "id": f"{cid}@{variant}", "case": cid, "variant": variant, "measure": True,
                             "timeout": conf.get("case_timeout_s", 1200), "showcase": False})
    return inputs + measured, conf["tiers"], len(measured)


def measure_all(run_id: str) -> str:
    import core  # lab/core.py
    cases, tiers, n = measure_cases(ROOT / "lite" / "measure.json")
    assets = {}
    for c in cases:
        for v in c.get("values", {}).values():
            if isinstance(v, str) and v.startswith("asset:"):
                name = v[len("asset:"):]
                assets[name] = (ROOT / "lab" / "assets" / name).read_bytes()
    needed = core.models_for_cases(cases, ROOT / "apps")
    print(f"measure {run_id}: {n} measured runs (full and lite) at {tiers} GB, "
          f"{len(cases) - n} inputs; making sure {len(needed)} model files are in the volume (CPU)")
    missing = fetch.remote(needed)
    for name, reason in missing.items():
        print(f"  ✗ {name}: {reason} (the cases that load it are skipped)")
    # a few minutes first: the smallest case, both versions, at the smallest card size, before four GPUs for hours
    smoke = [{**c, "id": f"{c['id']}@{tiers[0]}", "tier": tiers[0]} for c in cases
             if c.get("measure") and c["case"] == SMOKE_CASE]   # it reads no other case's output
    print(f"smoke test: {SMOKE_CASE} at {tiers[0]} GB ...")
    got = measure.remote(smoke, f"{run_id}-smoke", assets, tiers[0], missing)
    bad = [r for r in got if r.get("measure") and (r["status"] != "ok" or r.get("offloaded") is None or not r.get("peak_ram_gb"))]
    for r in got:
        print(f"  {r['id']}: {r['status']} {r.get('seconds')}s, VRAM {r.get('peak_vram_gb')} GB, RAM {r.get('peak_ram_gb')} GB, "
              f"offloaded {r.get('offloaded')} {r.get('error') or ''}")
    if bad or not got:
        raise SystemExit("the smoke test did not measure what it should: nothing else was started")
    calls = []
    for tier in tiers:
        tier_cases = [{**c, "id": f"{c['id']}@{tier}", "tier": tier} if c.get("measure") else c for c in cases]
        calls.append((tier, measure.spawn(tier_cases, f"{run_id}-t{tier}", assets, tier, missing)))
        print(f"  {run_id}-t{tier}: started on {GPU}")
    for tier, call in calls:
        try:
            part = call.get()
            ok = sum(r["status"] == "ok" for r in part if r.get("measure"))
            print(f"  {tier} GB: {ok}/{sum(1 for r in part if r.get('measure'))} measured runs finished")
        except Exception as e:   # time limit, or the container died: what it measured is on the volume
            print(f"  {tier} GB stopped: {type(e).__name__}: {e}")
    return run_id


def pull(run_id: str) -> None:
    """lab/results/<run_id>: every card size side by side, review.html, and docs/vram-measured.json."""
    from lab_modal import merge_shards   # lab/lab_modal.py
    import review                         # lab/review.py
    parts = sorted({e.path.strip("/").rsplit("/", 1)[-1] for e in lab_volume.listdir("/")
                    if e.path.strip("/").rsplit("/", 1)[-1].startswith(f"{run_id}-t")})
    if not parts:
        raise SystemExit(f"nothing on the lab volume for {run_id}")
    dest = ROOT / "lab" / "results" / run_id
    print(f"downloading {', '.join(parts)} to {dest} ...")
    merge_shards(parts, dest)
    review.main([str(dest), "--tiers"])


@app.local_entrypoint()
def main(step: str = "all", only: str = "", run_id: str = ""):
    """--step all | quantize | measure | pull. --only names (a piece of) the files to quantize."""
    if step == "pull":
        if not run_id:
            raise SystemExit("--step pull needs --run-id")
        pull(run_id)
        return
    if step in ("all", "quantize"):
        reports = quantize_all(list(filter(None, only.split(","))))
        out = ROOT / "lab" / "results" / "quantize"
        out.mkdir(parents=True, exist_ok=True)
        for r in reports:
            (out / f"{r['output']}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        print(f"reports: {out}")
        if any(r.get("error") for r in reports) and step == "all":
            raise SystemExit("some copies failed: fix them before measuring (the measurements would miss them)")
    if step in ("all", "measure"):
        run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-lite"
        measure_all(run_id)
        pull(run_id)

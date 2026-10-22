"""LoRA lab on Modal: launch a batch of cases, download the results, review and publish them.

    modal run lab/lab_modal.py --showcase                        # one example per app (+ the references they need)
    modal run lab/lab_modal.py                                   # every case in lab/cases.json, on an L40S
    modal run lab/lab_modal.py --apps camera-moves,relight       # every case of these apps
    FREEFIELD_GPU=A10G modal run lab/lab_modal.py --only ic-clean-plate,ic-day-to-night   # 24 GB parity check
    modal run lab/lab_modal.py --apps effects --shards 4         # the same cases split over 4 GPUs at once
    modal run lab/lab_modal.py --pull <run_id>                   # copy back and publish a run that finished without you

Missing model files are downloaded first on a CPU container (no GPU billed while they
arrive) into the "freefield-models" volume; gated repos need the "huggingface" secret and an
accepted license. Results, a results.jsonl with time and peak VRAM per case, and small web
versions of every output go to the "freefield-lab" volume as each case finishes, so a partial
run is still useful. At the end the run is copied to lab/results/<run_id>, review.html is
built there, and the examples the web UI shows are refreshed (--no-publish to skip).

--shards N runs the cases on N GPU containers at the same time. Cases that read the same
reference stay in one group, so every reference is still made once; each group writes to
<run_id>-s1, -s2, … on the volume, and they come back merged into lab/results/<run_id>. The
GPU time is about the same as one container (plus loading the models once per container);
the wait is about 1/N.
"""
from __future__ import annotations

import json
import os
import re
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


def split_cases(spec: list[dict], keep: set[str], n: int) -> list[list[dict]]:
    """The chosen cases in at most n groups that can run at the same time, each with the cases it reads.

    Chosen cases that read the same reference (directly or through another case) stay in one group,
    so a reference is never made twice; groups are balanced by how many chosen cases they hold."""
    by_id = {c["id"]: c for c in spec}

    def sources(cid: str) -> set[str]:
        out, todo = set(), [cid]
        while todo:
            for v in by_id[todo.pop()].get("values", {}).values():
                src = v[len("@case:"):] if isinstance(v, str) and v.startswith("@case:") else None
                if src in by_id and src not in out:
                    out.add(src)
                    todo.append(src)
        return out

    blocks: list[tuple[set[str], list[str]]] = []   # (every case the block touches, its chosen cases)
    for c in spec:
        if c["id"] not in keep:
            continue
        touch, chosen = {c["id"]} | sources(c["id"]), [c["id"]]
        for b in [b for b in blocks if b[0] & touch]:
            blocks.remove(b)
            touch, chosen = touch | b[0], b[1] + chosen
        blocks.append((touch, chosen))
    bins: list[list[str]] = [[] for _ in range(max(1, min(n, len(blocks))))]
    for _, chosen in sorted(blocks, key=lambda b: -len(b[1])):
        min(bins, key=len).extend(chosen)
    return [with_dependencies(spec, set(b)) for b in bins if b]


def shard_ids(run_id: str) -> list[str]:
    """The volume folders of a run split with --shards (<run_id>-s1, -s2, …); empty for a run in one piece."""
    found = []
    for entry in lab_volume.listdir("/"):
        name = entry.path.strip("/").rsplit("/", 1)[-1]
        m = re.fullmatch(re.escape(run_id) + r"-s(\d+)", name)
        if m:
            found.append((int(m.group(1)), name))
    return [name for _, name in sorted(found)]


def volume_text(path: str) -> str:
    try:
        return b"".join(lab_volume.read_file(path)).decode("utf-8")
    except Exception:   # not written yet: that shard has not started a case
        return ""


def merge_shards(parts: list[str], dest: Path) -> None:
    """Every shard's case folders side by side in dest, with one results.jsonl and one run.json for all."""
    lines, metas = [], []
    for sid in parts:
        print(f"  {sid}: {download_run(sid, dest, skip={'results.jsonl', 'run.json'})} new files")
        lines += [ln for ln in volume_text(f"/{sid}/results.jsonl").splitlines() if ln.strip()]
        try:
            metas.append(json.loads(volume_text(f"/{sid}/run.json") or "{}"))
        except json.JSONDecodeError:
            pass
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "results.jsonl").write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
    meta = {"gpu": next((m["gpu"] for m in metas if m.get("gpu")), None),
            "started": min((m["started"] for m in metas if m.get("started")), default=None),
            "cases": sum(m.get("cases", 0) for m in metas), "shards": parts}
    (dest / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def download_run(run_id: str, dest: Path, skip: set[str] | frozenset[str] = frozenset()) -> int:
    """Copy /<run_id> from the lab volume to dest, except the top-level files named in skip;
    files already there with the same size are kept."""
    n = 0
    for entry in lab_volume.iterdir(f"/{run_id}", recursive=True):
        if int(entry.type) != 1:   # 1 = file
            continue
        rel = entry.path.lstrip("/")
        rel = rel[len(run_id) + 1:] if rel.startswith(run_id + "/") else rel
        if rel in skip:
            continue
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
    """Copy the run (all its shards, if it was split) to lab/results/<run_id>, build review.html there and publish."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    dest = Path("lab/results") / run_id
    parts = shard_ids(run_id)
    if parts:
        print(f"downloading {len(parts)} shards of the run to {dest} ...")
        merge_shards(parts, dest)
    else:
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
         run_id: str = "", publish: bool = True, pull: str = "", shards: int = 1):
    """--showcase (one case per app), --only case,ids or --apps app,ids; their reference cases come along.
    --shards N splits them over N GPU containers that run at the same time.
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
    else:
        keep = {c["id"] for c in spec}
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
    if shards > 1:
        groups = split_cases(spec, keep, shards)
        ids = [f"{run_id}-s{k}" for k in range(1, len(groups) + 1)]
        print(f"running on {len(groups)} x {GPU} at once:")
        for sid, g in zip(ids, groups):
            print(f"  {sid}: {sum(c['id'] in keep for c in g)} cases + {sum(c['id'] not in keep for c in g)} references")
        calls = [run.spawn(g, sid, assets) for g, sid in zip(groups, ids)]
        results = []
        for sid, call in zip(ids, calls):
            try:
                part = call.get()
            except Exception as e:   # a container that died: the cases it finished are on the volume
                print(f"  {sid} stopped: {type(e).__name__}: {e}")
                continue
            print(f"  {sid}: {sum(r['status'] == 'ok' for r in part)}/{len(part)} ok")
            results += part
    else:
        print(f"running on {GPU}")
        results = run.remote(spec, run_id, assets)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"\n{ok}/{len(results)} ok")
    finish(run_id, publish)

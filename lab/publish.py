#!/usr/bin/env python3
"""Publish one example per app from a lab run into the web UI.

    python lab/publish.py lab/results/<run_id>

For every app it picks a case that succeeded (the one marked "showcase" in lab/cases.json if
it ran, otherwise the first one in file order) and copies that case's web versions into
web/examples/<app>/, plus small previews of the files the case was given (the reference images,
clips or songs made earlier in the run). web/examples/index.json lists them; the web UI uses it
for the app cards, the example shown with each app, and the gallery. Apps without a successful
case keep the example they had.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "web" / "examples"
HIDDEN = {"smoke", "smoke-invert"}


def read_results(run_dir: Path) -> dict[str, dict]:
    """Last result per case id (results.jsonl is appended to when a run id is reused)."""
    out: dict[str, dict] = {}
    path = run_dir / "results.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} not found; is {run_dir} a lab run folder?")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def copy_as(run_dir: Path, rel: str | None, dest: Path, stem: str) -> str | None:
    """Copy run_dir/rel to dest/<stem><ext>; returns the path the web UI uses, or None."""
    if not rel or not (run_dir / rel).exists():
        return None
    target = dest / f"{stem}{Path(rel).suffix.lower()}"
    shutil.copy(run_dir / rel, target)
    return target.relative_to(ROOT / "web").as_posix()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    a = ap.parse_args(argv)
    run_dir = a.run_dir.resolve()
    results = read_results(run_dir)
    order = [c["id"] for c in json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]]
    rank = {cid: i for i, cid in enumerate(order)}
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) if (run_dir / "run.json").exists() else {}

    index_path = EXAMPLES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"apps": {}}
    published, missing = [], []
    for manifest_path in sorted((ROOT / "apps").glob("*/app.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        app_id = manifest["id"]
        if app_id in HIDDEN:
            continue
        ok = [r for r in results.values() if r["app"] == app_id and r["status"] == "ok" and r.get("web")]
        if not ok:
            missing.append(app_id)
            continue
        pick = sorted(ok, key=lambda r: (not r.get("showcase"), rank.get(r["id"], 10**6)))[0]
        web = pick["web"]
        dest = EXAMPLES / app_id
        if dest.exists():
            shutil.rmtree(dest)   # only ever our own generated folder
        dest.mkdir(parents=True)
        full = copy_as(run_dir, web.get("full"), dest, "full")
        card = copy_as(run_dir, web.get("card"), dest, "card") or (full if web.get("type") == "image" else None)
        poster = copy_as(run_dir, web.get("poster"), dest, "poster")

        labels = {i["id"]: i for i in manifest.get("inputs", [])}
        inputs = []
        for input_id, raw in (pick.get("inputs") or {}).items():
            src = None
            if isinstance(raw, str) and raw.startswith("@case:"):
                source = results.get(raw[len("@case:"):])
                if source and source.get("web"):
                    w = source["web"]
                    # a still for images, the poster for clips, the waveform for audio, plus the playable file
                    src = copy_as(run_dir, w.get("card") if w.get("type") != "video" else w.get("poster"), dest, f"input-{input_id}")
                    playable = copy_as(run_dir, w.get("full"), dest, f"input-{input_id}-full") if w.get("type") in ("video", "audio") else None
                    inputs.append({"id": input_id, "label": labels.get(input_id, {}).get("label", input_id),
                                   "type": w.get("type"), "src": src, "full": playable, "from_case": source["id"]})
                    continue
            inputs.append({"id": input_id, "label": labels.get(input_id, {}).get("label", input_id),
                           "type": labels.get(input_id, {}).get("type"), "src": None, "full": None, "from": raw})

        shown = {k: v for k, v in (pick.get("values") or {}).items() if k != "seed"}
        index["apps"][app_id] = {
            "case": pick["id"], "type": web.get("type"), "card": card, "poster": poster, "full": full,
            "inputs": inputs, "values": shown, "seed": (pick.get("values") or {}).get("seed"),
            "seconds": pick.get("seconds"), "peak_vram_gb": pick.get("peak_vram_gb"),
            "gpu": meta.get("gpu"), "run": run_dir.name,
        }
        published.append(app_id)

    EXAMPLES.mkdir(parents=True, exist_ok=True)
    index["updated_from"] = run_dir.name
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"published {len(published)} app example(s) to {EXAMPLES.relative_to(ROOT)}")
    if missing:
        print(f"no successful case in this run for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

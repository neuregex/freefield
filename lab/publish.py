#!/usr/bin/env python3
"""Publish one example per app from a lab run into the web UI.

    python lab/publish.py lab/results/<run_id>
    python lab/publish.py lab/results/<run_id> --skip fx-crying,tpl-idol   # all but these cases

For every app it picks a case that succeeded (the one marked "showcase" in lab/cases.json if
it ran, otherwise the first one in file order) and copies that case's web versions into
web/examples/<app>/, plus small previews of the files the case was given (the reference images,
clips or songs made earlier in the run). web/examples/index.json lists them; the web UI uses it
for the app cards, the example shown with each app, and the gallery. Apps without a successful
case keep the example they had, and a run without the app's showcase case keeps a showcase
example published earlier. Cases with overrides or extra LoRAs (experiments) come last.

A select input marked "gallery" in app.json (the effects picker) also gets one example per
option, from the cases that chose it and run the app as shipped (no overrides, no extra LoRAs):
web/examples/<app>/options/<input>/<value>/ holds its card and poster. Options this run did not
cover keep what they had.

lab/flags.json holds the examples marked "mediocre" in the web UI (key "<app>" or
"<app>/<input>/<value>"); an example this run replaces loses its mark, since the new one has not
been looked at yet.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "web" / "examples"
FLAGS = ROOT / "lab" / "flags.json"
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


def experimental(r: dict) -> bool:
    """The case changed the app's workflow (overrides or extra LoRAs), so it shows a test, not the app as shipped."""
    return bool(r.get("overrides") or r.get("loras"))


def clear_main(dest: Path) -> None:
    """Empty the app's own example folder (only ever our generated files), keeping the per-option examples."""
    dest.mkdir(parents=True, exist_ok=True)
    for p in dest.iterdir():
        if p.name != "options":
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def slug(value) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-") or "x"


def unmark(keys: set[str]) -> int:
    """Drop the "mediocre" marks of the examples in keys from lab/flags.json; returns how many were dropped."""
    if not keys or not FLAGS.exists():
        return 0
    try:
        data = json.loads(FLAGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    marks = data.get("mediocre") if isinstance(data.get("mediocre"), dict) else {}
    gone = [k for k in marks if k in keys]
    for k in gone:
        del marks[k]
    if gone:
        data["mediocre"] = marks
        FLAGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(gone)


def publish_options(run_dir: Path, ok: list[dict], dest: Path, manifest: dict, order, meta: dict, prev: dict, replaced: set[str]) -> dict:
    """One example per option of each gallery input, from the cases that chose that option.
    The keys of the examples written (and of the options dropped) go into replaced."""
    out = {k: dict(v) for k, v in prev.items()}
    for inp in manifest.get("inputs", []):
        if inp.get("type") != "select" or not inp.get("gallery"):
            continue
        per = out.setdefault(inp["id"], {})
        for opt in inp.get("options", []):
            # a case that swaps nodes (overrides) or adds LoRAs is an experiment, not an example of the option
            hits = [r for r in ok if (r.get("values") or {}).get(inp["id"]) == opt["value"] and not experimental(r)]
            if not hits:
                continue
            r = sorted(hits, key=order)[0]
            replaced.add(f'{manifest["id"]}/{inp["id"]}/{opt["value"]}')
            d = dest / "options" / inp["id"] / slug(opt["value"])
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            web = r["web"]
            # a muted 5 s card and a poster are all the picker needs; the full clip stays in the run folder
            card = copy_as(run_dir, web.get("card") or web.get("full"), d, "card")
            per[str(opt["value"])] = {
                "case": r["id"], "type": web.get("type"), "card": card, "poster": copy_as(run_dir, web.get("poster"), d, "poster"),
                "values": {k: v for k, v in (r.get("values") or {}).items() if k != "seed"}, "seed": (r.get("values") or {}).get("seed"),
                "seconds": r.get("seconds"), "peak_vram_gb": r.get("peak_vram_gb"), "gpu": meta.get("gpu"), "run": run_dir.name,
            }
        valid = {str(o["value"]) for o in inp.get("options", [])}
        for k in [k for k in per if k not in valid]:   # an option that was removed from app.json
            shutil.rmtree(dest / "options" / inp["id"] / slug(k), ignore_errors=True)
            del per[k]
            replaced.add(f'{manifest["id"]}/{inp["id"]}/{k}')
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--skip", default="", help="case ids not to publish (comma-separated): their apps keep what they had")
    a = ap.parse_args(argv)
    run_dir = a.run_dir.resolve()
    results = read_results(run_dir)
    skip = {s for s in a.skip.split(",") if s}
    if skip:
        unknown = skip - set(results)
        if unknown:
            print(f"--skip: not in this run: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        results = {k: v for k, v in results.items() if k not in skip}
    cases = json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]
    rank = {c["id"]: i for i, c in enumerate(cases)}
    showcase = {c["id"] for c in cases if c.get("showcase")}

    def is_showcase(r: dict) -> bool:   # lab/cases.json as it is now decides; the flag a result recorded is the fallback
        return r["id"] in showcase if r["id"] in rank else bool(r.get("showcase"))

    def order(r: dict):   # showcase first, then cases that run the app as shipped, then file order
        return (not is_showcase(r), experimental(r), rank.get(r["id"], 10**6))
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) if (run_dir / "run.json").exists() else {}

    index_path = EXAMPLES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"apps": {}}
    published, missing = [], []
    replaced: set[str] = set()   # examples written now: their "mediocre" marks no longer apply
    for manifest_path in sorted((ROOT / "apps").glob("*/app.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        app_id = manifest["id"]
        if app_id in HIDDEN:
            continue
        ok = [r for r in results.values() if r["app"] == app_id and r["status"] == "ok" and r.get("web")]
        if not ok:
            missing.append(app_id)
            continue
        pick = sorted(ok, key=order)[0]
        dest = EXAMPLES / app_id
        prev = index["apps"].get(app_id) or {}
        options = publish_options(run_dir, ok, dest, manifest, order, meta, prev.get("options") or {}, replaced)
        if prev.get("case") in showcase and not is_showcase(pick) and prev.get("full") and (ROOT / "web" / prev["full"]).exists():
            # a run of a few cases does not replace the showcase example with a lesser one
            index["apps"][app_id] = {**prev, **({"options": options} if options else {})}
            published.append(app_id)
            continue
        web = pick["web"]
        replaced.add(app_id)
        clear_main(dest)
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
                    # a still for the card (the poster for clips, the waveform for audio) plus the full file, which
                    # the UI plays and loads into the form when someone presses "Load this example"
                    src = copy_as(run_dir, w.get("card") if w.get("type") != "video" else w.get("poster"), dest, f"input-{input_id}")
                    playable = copy_as(run_dir, w.get("full"), dest, f"input-{input_id}-full")
                    inputs.append({"id": input_id, "label": labels.get(input_id, {}).get("label", input_id),
                                   "type": w.get("type"), "src": src, "full": playable, "from_case": source["id"]})
                    continue
            if isinstance(raw, str) and raw.startswith("asset:") and (ROOT / "lab" / "assets" / raw[len("asset:"):]).exists():
                # a file kept in lab/assets (inpaint's painted mask): copied as it is, so "Load this example" fills it in too
                asset = ROOT / "lab" / "assets" / raw[len("asset:"):]
                name = f"input-{input_id}-full{asset.suffix.lower()}"
                shutil.copy(asset, dest / name)
                rel = f"examples/{app_id}/{name}"
                inputs.append({"id": input_id, "label": labels.get(input_id, {}).get("label", input_id),
                               "type": labels.get(input_id, {}).get("type"), "src": rel, "full": rel, "from": raw})
                continue
            inputs.append({"id": input_id, "label": labels.get(input_id, {}).get("label", input_id),
                           "type": labels.get(input_id, {}).get("type"), "src": None, "full": None, "from": raw})

        shown = {k: v for k, v in (pick.get("values") or {}).items() if k != "seed"}
        index["apps"][app_id] = {
            "case": pick["id"], "type": web.get("type"), "card": card, "poster": poster, "full": full,
            "inputs": inputs, "values": shown, "seed": (pick.get("values") or {}).get("seed"),
            "seconds": pick.get("seconds"), "peak_vram_gb": pick.get("peak_vram_gb"),
            "gpu": meta.get("gpu"), "run": run_dir.name,
            **({"options": options} if options else {}),
        }
        published.append(app_id)

    EXAMPLES.mkdir(parents=True, exist_ok=True)
    index["updated_from"] = run_dir.name
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"published {len(published)} app example(s) to {EXAMPLES.relative_to(ROOT)}")
    sys.path.insert(0, str(ROOT / "tools"))
    import catalog  # tools/catalog.py: docs/vram-map.* show each example's measured peak, so they follow the index
    catalog.write_vram(catalog.load_apps(), quiet=True)
    dropped = unmark(replaced)
    if dropped:
        print(f"{dropped} \"mediocre\" mark(s) removed from lab/flags.json: those examples were replaced")
    if missing:
        print(f"no successful case in this run for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

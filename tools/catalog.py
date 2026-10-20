#!/usr/bin/env python3
"""Everything derived from the manifests: model packs and the VRAM map.

    python tools/catalog.py packs     → packs/<pack>.json (what to download) and packs/index.json
    python tools/catalog.py vram      → docs/vram-map.md and docs/vram-map.json
    python tools/catalog.py all

VRAM numbers here are weight sizes from the Hub, not measurements. "Whole" assumes every
model sits on the GPU at once; "largest phase" assumes ComfyUI keeps only the models of
the current step (text encoding, denoising, decoding) and offloads the rest, which is
what it does when VRAM is short. Activations come on top and are not estimated: the
smoke tests and the lab write measured peaks into each app.json (vram.peak_gb).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_GB = 24.0          # the RTX 3090 Ti this project targets locally
HEADROOM_GB = 4.0        # CUDA context + activations margin used for the "fits" call


def load_apps() -> list[dict]:
    apps = []
    for f in sorted((ROOT / "apps").glob("*/app.json")):
        apps.append(json.loads(f.read_text(encoding="utf-8")))
    return apps


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- packs
def build_packs(apps: list[dict]) -> dict[str, dict]:
    packs: dict[str, dict] = defaultdict(lambda: {"apps": [], "models": {}, "custom_nodes": {}})
    for a in apps:
        p = packs[a["pack"]]
        p["apps"].append(a["id"])
        for m in a.get("models", []):
            key = f"{m['dir']}/{basename(m['file'])}"
            entry = p["models"].setdefault(key, {**{k: m[k] for k in ("repo", "file", "dir", "gb")},
                                                 "name": basename(m["file"]), "gated": bool(m.get("gated")),
                                                 "license": m.get("license"), "used_by": []})
            entry["used_by"].append(a["id"])
        for c in a.get("custom_nodes", []):
            p["custom_nodes"][c["repo"]] = c["commit"]
    out = {}
    for name, p in sorted(packs.items()):
        models = sorted(p["models"].values(), key=lambda m: (m["dir"], m["name"]))
        out[name] = {
            "pack": name,
            "apps": sorted(p["apps"]),
            "download_gb": round(sum(m["gb"] for m in models), 2),
            "needs_hf_token": any(m["gated"] for m in models),
            "custom_nodes": [{"repo": r, "commit": c} for r, c in sorted(p["custom_nodes"].items())],
            "models": models,
        }
    return out


def write_packs(apps: list[dict]) -> None:
    packs = build_packs(apps)
    d = ROOT / "packs"
    d.mkdir(exist_ok=True)
    for name, p in packs.items():
        (d / f"{name}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    index = {name: {"apps": p["apps"], "download_gb": p["download_gb"], "needs_hf_token": p["needs_hf_token"]}
             for name, p in packs.items()}
    (d / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for name, p in packs.items():
        print(f"packs/{name}.json  {len(p['models'])} files  {p['download_gb']:.1f} GB  apps: {', '.join(p['apps'])}")


# ---------------------------------------------------------------- VRAM
def vram_row(a: dict) -> dict:
    req = [m for m in a.get("models", []) if not m.get("optional")]
    opt = [m for m in a.get("models", []) if m.get("optional")]
    by = defaultdict(float)
    for m in req:
        by[m["phase"]] += m["gb"]
    always = by["all"]
    aux_max = max([m["gb"] for m in req if m["phase"] == "aux"], default=0.0)
    phases = {
        "encode": round(by["encode"] + always, 2),
        "denoise": round(by["denoise"] + always, 2),
        "denoise2": round(by["denoise2"] + always, 2) if by["denoise2"] else 0.0,   # second expert, after the first
        "decode": round(by["decode"] + always, 2),
        "aux": round(aux_max + always, 2) if aux_max else 0.0,
    }
    whole = round(sum(m["gb"] for m in req), 2)
    largest_phase, largest_gb = max(phases.items(), key=lambda kv: kv[1])
    limit = LOCAL_GB - HEADROOM_GB
    if not req:
        verdict, gpu = "no models", "any"
    elif whole <= limit:
        verdict, gpu = "fits whole", "L4 / A10G (24 GB)"
    elif largest_gb <= limit:
        verdict, gpu = "fits by phases", "L4 / A10G (24 GB)"
    elif largest_gb <= LOCAL_GB - 1:
        verdict, gpu = "tight (by phases)", "test on L4 / A10G; L40S (48 GB) is comfortable"
    elif whole <= 48 - HEADROOM_GB:
        verdict, gpu = "needs Modal", "L40S (48 GB), whole"
    elif largest_gb <= 48 - HEADROOM_GB:
        verdict, gpu = "needs Modal", "L40S (48 GB), by phases"
    else:
        verdict, gpu = "needs Modal", "A100 80GB / H100"
    biggest = max(req, key=lambda m: m["gb"]) if req else None
    return {
        "id": a["id"], "name": a["name"], "section": a["section"], "pack": a["pack"], "status": a["status"],
        "whole_gb": whole, "phases_gb": phases, "largest_phase": largest_phase, "largest_phase_gb": largest_gb,
        "optional_gb": round(sum(m["gb"] for m in opt), 2),
        "biggest_file": {"name": basename(biggest["file"]), "gb": biggest["gb"]} if biggest else None,
        "verdict_24gb": verdict, "modal_gpu": gpu,
        "measured_peak_gb": (a.get("vram") or {}).get("peak_gb"),
    }


def write_vram(apps: list[dict]) -> None:
    rows = [vram_row(a) for a in apps]
    order = {"fits whole": 0, "fits by phases": 1, "tight (by phases)": 2, "needs Modal": 3, "no models": 4}
    rows.sort(key=lambda r: (order[r["verdict_24gb"]], r["largest_phase_gb"], r["id"]))
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "vram-map.json").write_text(json.dumps({"local_gb": LOCAL_GB, "headroom_gb": HEADROOM_GB, "apps": rows},
                                                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# VRAM map",
        "",
        "Generated by `python tools/catalog.py vram` from the apps' `app.json`. Weight sizes come from the Hugging Face Hub;",
        f"activations are **not** included. Local target: one {LOCAL_GB:.0f} GB card (RTX 3090 Ti) keeping {HEADROOM_GB:.0f} GB of headroom.",
        "",
        "When two apps run back to back with different models, the gateway asks ComfyUI to unload everything first",
        "(`POST /free`), so the previous app never stays in VRAM.",
        "",
        "| App | Status | Whole | Largest phase | Biggest file | Verdict on 24 GB | Modal GPU | Measured |",
        "|---|---|---:|---|---|---|---|---:|",
    ]
    for r in rows:
        bf = f"{r['biggest_file']['name']} ({r['biggest_file']['gb']:.1f})" if r["biggest_file"] else "—"
        peak = f"{r['measured_peak_gb']:.1f}" if r["measured_peak_gb"] else "not measured"
        opt = f" (+{r['optional_gb']:.1f} optional)" if r["optional_gb"] else ""
        lines.append(f"| `{r['id']}` | {r['status']} | {r['whole_gb']:.1f} GB{opt} | {r['largest_phase']} {r['largest_phase_gb']:.1f} GB "
                     f"| {bf} | {r['verdict_24gb']} | {r['modal_gpu']} | {peak} |")
    (docs / "vram-map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['verdict_24gb']:<18} whole {r['whole_gb']:5.1f}  {r['largest_phase']:<7} {r['largest_phase_gb']:5.1f}  {r['id']}")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "all"
    apps = load_apps()
    if cmd in ("packs", "all"):
        write_packs(apps)
    if cmd in ("vram", "all"):
        write_vram(apps)
    if cmd not in ("packs", "vram", "all"):
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

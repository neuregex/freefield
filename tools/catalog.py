#!/usr/bin/env python3
"""Everything derived from the manifests: model packs and the VRAM map.

    python tools/catalog.py packs     → packs/<pack>.json (what to download), packs/<pack>-lite.json and packs/index.json
    python tools/catalog.py vram      → docs/vram-map.md, docs/vram-map.json and the GPU table in README.md
    python tools/catalog.py all

Lite versions (lite/README.md): lite/variants.json names a smaller copy of some model files; an app's lite version
loads those copies instead. packs/<pack>-lite.json downloads what the lite versions of its apps load (the copies and
every file they share with the full version), and the VRAM map says, for 8 to 80 GB cards, whether each version fits,
runs offloading part of its weights to RAM (slower; needs `ram_gb` of RAM) or does not run.

VRAM numbers here are weight sizes from the Hub, not measurements. "Whole" assumes every
model sits on the GPU at once; "largest phase" assumes ComfyUI keeps only the models of
the current step (text encoding, denoising, decoding) and offloads the rest, which is
what it does when VRAM is short. Activations come on top and are not estimated. The
"Measured" column is the peak VRAM of the app's published lab example (web/examples/index.json),
or vram.peak_gb in its app.json when `lab/review.py --apply-peaks` wrote one.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_GB = 24.0          # the RTX 3090 Ti this project targets locally
HEADROOM_GB = 4.0        # CUDA context + activations margin used for the "fits" call
EXAMPLES = ROOT / "web" / "examples" / "index.json"
TIERS = [8, 12, 16, 24, 32, 48, 80]   # card sizes the studio's GPU picker offers, in GB
RAM_OS_GB = 8.0          # RAM left for the system when ComfyUI keeps offloaded weights in RAM
RAM_OS_MEASURED_GB = 4.0  # on top of the RAM a lab run measured ComfyUI using (its own overhead is in the measure)
MEASURED = ROOT / "docs" / "vram-measured.json"   # lab runs with ComfyUI capped to a card size (lab/review.py --tiers)
MEASURED_VERSION = 2    # lab/review.py: version 1 files ran a card size's cases in one ComfyUI and are not used
README_START, README_END = "<!-- gpu-table:start -->", "<!-- gpu-table:end -->"


def headroom(a: dict) -> float:
    """GB kept free for the CUDA context and activations: video frames take more than a picture."""
    return HEADROOM_GB if a["section"] == "video" else 2.5


def load_lite() -> dict[str, dict]:
    """lite/variants.json: base name of a full file → its smaller copy."""
    f = ROOT / "lite" / "variants.json"
    return json.loads(f.read_text(encoding="utf-8")).get("variants", {}) if f.exists() else {}


LITE = load_lite()


def models_for(a: dict, variant: str) -> list[dict]:
    """The models a version loads: in lite, each model with a copy is that copy (same folder and phase)."""
    if variant != "lite":
        return a.get("models", [])
    out = []
    for m in a.get("models", []):
        lite = LITE.get(basename(m["file"]))
        if lite:
            m = {**m, "repo": lite["repo"], "file": lite["file"], "gb": lite["gb"],
                 "license": lite.get("license", m.get("license")),
                 "gated": lite.get("gated", m.get("gated") if lite["repo"] == m["repo"] else False)}
        out.append(m)
    return out


def has_lite(a: dict) -> bool:
    return any(not m.get("optional") and basename(m["file"]) in LITE for m in a.get("models", []))


def example_peaks() -> dict[str, dict]:
    """Peak VRAM, GPU and run of each app's published lab example."""
    try:
        apps = json.loads(EXAMPLES.read_text(encoding="utf-8"))["apps"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for app_id, e in apps.items():
        if e.get("peak_vram_gb"):
            gpu = (e.get("gpu") or "GPU").split(",")[0].replace("NVIDIA ", "").replace(" 80GB HBM3", "")
            out[app_id] = {"peak_gb": e["peak_vram_gb"], "measured_on": f"{gpu} · {e.get('run', '')}"}
    return out


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
    lite_packs = {a["pack"] for a in apps if has_lite(a)}
    for a in apps:
        for variant in ("full", "lite"):
            if variant == "lite" and a["pack"] not in lite_packs:
                continue
            add_to_pack(packs[a["pack"] if variant == "full" else f"{a['pack']}-lite"], a, variant)
    out = {}
    for name, p in sorted(packs.items()):
        models = sorted(p["models"].values(), key=lambda m: (m["dir"], m["name"]))
        lite = name.endswith("-lite")
        out[name] = {
            "pack": name,
            **({"variant": "lite", "of": name[:-5]} if lite else {}),
            "apps": sorted(p["apps"]),
            "download_gb": round(sum(m["gb"] for m in models), 2),
            "needs_hf_token": any(m["gated"] for m in models),
            "custom_nodes": [{"repo": r, "commit": c} for r, c in sorted(p["custom_nodes"].items())],
            "models": models,
        }
    return out


def add_to_pack(p: dict, a: dict, variant: str) -> None:
    p["apps"].append(a["id"])
    for m in models_for(a, variant):
        key = f"{m['dir']}/{basename(m['file'])}"
        entry = p["models"].setdefault(key, {**{k: m[k] for k in ("repo", "file", "dir", "gb")},
                                             "name": basename(m["file"]), "gated": bool(m.get("gated")),
                                             "license": m.get("license"), "used_by": []})
        entry["used_by"].append(a["id"])
    for c in a.get("custom_nodes", []):
        p["custom_nodes"][c["repo"]] = c["commit"]


def default_packs() -> list[str]:
    """The packs a pod downloads when FREEFIELD_PACKS is not set, as infra/pod.py says (read, not imported)."""
    pod = (ROOT / "infra" / "pod.py").read_text(encoding="utf-8")
    return re.search(r'^DEFAULT_PACKS = "([^"]*)"', pod, re.M)[1].split(",")


def write_packs(apps: list[dict]) -> None:
    packs = build_packs(apps)
    d = ROOT / "packs"
    d.mkdir(exist_ok=True)
    for name, p in packs.items():
        (d / f"{name}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # "gated": a file of each repo that asks for a license, to ask Hugging Face whether a token can read it before
    # anything downloads; "default": what a pod downloads without FREEFIELD_PACKS
    defaults = default_packs()
    gated = lambda p: {m["repo"]: m["file"] for m in reversed(p["models"]) if m["gated"]}  # noqa: E731  (the first file wins)
    index = {name: {"apps": p["apps"], "download_gb": p["download_gb"], "needs_hf_token": p["needs_hf_token"],
                    "gated": dict(sorted(gated(p).items())), "default": name in defaults,
                    **({"variant": "lite", "of": p["of"]} if p.get("variant") == "lite" else {}),
                    **({"lite": f"{name}-lite"} if f"{name}-lite" in packs else {})}
             for name, p in packs.items()}
    (d / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for name, p in packs.items():
        print(f"packs/{name}.json  {len(p['models'])} files  {p['download_gb']:.1f} GB  apps: {', '.join(p['apps'])}")


# ---------------------------------------------------------------- VRAM
def phases_of(req: list[dict]) -> dict[str, float]:
    """GB on the GPU in each step when ComfyUI keeps only the models of that step."""
    by = defaultdict(float)
    for m in req:
        by[m["phase"]] += m["gb"]
    always = by["all"]
    aux_max = max([m["gb"] for m in req if m["phase"] == "aux"], default=0.0)
    return {
        "encode": round(by["encode"] + always, 2),
        "denoise": round(by["denoise"] + always, 2),
        "denoise2": round(by["denoise2"] + always, 2) if by["denoise2"] else 0.0,
        "decode": round(by["decode"] + always, 2),
        "aux": round(aux_max + always, 2) if aux_max else 0.0,
    }


def version_row(a: dict, variant: str) -> dict:
    req = [m for m in models_for(a, variant) if not m.get("optional")]
    phases = phases_of(req)
    largest_phase, largest_gb = max(phases.items(), key=lambda kv: kv[1])
    whole = round(sum(m["gb"] for m in req), 2)
    return {"whole_gb": whole, "largest_phase": largest_phase, "largest_phase_gb": largest_gb,
            "ram_gb": int(-(-(whole + RAM_OS_GB) // 1))}


def tier_fit(a: dict, v: dict, tier: int) -> str:
    """fits: the largest phase fits next to the headroom; offload: ComfyUI keeps part of the weights in RAM and moves
    them in each step (slower; needs v["ram_gb"] of RAM); estimates until docs/vram-measured.json says otherwise."""
    if not a.get("models"):
        return "fits"
    return "fits" if v["largest_phase_gb"] <= tier - headroom(a) else "offload"


def measured_fit(entry: dict, tier: int | None = None) -> str:
    if not entry.get("ok"):
        return "no"
    if entry.get("offloaded"):
        return "offload"
    # the peak is what nvidia-smi saw on the bigger GPU, the CUDA context and kernels' own memory included: past the
    # card's size, a real card that size would have had to keep part of the weights in RAM
    if tier is not None and (entry.get("peak_gb") or 0) > tier:
        return "offload"
    return "fits"


def vram_row(a: dict, measured: dict | None = None, tiers_measured: dict | None = None) -> dict:
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
    variants = ["full", "lite"] if has_lite(a) else ["full"]
    versions = {v: version_row(a, v) for v in variants}
    tiers = {}
    for t in TIERS:
        tiers[str(t)] = {}
        for v in variants:
            got = (tiers_measured or {}).get(str(t), {}).get(v)
            tiers[str(t)][v] = measured_fit(got, t) if got else tier_fit(a, versions[v], t)
    for v in variants:   # what ComfyUI used when it had to keep weights in RAM, once the lab measured it
        ram = [e["ram_peak_gb"] for sizes in (tiers_measured or {}).values() for vv, e in sizes.items()
               if vv == v and e.get("ok") and e.get("offloaded") and e.get("ram_peak_gb")]
        if ram:
            versions[v]["ram_gb"] = int(-(-(max(ram) + RAM_OS_MEASURED_GB) // 1))
    return {
        "id": a["id"], "name": a["name"], "section": a["section"], "pack": a["pack"], "status": a["status"],
        "versions": {v: {k: r[k] for k in ("whole_gb", "largest_phase", "largest_phase_gb")} for v, r in versions.items()},
        "tiers": tiers, "ram_gb": {v: r["ram_gb"] for v, r in versions.items()},
        "measured": tiers_measured or None,
        "whole_gb": whole, "phases_gb": phases, "largest_phase": largest_phase, "largest_phase_gb": largest_gb,
        "optional_gb": round(sum(m["gb"] for m in opt), 2),
        "biggest_file": {"name": basename(biggest["file"]), "gb": biggest["gb"]} if biggest else None,
        "verdict_24gb": verdict, "modal_gpu": gpu,
        "measured_peak_gb": (a.get("vram") or measured or {}).get("peak_gb"),
        "measured_on": (a.get("vram") or measured or {}).get("measured_on"),
    }


def tier_counts(rows: list[dict]) -> list[dict]:
    """Per card size: apps that run as they are, apps that run in their lite version, apps that need offloading."""
    out = []
    for t in TIERS:
        c = {"tier": t, "full": 0, "lite": 0, "offload": 0, "no": 0}
        for r in rows:
            if not r["whole_gb"] and r["verdict_24gb"] == "no models":
                continue
            fit = r["tiers"][str(t)]
            if fit["full"] == "fits":
                c["full"] += 1
            elif fit.get("lite") == "fits":
                c["lite"] += 1
            elif "offload" in fit.values():
                c["offload"] += 1
            else:
                c["no"] += 1
        out.append(c)
    return out


SYMBOL = {"fits": "✓", "offload": "RAM", "no": "✗"}


def tier_cell(fit: dict) -> str:
    if fit["full"] == "fits":
        return "✓"
    if fit.get("lite") == "fits":
        return "lite"
    return SYMBOL.get(fit.get("lite", fit["full"]), "?")


def write_readme_table(counts: list[dict], with_models: int) -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if README_START not in text:
        return
    failed = any(c["no"] for c in counts)   # a lab run capped to that size did not finish
    lines = [README_START,
             "| Your card | Runs as it is | Runs in its lite version | Runs offloading to RAM (slower) |" + (" Failed in the lab |" if failed else ""),
             "|---|---:|---:|---:|" + ("---:|" if failed else "")]
    for c in counts:
        lines.append(f"| {c['tier']} GB | {c['full']} | {c['lite']} | {c['offload']} |" + (f" {c['no']} |" if failed else ""))
    lines += ["", f"Of the {with_models} apps that load models; estimates from the weight sizes until the lab measures them "
              f"([`docs/vram-map.md`](docs/vram-map.md)). Offloading needs about the app's weights plus {RAM_OS_GB:.0f} GB of RAM. "
              "The studio's GPU picker says it app by app, for your card and your RAM.", README_END]
    head, rest = text.split(README_START, 1)
    tail = rest.split(README_END, 1)[1]
    readme.write_text(head + "\n".join(lines) + tail, encoding="utf-8")


def load_measured() -> dict:
    """docs/vram-measured.json's apps, if the lab wrote it with every case in a fresh ComfyUI."""
    if not MEASURED.exists():
        return {}
    doc = json.loads(MEASURED.read_text(encoding="utf-8"))
    if doc.get("version", 1) < MEASURED_VERSION:
        print(f"ignoring {MEASURED.relative_to(ROOT)}: version {doc.get('version', 1)}, measured before each case got "
              "its own ComfyUI; measure again with lab/lite_modal.py --step measure")
        return {}
    return doc.get("apps", {})


def write_vram(apps: list[dict], quiet: bool = False) -> None:
    peaks = example_peaks()
    measured = load_measured()
    rows = [vram_row(a, peaks.get(a["id"]), measured.get(a["id"])) for a in apps]
    order = {"fits whole": 0, "fits by phases": 1, "tight (by phases)": 2, "needs Modal": 3, "no models": 4}
    rows.sort(key=lambda r: (order[r["verdict_24gb"]], r["largest_phase_gb"], r["id"]))
    counts = tier_counts(rows)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "vram-map.json").write_text(json.dumps({"local_gb": LOCAL_GB, "headroom_gb": HEADROOM_GB, "tiers": TIERS,
                                                    "ram_os_gb": RAM_OS_GB, "counts": counts, "apps": rows},
                                                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with_models = sum(1 for r in rows if r["verdict_24gb"] != "no models")
    lines = [
        "# VRAM map",
        "",
        "Generated by `python tools/catalog.py vram` from the apps' `app.json` and `lite/variants.json`. Weight sizes come",
        "from the Hugging Face Hub; activations are **not** included.",
        "",
        "## By card size",
        "",
        f"Of the {with_models} apps that load models. *Lite* is the app's lite version: some of its files swapped for smaller",
        "copies of the same models that ComfyUI loads with the same node ([`lite/README.md`](../lite/README.md)). *RAM*:",
        "the largest step does not fit, so ComfyUI keeps part of the weights in RAM and moves them in each step; it runs,",
        f"slower, with about the app's weights plus {RAM_OS_GB:.0f} GB of RAM. A video app keeps {HEADROOM_GB:.0f} GB free for",
        "activations, the others 2.5 GB. These are estimates until the lab runs the app with ComfyUI capped to that size",
        "(`docs/vram-measured.json`).",
        "",
        "| Card | Runs as it is | Runs lite | Needs RAM offload | Failed in the lab |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in counts:
        lines.append(f"| {c['tier']} GB | {c['full']} | {c['lite']} | {c['offload']} | {c['no']} |")
    lines += [
        "",
        "## App by app",
        "",
        "When two apps run back to back with different models, the gateway asks ComfyUI to unload everything first",
        "(`POST /free`), so the previous app never stays in VRAM.",
        "",
        "*Measured* is the peak VRAM of the app's lab example as published in the web UI, and the GPU it ran on. On an",
        "80 GB H100 ComfyUI can keep models of earlier steps loaded instead of offloading them, so a peak measured there",
        "is not the least the app needs. In the card columns: ✓ runs as it is, *lite* runs in its lite version, *RAM*",
        "needs RAM offload.",
        "",
        "| App | Largest step | Lite: largest step | " + " | ".join(f"{t} GB" for t in TIERS) + " | Measured |",
        "|---|---:|---:|" + "---|" * len(TIERS) + "---:|",
    ]
    for r in rows:
        on = (r["measured_on"] or "").split(" · ")[0]
        peak = f"{r['measured_peak_gb']:.1f} GB ({on})" if r["measured_peak_gb"] else "not measured"
        lite = r["versions"].get("lite")
        lite_cell = f"{lite['largest_phase_gb']:.1f} GB" if lite else "—"
        cells = " | ".join("—" if r["verdict_24gb"] == "no models" else tier_cell(r["tiers"][str(t)]) for t in TIERS)
        lines.append(f"| `{r['id']}` | {r['largest_phase']} {r['largest_phase_gb']:.1f} GB | {lite_cell} | {cells} | {peak} |")
    (docs / "vram-map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_readme_table(counts, with_models)
    if quiet:
        return
    for c in counts:
        print(f"{c['tier']:>3} GB  as is {c['full']:3d}  lite {c['lite']:3d}  RAM offload {c['offload'] + c['no']:3d}")


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

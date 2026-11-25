#!/usr/bin/env python3
"""The Hugging Face model cards of the lite copies Freefield makes (lite/quantize.json → lite/cards/<repo>.md).

    python tools/lite_cards.py            # writes lite/cards/*.md from the reports and the measurements

Reads lite/quantize.json (repos, files, licenses), lite/reports/<file>.json (what tools/quantize.py measured on the
weights) and docs/vram-measured.json (what the lab measured at each card size, lab/lite_modal.py). The cards are
plain Markdown, reviewed before lab/hf_publish_modal.py --publish uploads them as each repo's README.md.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISCORD = "https://discord.gg/HxfP9TnctJ"
TIERS = [8, 12, 16, 24]
MEASURED_VERSION = 2   # lab/review.py: version 1 ran a card size's cases in one ComfyUI, one run carrying the last's models
COMFYUI_TESTED = "e3bee7f"   # infra/common.py COMFYUI_COMMIT, 2026-10-19, after 0.42.0: the ComfyUI the lab ran them on

# what each measured case runs, in a line (lab/cases.json)
WORKLOAD = {
    "i2v-portrait": "image to video, 4 s with audio, two stages",
    "fx-cakeify": "image to video with an effect LoRA (Cakeify), 81 frames, landscape",
    "camera-moves-quality": "image to video with a zoom-in camera move, 81 frames at 832×480",
    "motion-transfer-walk": "a character image animated with the motion of a driving clip",
    "relight-neon": "one image edit (relighting a portrait)",
    "ref-song": "a 10-second song with vocals",
}

LICENSE_TEXT = {
    "ltx": (
        "These files are a modified version of [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) by Lightricks: a "
        "Derivative of LTX-2.x, distributed under the **LTX-2.x Community License Agreement**, included in full as "
        "[LICENSE](LICENSE).\n\n"
        "- Use of LTX-2.x and of any Derivative of it is subject to Section 4 and Attachment A of that agreement, "
        "including all of its use restrictions and acceptable use policies.\n"
        "- A Commercial Entity (annual revenues of at least US$10,000,000) needs a paid commercial license from "
        "Lightricks before any use of LTX-2.x or its Derivatives, unless the use is a Non-Commercial Purpose as the "
        "agreement defines it.\n"
        "- These files were changed: their weights were quantized as described above. Nothing else was changed.\n"
        "- The text encoder holds the weights of Gemma 4 12B by Google, released under the Apache License 2.0 "
        "([Gemma 4 license](https://ai.google.dev/gemma/docs/gemma_4_license)), with LTX-2.5's projection layers."
    ),
    "apache": (
        "Quantized from {bases}, released under the **Apache License 2.0**, included as [LICENSE](LICENSE). "
        "These files were changed: their weights were quantized as described above. Nothing else was changed."
    ),
    "minimax": (
        "These files are a modified version of [MiniMax Music 3](https://huggingface.co/MiniMaxAI/MiniMax-Music3), "
        "Copyright (c) 2026 MiniMax, distributed under the **MiniMax-Music3 Community License**, included in full as "
        "[LICENSE](LICENSE), together with its Acceptable Use Policy (Exhibit A). Its commercial terms apply: a "
        "commercial product or service that uses it shows \"MiniMax-Music3\" on its user interface, and one with "
        "yearly revenue above US$20 million needs written authorization from MiniMax. These files were changed: "
        "their weights were quantized as described above. MiniMax Music 3 was fine-tuned from Qwen3-8B (Apache "
        "License 2.0)."
    ),
}


def license_kind(lic: dict) -> str:
    if lic["id"] == "apache-2.0":
        return "apache"
    return "ltx" if "ltx" in lic.get("name", "") else "minimax"


def front_matter(info: dict) -> str:
    lic = info["license"]
    lines = ["---", f"license: {lic['id']}"]
    if lic["id"] == "other":
        lines += [f"license_name: {lic['name']}", "license_link: LICENSE"]
    lines += ["base_model:"] + [f"- {b}" for b in info["base_model"]]
    lines += ["base_model_relation: quantized", f"pipeline_tag: {info['pipeline_tag']}", "tags:",
              "- comfyui", "- quantized", "- w4a8"] + [f"- {t}" for t in info.get("tags", [])] + ["---", ""]
    return "\n".join(lines)


def verdict(e: dict | None) -> str:
    if not e:
        return "—"
    if not e.get("ok"):
        return "✗ out of memory" if "memory" in (e.get("error") or "").lower() else "✗ did not run"
    extra = [f"{e['seconds']:.0f} s" if e.get("seconds") else None,
             f"{e['ram_peak_gb']:.0f} GB RAM" if e.get("ram_peak_gb") else None]
    return "✓ runs · " + " · ".join(x for x in extra if x)


def memory_section(files: list[dict], measured: dict, measure_cases: list[str]) -> str:
    """The measured cases whose app loads one of the files these copies replace."""
    cases = json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    replaced = {f["replaces"] for f in files}
    copies = json.loads((ROOT / "lite" / "variants.json").read_text(encoding="utf-8"))["variants"]
    out = []
    for cid in measure_cases:
        app = by_id[cid]["app"]
        manifest = json.loads((ROOT / "apps" / app / "app.json").read_text(encoding="utf-8"))
        loads = {m["file"].rsplit("/", 1)[-1] for m in manifest.get("models", []) if not m.get("optional")}
        if not loads & replaced or app not in measured:
            continue
        others = sorted(copies[b]["file"].rsplit("/", 1)[-1] for b in loads - replaced if b in copies)
        rows = ["| Card | Original files | With these files |", "|---|---|---|"]
        for t in TIERS:
            m = measured[app].get(str(t), {})
            rows.append(f"| {t} GB | {verdict(m.get('full'))} | {verdict(m.get('lite'))} |")
        note = f" The run with these files also used the official smaller copies of {', '.join(f'`{o}`' for o in others)}." if others else ""
        out.append(f"**{WORKLOAD.get(cid, cid)}**{'.' if not note else ''}{note}\n\n" + "\n".join(rows))
    if not out:
        return ""
    return ("## Memory\n\nMeasured on an NVIDIA L40S with ComfyUI limited to each card size (`--reserve-vram`, a "
            "PyTorch memory cap and `--disable-dynamic-vram`), each run in a freshly started ComfyUI. RAM is the most "
            "the ComfyUI process used: below a certain card size it keeps part of the weights there. Times are for "
            "the L40S; a smaller card is slower. On a real card the CUDA context and some kernels also take memory "
            "outside that cap, so close to the limit ComfyUI keeps a little more in RAM.\n\n"
            + "\n\n".join(out) + "\n")


def size_line(files: list[dict], reports: dict) -> str:
    """What the copies weigh against the bf16 files they were made from, from tools/quantize.py's reports."""
    got = [reports[f["name"]] for f in files if f["name"] in reports]
    if len(got) != len(files):
        return ""
    out, src = sum(r["gb_out"] for r in got), sum(r["gb_in"] for r in got)
    what = "file weighs" if len(files) == 1 else "files weigh"
    return f"The {what} {out:.1f} GB in all, {out / src:.0%} of the {src:.1f} GB of bf16 weights they come from."


def card(repo: str, info: dict, files: list[dict], reports: dict, measured: dict, measure_cases: list[str]) -> str:
    rows = ["| File | Put it in | Size | Instead of |", "|---|---|---:|---|"]
    for f in files:
        r = reports.get(f["name"], {})
        size = f"{r['gb_out']:.1f} GB" if r.get("gb_out") else "—"
        src = f["source"]["file"].rsplit("/", 1)[-1]
        rows.append(f"| `{f['dir']}/{f['name']}` | `ComfyUI/models/{f['dir']}/` | {size} | "
                    f"`{src}` ({f['source']['gb']:.1f} GB) or `{f['replaces']}` ({f['ref']['gb']:.1f} GB) |")
    made = []
    for f in files:
        r = reports.get(f["name"])
        if not r:
            continue
        e = r["relative_error"]
        made.append(f"- `{f['name']}`: {r['layers_w4a8']} layers in w4a8, the ones `{f['ref']['file'].rsplit('/', 1)[-1]}` "
                    f"quantized" + (f"; {len(r['layers_from_reference'])} kept as they are in that file "
                                    f"({', '.join(r['layers_from_reference'][:3])})" if r["layers_from_reference"] else "")
                    + f". Weight error per layer after a round trip, ‖W − Ŵ‖ / ‖W‖: mean {e['mean']:.3f}, "
                    f"max {e['max']:.3f}.")
    loader = {"diffusion_models": "**Load Diffusion Model** (`UNETLoader`)", "text_encoders": "**Load CLIP** (`CLIPLoader`)"}
    use = [f"pick `{f['name']}` in {loader.get(f['dir'], 'its loader')}" for f in files]
    lic = license_kind(info["license"])
    bases = ", ".join(f"[{b}](https://huggingface.co/{b})" for b in info["base_model"])
    text = [
        front_matter(info),
        f"# {info['title']}",
        "",
        f"4-bit copies of {bases} in ComfyUI's own `asym_w4a8_int8` format: they load with ComfyUI's usual loader "
        f"nodes, no custom nodes. {size_line(files, reports)}",
        "",
        "## Files",
        "",
        *rows,
        "",
        "## How they were made",
        "",
        "- Format: `asym_w4a8_int8` from ComfyUI's QUANTIZATION.md: 4-bit codes on a Lloyd-Max codebook, fp8 (E4M3) "
        "scales every 16 weights, an fp32 scale per output row and a Hadamard rotation in groups of 256, made with "
        "Comfy Kitchen 0.2.39, the library ComfyUI runs them with.",
        "- Layers: only those the official quantized file quantized; every other tensor is the bf16 original.",
        *made,
        *([f"- Checked: {info['checked']}"] if info.get("checked") else []),
        "",
        *[m for m in [memory_section(files, measured, measure_cases)] if m],
        "## Use",
        "",
        "1. Put each file in the folder of the table above.",
        "2. In your workflow, " + "; ".join(use) + ". Nothing else changes.",
        f"3. ComfyUI from 2026-10-19 or newer (tested on commit `{COMFYUI_TESTED}`, after 0.42.0). RTX 30 series "
        "cards and newer run them with int8 kernels; older cards dequantize "
        "each layer before multiplying (the same memory, slower).",
        "",
        "## License",
        "",
        LICENSE_TEXT[lic].format(bases=bases),
        "",
        "## Community",
        "",
        f"Questions, results and other quantized models: [Discord]({DISCORD}).",
        "",
    ]
    return "\n".join(text)


def main() -> int:
    spec = json.loads((ROOT / "lite" / "quantize.json").read_text(encoding="utf-8"))
    reports = {}
    for p in sorted((ROOT / "lite" / "reports").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        reports[r["output"]] = r
    mfile = ROOT / "docs" / "vram-measured.json"
    mdoc = json.loads(mfile.read_text(encoding="utf-8")) if mfile.exists() else {}
    measured = mdoc.get("apps", {}) if mdoc.get("version", 1) >= MEASURED_VERSION else {}
    if mdoc and not measured:
        print("docs/vram-measured.json is a version 1 file (cases sharing one ComfyUI): the cards leave memory out")
    measure_cases = json.loads((ROOT / "lite" / "measure.json").read_text(encoding="utf-8"))["cases"]
    out = ROOT / "lite" / "cards"
    out.mkdir(exist_ok=True)
    for repo, info in spec["repos"].items():
        if info.get("publish") is False:   # a copy that did not pass: no card to publish
            continue
        files = [f for f in spec["files"] if f["repo"] == repo]
        (out / f"{repo}.md").write_text(card(repo, info, files, reports, measured, measure_cases), encoding="utf-8")
        print(f"lite/cards/{repo}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

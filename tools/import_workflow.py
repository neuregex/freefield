#!/usr/bin/env python3
"""Turn a ComfyUI workflow into a draft Freefield app: apps/<id>/app.json + apps/<id>/workflow.api.json.

    python tools/import_workflow.py my_workflow.json --id my-app [--name "My App"] [--section image]
    python tools/import_workflow.py ui_workflow.json --id my-app --object-info object_info.json   # a UI workflow
    python tools/import_workflow.py wf.json --id my-app --out /tmp/my-app --force                 # elsewhere, overwrite

The workflow may be in API format ("Export (API)") or a UI workflow with nodes and links (converted with
tools/ui2api.py; pass --object-info with GET /object_info from a ComfyUI that has its nodes when the bundled
tools/object_info.json lacks one). What it writes:

- inputs: each LoadImage / LoadVideo / LoadAudio, the positive prompt (the literal text of a text encoder, or the
  PrimitiveString node that feeds it), the negative prompt when it has words, seeds, steps, literal latent
  width/height, a ResolutionSelector aspect ratio, and Primitive nodes someone gave a title;
- outputs: every Save node (a PreviewImage becomes a SaveImage), filename_prefix "freefield/<id>";
- models: every loader file, with repo, path, size, folder and license taken from packs/*.json when Freefield
  already knows the file, and its phase from the apps that use it. A file Freefield does not know gets
  repo "TODO/unknown" and a note: find it on Hugging Face before the app is used;
- status "draft", and the pack that already holds all its models, when one does.

Then it runs the repo's validator on the new app alone and prints a report. It exits 1 when the app does not
validate (or would not), 2 on bad arguments. Nothing in the workflow is executed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui2api import ConversionError, convert  # noqa: E402  tools/ui2api.py

MODEL_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin", ".sft")
FILE_LOADERS = {"LoadImage": ("image", "image"), "LoadImageMask": ("image", "image"),
                "LoadVideo": ("video", "file"), "LoadAudio": ("audio", "audio")}
SAVE_TYPES = {"SaveImage": "image", "SaveAnimatedWEBP": "image", "SaveAnimatedPNG": "image",
              "SaveVideo": "video", "SaveWEBM": "video",
              "SaveAudio": "audio", "SaveAudioMP3": "audio", "SaveAudioOpus": "audio"}
STRING_PRIMITIVES = {"PrimitiveString", "PrimitiveStringMultiline"}
NUMBER_PRIMITIVES = {"PrimitiveInt": "int", "PrimitiveFloat": "float", "PrimitiveBoolean": "bool"}
SIZE_OPTIONS = [768, 1024, 1280, 1536]
# loader class → (models/ folder, phase) when packs/*.json does not know the file
LOADER_GUESS = [
    (re.compile(r"Checkpoint", re.I), "checkpoints", "all"),
    (re.compile(r"Lora", re.I), "loras", "denoise"),
    (re.compile(r"CLIPVision", re.I), "clip_vision", "encode"),
    (re.compile(r"CLIP|TextEncoder|T5", re.I), "text_encoders", "encode"),
    (re.compile(r"VAE", re.I), "vae", "decode"),
    (re.compile(r"LatentUpscale", re.I), "latent_upscale_models", "aux"),
    (re.compile(r"Upscale", re.I), "upscale_models", "aux"),
    (re.compile(r"BackgroundRemoval", re.I), "background_removal", "all"),
    (re.compile(r"MoGe|Geometry", re.I), "geometry_estimation", "aux"),
    (re.compile(r"Interpolation|FILM", re.I), "frame_interpolation", "aux"),
    (re.compile(r"AudioEncoder", re.I), "audio_encoders", "encode"),
    (re.compile(r"UNET|Diffusion|Model", re.I), "diffusion_models", "denoise"),
]


def is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int)


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s if s and s[0].isalpha() else f"in_{s}" if s else "input"


def title_of(node: dict) -> str:
    return ((node.get("_meta") or {}).get("title") or "").strip()


def plain_label(title: str, class_type: str) -> str | None:
    """A title someone gave the node, cleaned up; None when it is just the node's default name."""
    t = re.sub(r"^(Int|Float|Boolean|String|Primitive\w*)\s*\((.*)\)$", r"\2", title).strip()
    defaults = {class_type.lower(), re.sub(r"(?<!^)(?=[A-Z])", " ", class_type).lower(), "int", "float", "boolean",
                "string", "string (multiline)", "primitive", ""}
    return None if t.lower() in defaults else t


# ---------------------------------------------------------------- what Freefield already knows
def known_files(root: Path) -> tuple[dict[str, dict], dict[str, set[str]], dict[str, str]]:
    """basename → pack entry, basename → packs holding it, basename → the phase apps use it in."""
    files: dict[str, dict] = {}
    in_packs: dict[str, set[str]] = defaultdict(set)
    for p in sorted((root / "packs").glob("*.json")):
        if p.name == "index.json":
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        for m in spec.get("models", []):
            files.setdefault(m["name"], m)
            in_packs[m["name"]].add(spec["pack"])
    phases: dict[str, Counter] = defaultdict(Counter)
    for f in sorted((root / "apps").glob("*/app.json")):
        try:
            for m in json.loads(f.read_text(encoding="utf-8")).get("models", []):
                phases[m["file"].rsplit("/", 1)[-1]][m["phase"]] += 1
        except (OSError, ValueError, KeyError):
            continue
    return files, in_packs, {k: c.most_common(1)[0][0] for k, c in phases.items()}


# ---------------------------------------------------------------- graph helpers
def consumers(api: dict) -> dict[str, list[tuple[str, str]]]:
    """node id → [(consumer node id, consumer input name)]"""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for nid, n in api.items():
        for k, v in n["inputs"].items():
            if is_link(v):
                out[v[0]].append((nid, k))
    return out


def polarity(api: dict, users: dict, start: str) -> str | None:
    """Follow a text encoder's output downstream until an input named positive / negative takes it."""
    seen, todo = set(), [start]
    while todo:
        nid = todo.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        for (c, field) in users.get(nid, []):
            f = field.lower()
            if "negative" in f:
                return "negative"
            if "positive" in f:
                return "positive"
            if f in ("conditioning", "conditioning_to", "conditioning_from", "cond") or "conditioning" in f:
                todo.append(c)
    return None


def string_source(api: dict, nid: str, field: str) -> tuple[str, str] | None:
    """Where the words of a text input live: the input itself, or the PrimitiveString node upstream of it."""
    v = api[nid]["inputs"].get(field)
    if isinstance(v, str):
        return (nid, field)
    seen, todo = set(), [v]
    while todo:
        cur = todo.pop(0)
        if not is_link(cur) or cur[0] in seen or cur[0] not in api:
            continue
        seen.add(cur[0])
        node = api[cur[0]]
        if node["class_type"] in STRING_PRIMITIVES and isinstance(node["inputs"].get("value"), str):
            return (cur[0], "value")
        todo.extend(x for x in node["inputs"].values() if is_link(x))
    return None


def text_fields(node: dict) -> list[str]:
    ct = node["class_type"]
    if "Encode" not in ct and "Prompt" not in ct:
        return []
    return [k for k in ("text", "prompt", "text_g", "clip_l", "t5xxl") if k in node["inputs"]]


# ---------------------------------------------------------------- the import
def load_workflow(path: Path, object_info: Path | None) -> tuple[dict, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "nodes" in data and isinstance(data["nodes"], list):
        info_path = object_info or ROOT / "tools" / "object_info.json"
        info = json.loads(info_path.read_text(encoding="utf-8"))
        api, warnings = convert(data, info)
        return api, [f"converted from the UI format with {info_path.name}"] + warnings
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):   # a saved /prompt request
        data = data["prompt"]
    if not isinstance(data, dict) or not all(isinstance(n, dict) and "class_type" in n for n in data.values()):
        raise ValueError("not a ComfyUI workflow: expected API format {id: {class_type, inputs}} or a UI workflow")
    return data, []


def build(api: dict, app_id: str, name: str | None, section: str | None, source: str, root: Path = ROOT,
          object_info: dict | None = None) -> tuple[dict, dict, dict]:
    """(app.json, workflow.api.json, report) for a workflow already in API format."""
    api = json.loads(json.dumps(api))
    info = object_info or {}
    report: dict = {"inputs": [], "outputs": [], "models": [], "unknown": [], "check": [], "pack": None}
    files, in_packs, phases = known_files(root)
    users = consumers(api)
    order = sorted(api, key=lambda k: [int(p) if p.isdigit() else p for p in k.split(":")])
    inputs: list[dict] = []
    taken: Counter = Counter()

    def add(inp: dict) -> None:
        base = inp["id"]
        taken[base] += 1
        if taken[base] > 1:
            inp["id"] = f"{base}{taken[base]}"
        inputs.append(inp)

    # files the user gives
    for nid in order:
        n = api[nid]
        if n["class_type"] in FILE_LOADERS:
            kind, field = FILE_LOADERS[n["class_type"]]
            label = plain_label(title_of(n), n["class_type"]) or {"image": "Image", "video": "Video", "audio": "Audio"}[kind]
            if label.lower().startswith("load "):
                label = label[5:].strip().capitalize() or label
            add({"id": kind, "type": kind, "label": label, "required": True, "bind": [{"node": nid, "field": field}]})

    # prompts
    seen_src: set[tuple[str, str]] = set()
    for nid in order:
        n = api[nid]
        for field in text_fields(n):
            src = string_source(api, nid, field)
            if not src or src in seen_src:
                continue
            words = api[src[0]]["inputs"][src[1]]
            pol = polarity(api, users, nid) or ("positive" if n["class_type"].startswith("TextGenerate") or field == "prompt" else None)
            if pol is None:
                continue
            if pol == "negative" and not words.strip():
                continue
            seen_src.add(src)
            if pol == "positive":
                add({"id": "prompt", "type": "textarea", "label": "Prompt", "required": True, "default": words,
                     "bind": [{"node": src[0], "field": src[1]}]})
            else:
                add({"id": "negative", "type": "textarea", "label": "Negative prompt", "default": words,
                     "bind": [{"node": src[0], "field": src[1]}]})

    # numbers on samplers and latents
    seeds, steps = [], []
    for nid in order:
        n = api[nid]
        for k, v in n["inputs"].items():
            if "." in k or isinstance(v, bool) or not isinstance(v, int):
                continue
            if k in ("seed", "noise_seed") and ("Sampler" in n["class_type"] or "Noise" in n["class_type"]):
                seeds.append({"node": nid, "field": k})
            elif k == "steps" and ("Sampler" in n["class_type"] or "Scheduler" in n["class_type"]):
                steps.append((nid, v))
    for i, (nid, v) in enumerate(steps):
        add({"id": "steps", "type": "slider", "label": "Steps" if len(steps) == 1 else f"Steps ({i + 1})",
             "min": max(1, v // 2), "max": max(v * 2, 4), "step": 1, "default": v, "bind": [{"node": nid, "field": "steps"}]})
    for nid in order:
        n = api[nid]
        if "Latent" not in n["class_type"] or not n["class_type"].startswith("Empty"):
            continue
        for k in ("width", "height"):
            v = n["inputs"].get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                opts = sorted(set(SIZE_OPTIONS) | {v})
                add({"id": k, "type": "select", "label": k.capitalize(), "default": v,
                     "options": [{"value": o, "label": str(o)} for o in opts], "bind": [{"node": nid, "field": k}]})
        if n["class_type"].startswith("Empty") and isinstance(n["inputs"].get("length"), int):
            v = n["inputs"]["length"]
            add({"id": "frames", "type": "slider", "label": "Frames", "min": 1, "max": max(v * 2, 2), "step": 1,
                 "default": v, "bind": [{"node": nid, "field": "length"}]})
    for nid in order:
        n = api[nid]
        if n["class_type"] == "ResolutionSelector" and isinstance(n["inputs"].get("aspect_ratio"), str):
            spec = ((info.get("ResolutionSelector") or {}).get("input", {}).get("required", {}) or {}).get("aspect_ratio")
            choices = spec[0] if spec and isinstance(spec[0], list) else [n["inputs"]["aspect_ratio"]]
            add({"id": "aspect", "type": "select", "label": "Aspect ratio", "default": n["inputs"]["aspect_ratio"],
                 "options": [{"value": c, "label": c} for c in choices], "bind": [{"node": nid, "field": "aspect_ratio"}]})
    # primitives somebody named
    for nid in order:
        n = api[nid]
        kind = NUMBER_PRIMITIVES.get(n["class_type"])
        v = n["inputs"].get("value")
        label = plain_label(title_of(n), n["class_type"])
        if not kind or label is None or is_link(v):
            continue
        if kind == "bool" and isinstance(v, bool):
            add({"id": slug(label), "type": "toggle", "label": label, "default": v, "bind": [{"node": nid, "field": "value"}]})
        elif kind in ("int", "float") and isinstance(v, (int, float)) and not isinstance(v, bool):
            hi = max(v * 2, 1) if v > 0 else 10
            add({"id": slug(label), "type": "slider", "label": label, "min": 0 if v <= 0 else (1 if kind == "int" else 0),
                 "max": hi, "step": 1 if kind == "int" else 0.05, "default": v, "bind": [{"node": nid, "field": "value"}]})
            report["check"].append(f'"{label}" ({nid}) became a slider {0 if v <= 0 else 1}–{hi}: keep it only if a user should change it')
    if seeds:
        add({"id": "seed", "type": "seed", "label": "Seed", "default": -1, "help": "-1 picks a random seed", "bind": seeds})
        if len(seeds) > 1:
            report["check"].append(f"the seed writes {len(seeds)} nodes ({', '.join(s['node'] for s in seeds)}): "
                                   "keep only the ones that should change between runs")

    # outputs
    outputs = []
    for nid in order:
        n = api[nid]
        if n["class_type"] == "PreviewImage":
            n["class_type"] = "SaveImage"
            n["_meta"] = {"title": "Save Image"}
            report["check"].append(f"PreviewImage {nid} became a SaveImage")
        if n["class_type"] in SAVE_TYPES:
            n["inputs"]["filename_prefix"] = f"freefield/{app_id}"
            t = SAVE_TYPES[n["class_type"]]
            outputs.append({"node": nid, "type": t, "label": t.capitalize()})
    if len(outputs) > 1:
        report["check"].append(f"{len(outputs)} outputs: the first one listed is the app's main result")

    # models
    models: list[dict] = []
    seen_files: set[str] = set()
    for nid in order:
        n = api[nid]
        for k, v in n["inputs"].items():
            if not isinstance(v, str) or not v.lower().endswith(MODEL_EXT):
                continue
            base = v.replace("\\", "/").rsplit("/", 1)[-1]
            if base in seen_files:
                continue
            seen_files.add(base)
            guess_dir, guess_phase = next(((d, p) for rx, d, p in LOADER_GUESS if rx.search(n["class_type"])),
                                          ("diffusion_models", "denoise"))
            known = files.get(base)
            if known:
                m = {"repo": known["repo"], "file": known["file"], "dir": known["dir"], "gb": known["gb"],
                     "phase": phases.get(base, guess_phase)}
                if known.get("gated"):
                    m["gated"] = True
                if known.get("license"):
                    m["license"] = known["license"]
                models.append(m)
                report["models"].append(f"{base}  {known['repo']}  {known['gb']} GB  ({m['phase']})")
            else:
                models.append({"repo": "TODO/unknown", "file": base, "dir": guess_dir, "gb": 0.001, "phase": guess_phase})
                report["unknown"].append(f"{base}  (loaded by {n['class_type']} {nid}.{k}; folder guessed as {guess_dir})")

    # pack
    known_bases = [m["file"].rsplit("/", 1)[-1] for m in models if m["repo"] != "TODO/unknown"]
    pack = app_id
    if known_bases and not report["unknown"]:
        common = set.intersection(*(in_packs[b] for b in known_bases))
        if common:
            sizes = {p: sum(1 for s in in_packs.values() if p in s) for p in common}
            pack = min(common, key=lambda p: (sizes[p], p))
    report["pack"] = pack if pack != app_id else f"{app_id} (new: no existing pack holds every model)"

    if not section:
        kinds = {o["type"] for o in outputs}
        section = "video" if "video" in kinds else "audio" if kinds == {"audio"} else "image"
    notes = ["Imported by tools/import_workflow.py: check every input and model before marking it ready."]
    if report["unknown"]:
        notes.append("Models with repo TODO/unknown: find their Hugging Face repo, path and size, then run "
                     "python tools/catalog.py all.")
    app = {
        "$schema": "../../schema/app.schema.json",
        "id": app_id,
        "name": (name or app_id.replace("-", " ").title())[:40],
        "section": section,
        "pack": pack,
        "status": "draft",
        "summary": f"Imported from {source}."[:160],
        "workflow": "workflow.api.json",
        "source": {"template": source, "notes": " ".join(notes)},
        "inputs": inputs,
        "outputs": outputs,
        "models": models,
    }
    report["inputs"] = [f"{i['id']} ({i['type']}) → " + ", ".join(f"{b['node']}.{b['field']}" for b in i["bind"])
                        for i in inputs]
    report["outputs"] = [f"{o['type']} ← {o['node']} ({api[o['node']]['class_type']})" for o in outputs]
    if not outputs:
        report["check"].append("no Save node: the app needs at least one output")
    return app, api, report


def validate(app: dict, api: dict, root: Path = ROOT) -> tuple[list[str], list[str]] | None:
    """Run the repo's validator on this app alone, in a scratch copy of the repo. (errors, warnings), or None."""
    node = shutil.which("node")
    if not node or not (root / "node_modules").exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        shutil.copytree(root / "server", t / "server")
        shutil.copytree(root / "schema", t / "schema")
        shutil.copy(root / "package.json", t / "package.json")
        (t / "node_modules").symlink_to(root / "node_modules", target_is_directory=True)
        d = t / "apps" / app["id"]
        d.mkdir(parents=True)
        (d / "app.json").write_text(json.dumps(app, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (d / "workflow.api.json").write_text(json.dumps(api, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        r = subprocess.run([node, "--experimental-strip-types", "--disable-warning=ExperimentalWarning",
                            "server/cli.ts", "validate"], cwd=t, capture_output=True, text=True, encoding="utf-8")
    lines = r.stdout.splitlines()
    errors = [l[2:] for l in lines if l.startswith("✗ ")]
    warnings = [l[2:] for l in lines if l.startswith("! ")]
    if r.returncode != 0 and not errors:
        errors = [(r.stderr or r.stdout).strip() or f"validator exited {r.returncode}"]
    return errors, warnings


def print_report(app: dict, report: dict, checked, out: Path) -> None:
    print(f"{app['id']}: {len(app['inputs'])} inputs, {len(app['outputs'])} outputs, {len(app['models'])} models → {out}")
    for title, key in (("inputs", "inputs"), ("outputs", "outputs"), ("models matched in packs/", "models"),
                       ("models Freefield does not know", "unknown"), ("check by hand", "check")):
        if report[key]:
            print(f"  {title}:")
            for line in report[key]:
                print(f"    - {line}")
    print(f"  pack: {report['pack']}")
    if checked is None:
        print("  validator: not run (node or node_modules missing)")
    else:
        errors, warnings = checked
        print(f"  validator: {len(errors)} errors, {len(warnings)} warnings")
        for line in errors + warnings:
            print(f"    {line}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--id", required=True, help="app id: lowercase words joined by - (the folder name)")
    ap.add_argument("--name", help="name shown in the UI (default: the id in title case)")
    ap.add_argument("--section", choices=["image", "video", "audio", "utility"], help="default: from the outputs")
    ap.add_argument("--out", type=Path, help="folder to write (default: apps/<id>)")
    ap.add_argument("--object-info", type=Path, help="GET /object_info of a ComfyUI, for UI workflows and option lists")
    ap.add_argument("--force", action="store_true", help="overwrite the folder when it exists")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", a.id):
        print("--id must be lowercase letters and digits joined by -", file=sys.stderr)
        return 2
    out = a.out or ROOT / "apps" / a.id
    if (out / "app.json").exists() and not a.force:
        print(f"{out / 'app.json'} exists; pass --force to overwrite", file=sys.stderr)
        return 2
    try:
        api, notes = load_workflow(a.workflow, a.object_info)
    except (ValueError, ConversionError, OSError) as e:
        print(f"{a.workflow}: {e}", file=sys.stderr)
        return 1
    info_path = a.object_info or ROOT / "tools" / "object_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    app, api, report = build(api, a.id, a.name, a.section, a.workflow.name, object_info=info)
    report["check"] = notes + report["check"]
    checked = validate(app, api)
    out.mkdir(parents=True, exist_ok=True)
    (out / "app.json").write_text(json.dumps(app, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "workflow.api.json").write_text(json.dumps(api, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_report(app, report, checked, out)
    if not app["outputs"] or (checked is not None and checked[0]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

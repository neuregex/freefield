#!/usr/bin/env python3
"""The LoRA lab's engine: run a list of cases against one ComfyUI and keep everything.

A case is an app from apps/ plus values, optional preset, raw overrides and extra LoRAs:

    {"id": "clean-plate-street", "app": "vfx-clean-plate",
     "values": {"clip": "@case:ref-street", "prompt": "..."},
     "overrides": [{"node": "5004:5606", "field": "strength_model", "value": 0.8}],
     "loras": [{"repo": "WepeNerd/LTX-Ripple", "file": "LTX25_Ripple_v11.safetensors", "strength": 1.0}]}

File values can be "asset:<name>" (a file in lab/assets) or "@case:<id>" (the first output
of an earlier case, so a text-to-video case can feed an IC-LoRA case). For every case the
lab records status, seconds, peak VRAM (polled with nvidia-smi) and copies the outputs
into results/<run_id>/<case_id>/. Between cases whose model sets differ it asks ComfyUI to
unload everything, the same policy as the gateway.

Local check against any running ComfyUI (CPU is fine for the smoke cases):
    python lab/core.py --url http://127.0.0.1:8188 --comfy-dir /path/to/ComfyUI --cases lab/cases.smoke.json --out lab/results/local
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FILE_TYPES = {"image", "video", "audio"}
ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- HTTP
def _req(url: str, payload: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{url} → HTTP {e.code}: {e.read().decode(errors='replace')[:800]}") from None


# ---------------------------------------------------------------- VRAM
class VramSampler(threading.Thread):
    """Peak GPU memory in GB since the last reset, from nvidia-smi every 0.5 s."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak_mib = 0
        self.available = shutil.which("nvidia-smi") is not None
        self.gpu_name = None
        if self.available:
            try:
                self.gpu_name = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                               capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
            except Exception:
                self.available = False
        self._halt = threading.Event()

    def run(self):
        while self.available and not self._halt.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout
                self.peak_mib = max(self.peak_mib, max(int(x) for x in out.split()))
            except Exception:
                pass
            time.sleep(0.5)

    def reset(self) -> None:
        self.peak_mib = 0

    def peak_gb(self) -> float | None:
        return round(self.peak_mib / 1024, 2) if self.available else None

    def stop(self) -> None:
        self._halt.set()


# ---------------------------------------------------------------- workflow edits
def load_app(apps_dir: Path, app_id: str) -> tuple[dict, dict]:
    manifest = json.loads((apps_dir / app_id / "app.json").read_text(encoding="utf-8"))
    if not manifest.get("workflow"):
        raise ValueError(f"{app_id} has no workflow yet")
    api = json.loads((apps_dir / app_id / manifest["workflow"]).read_text(encoding="utf-8"))
    return manifest, api


PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def render(template: str, values: dict) -> str:
    s = PLACEHOLDER.sub(lambda m: "" if values.get(m.group(1)) is None else str(values[m.group(1)]), template)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*,+", ",", s)
    return re.sub(r"\s{2,}", " ", s).strip().rstrip(",")


def set_value(value, values: dict):
    """A value in an option's or preset's sets: a string with {placeholders} is filled like a bind template."""
    return render(value, values) if isinstance(value, str) and PLACEHOLDER.search(value) else value


def resolve_values(manifest: dict, given: dict) -> dict:
    values = {}
    for inp in manifest.get("inputs", []):
        v = given.get(inp["id"], inp.get("default"))
        if inp["type"] == "seed" and v in (None, -1, "-1"):
            v = 42   # fixed, so cases are comparable
        if v is not None:
            values[inp["id"]] = v
    return values


def apply(manifest: dict, api: dict, values: dict, preset: str | None = None) -> None:
    for inp in manifest.get("inputs", []):
        if inp["id"] not in values:
            continue
        for b in inp.get("bind", []):
            api[b["node"]]["inputs"][b["field"]] = render(b["template"], values) if b.get("template") else values[inp["id"]]
        for opt in inp.get("options") or []:   # a select option can carry extra fields
            if opt["value"] == values[inp["id"]]:
                for s in opt.get("sets", []):
                    api[s["node"]]["inputs"][s["field"]] = set_value(s["value"], values)
    if preset:
        p = next(p for p in manifest.get("presets", []) if p["id"] == preset)
        for s in p["sets"]:
            api[s["node"]]["inputs"][s["field"]] = set_value(s["value"], values)


def add_loras(api: dict, loras: list[dict]) -> None:
    """Chain LoraLoaderModelOnly nodes right after the diffusion model loader."""
    unets = [i for i, n in api.items() if n["class_type"] in ("UNETLoader", "CheckpointLoaderSimple")]
    if len(unets) != 1:
        raise ValueError(f"expected one model loader, found {unets}")
    src = [unets[0], 0]
    for k, l in enumerate(loras):
        nid = f"lab_lora_{k}"
        for n in api.values():
            for f, v in n["inputs"].items():
                if v == src:
                    n["inputs"][f] = [nid, 0]
        api[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": list(src), "lora_name": l["file"].rsplit("/", 1)[-1],
                                                                     "strength_model": l.get("strength", 1.0)}, "_meta": {"title": "lab LoRA"}}
        src = [nid, 0]


def build_case(apps_dir: Path, case: dict, file_value) -> tuple[dict, dict, dict]:
    """The exact prompt a case submits: app workflow + values + preset + overrides + LoRAs.

    file_value(case_id, raw, kind) turns "@case:…", "asset:…" or a path into a file name in
    ComfyUI's input folder; kind is the input type (image, video or audio)."""
    manifest, api = load_app(apps_dir, case["app"])
    given = dict(case.get("values", {}))
    types = {i["id"]: i["type"] for i in manifest.get("inputs", [])}
    for k, v in list(given.items()):
        if types.get(k) in FILE_TYPES and isinstance(v, str):
            given[k] = file_value(case["id"], v, types[k])
    values = resolve_values(manifest, given)
    apply(manifest, api, values, case.get("preset"))
    for o in case.get("overrides", []):
        api[o["node"]]["inputs"][o["field"]] = o["value"]
    if case.get("loras"):
        add_loras(api, case["loras"])
    return manifest, api, {k: v for k, v in values.items() if types.get(k) not in FILE_TYPES}


def lora_models(loras: list[dict]) -> list[dict]:
    return [{"repo": l["repo"], "file": l["file"], "dir": "loras", "gb": l.get("gb", 0)} for l in loras]


def models_for_cases(cases: list[dict], apps_dir: Path) -> list[dict]:
    seen, out = set(), []
    for c in cases:
        manifest = json.loads((apps_dir / c["app"] / "app.json").read_text(encoding="utf-8"))
        extra = lora_models(c.get("loras", [])) + lora_models(c.get("loras_download", []))  # files swapped in by overrides
        for m in manifest.get("models", []) + extra:
            key = (m["dir"], m["file"].rsplit("/", 1)[-1])
            if key not in seen:
                seen.add(key)
                out.append(m)
    return out


# ---------------------------------------------------------------- web versions
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".gif"}
AUDIO_EXT = {".flac", ".mp3", ".wav", ".ogg", ".opus", ".m4a"}
ALPHA_PIX = re.compile(r"^(rgba|bgra|argb|abgr|ya\d|yuva|gbrap|pal8)")


def media_kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else None


def _ffmpeg(*args: str) -> bool:
    try:
        return subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, timeout=600).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _has_alpha(path: Path) -> bool:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return path.suffix.lower() == ".png"
    return bool(ALPHA_PIX.match(out))


def web_versions(src: Path, dest: Path) -> dict:
    """Small files for the gallery: a card (thumbnail), a poster for videos and a web-sized full version.

    Images become JPEG (PNG when they have transparency), videos H.264 MP4 (the card muted, 5 s,
    360 p), audio MP3 with a waveform picture as its card. Needs ffmpeg (the Modal image has it);
    without it the original file stands in for every version. Paths are relative to dest.parent.
    """
    kind = media_kind(src)
    out = {"type": kind, "card": None, "poster": None, "full": None, "source": src.name}
    if kind is None:
        return out
    dest.mkdir(parents=True, exist_ok=True)
    rel = lambda p: f"{dest.name}/{p.name}"   # noqa: E731
    if kind == "image":
        ext = ".png" if _has_alpha(src) else ".jpg"
        q = [] if ext == ".png" else ["-q:v", "3"]
        if _ffmpeg("-i", str(src), "-vf", "scale='min(640,iw)':-2", *q, str(dest / f"card{ext}")):
            out["card"] = rel(dest / f"card{ext}")
        if _ffmpeg("-i", str(src), "-vf", "scale='min(1600,iw)':-2", *q, str(dest / f"full{ext}")):
            out["full"] = rel(dest / f"full{ext}")
    elif kind == "video":
        if _ffmpeg("-i", str(src), "-t", "5", "-vf", "scale=-2:'min(360,ih)'", "-an", "-c:v", "libx264", "-preset", "medium",
                   "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest / "card.mp4")):
            out["card"] = rel(dest / "card.mp4")
        if _ffmpeg("-i", str(src), "-vf", "thumbnail,scale='min(640,iw)':-2", "-frames:v", "1", "-q:v", "3", str(dest / "poster.jpg")):
            out["poster"] = rel(dest / "poster.jpg")
        if _ffmpeg("-i", str(src), "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "medium", "-crf", "26",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest / "full.mp4")):
            out["full"] = rel(dest / "full.mp4")
    else:
        if _ffmpeg("-i", str(src), "-filter_complex", "showwavespic=s=640x160:colors=#e8ff5a:scale=sqrt", "-frames:v", "1", str(dest / "card.png")):
            out["card"] = rel(dest / "card.png")
        if _ffmpeg("-i", str(src), "-c:a", "libmp3lame", "-b:a", "160k", str(dest / "full.mp3")):
            out["full"] = rel(dest / "full.mp3")
    if out["full"] is None:   # no ffmpeg: the original is the full version
        out["full"] = src.name
    return out


# ---------------------------------------------------------------- runner
class Lab:
    def __init__(self, url: str, input_dir: Path, output_dir: Path, results_dir: Path,
                 apps_dir: Path = ROOT / "apps", assets_dir: Path = ROOT / "lab" / "assets", on_case_done=None,
                 missing: dict[str, str] | None = None):
        self.url = url.rstrip("/")
        self.missing = missing or {}   # model files that could not be downloaded → reason
        self.input_dir, self.output_dir, self.results_dir = input_dir, output_dir, results_dir
        self.apps_dir, self.assets_dir = apps_dir, assets_dir
        self.on_case_done = on_case_done or (lambda: None)
        self.outputs: dict[str, list[Path]] = {}
        self.last_key: str | None = None
        self.vram = VramSampler()
        self.vram.start()

    def _file_value(self, case_id: str, raw: str, kind: str = "") -> str:
        if raw.startswith("@case:"):
            src_id = raw[len("@case:"):]
            files = self.outputs.get(src_id) or []
            if not files:
                raise RuntimeError(f"{case_id}: case '{src_id}' produced no output to use")
            src = files[0]
        elif raw.startswith("asset:"):
            src = self.assets_dir / raw[len("asset:"):]
        else:
            src = Path(raw)
        if not src.exists():
            raise FileNotFoundError(f"{case_id}: input file {src} not found")
        name = f"lab_{case_id}_{src.name}"
        shutil.copy(src, self.input_dir / name)
        return name

    def run_case(self, case: dict) -> dict:
        cid = case["id"]
        res = {"id": cid, "app": case["app"], "status": "error", "seconds": None, "peak_vram_gb": None,
               "files": [], "error": None, "values": {}, "inputs": {}, "web": None, "loras": case.get("loras", []),
               "overrides": case.get("overrides", []), "note": case.get("note", ""), "showcase": bool(case.get("showcase"))}
        try:
            manifest, api, res["values"] = build_case(self.apps_dir, case, self._file_value)
            # where each file input came from ("@case:<id>", "asset:<name>" or a path), for the gallery
            types = {i["id"]: i["type"] for i in manifest.get("inputs", [])}
            res["inputs"] = {k: v for k, v in case.get("values", {}).items() if types.get(k) in FILE_TYPES}
            # skip, with the reason, when a file this exact prompt loads could not be downloaded
            used = {v for n in api.values() for v in n["inputs"].values() if isinstance(v, str)}
            lacking = sorted(used & set(self.missing))
            if lacking:
                res["status"] = "skipped"
                raise RuntimeError("model file(s) not downloaded: " + "; ".join(f"{n} ({self.missing[n]})" for n in lacking))
            # same rule as the gateway: unload only when the base models change, not the LoRAs
            key = "|".join(sorted(f"{m['dir']}/{m['file'].rsplit('/', 1)[-1]}" for m in manifest.get("models", [])
                                  if not m.get("optional") and m["dir"] != "loras"))
            if self.last_key is not None and key != self.last_key:
                _req(f"{self.url}/free", {"unload_models": True, "free_memory": True})
            self.last_key = key
            self.vram.reset()
            t0 = time.time()
            pid = _req(f"{self.url}/prompt", {"prompt": api, "client_id": f"lab-{uuid.uuid4().hex[:8]}"})["prompt_id"]
            deadline = t0 + case.get("timeout", 1800)
            entry = None
            while time.time() < deadline:
                hist = _req(f"{self.url}/history/{pid}")
                entry = hist.get(pid)
                if entry and entry.get("status", {}).get("completed") is not None and \
                        (entry["status"].get("completed") or entry["status"].get("status_str") == "error"):
                    break
                time.sleep(1)
            res["seconds"] = round(time.time() - t0, 1)
            res["peak_vram_gb"] = self.vram.peak_gb()
            if not entry:
                raise TimeoutError(f"no result after {case.get('timeout', 1800)} s")
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                detail = msgs[-1][1] if msgs else {}
                raise RuntimeError(f"{detail.get('node_type', '')}: {detail.get('exception_message', 'execution error')}".strip())
            out_dir = self.results_dir / cid
            out_dir.mkdir(parents=True, exist_ok=True)
            wanted = {o["node"] for o in manifest["outputs"]}
            saved = []
            for node_id, out in (entry.get("outputs") or {}).items():
                if node_id not in wanted:
                    continue
                for items in out.values():
                    if not isinstance(items, list):
                        continue
                    for it in items:
                        if isinstance(it, dict) and "filename" in it and it.get("type", "output") == "output":
                            src = self.output_dir / it.get("subfolder", "") / it["filename"]
                            if src.exists():
                                dst = out_dir / it["filename"]
                                shutil.copy(src, dst)
                                saved.append(dst)
            self.outputs[cid] = saved
            res["files"] = [p.relative_to(self.results_dir).as_posix() for p in saved]
            res["status"] = "ok" if saved else "no-output"
            if saved:
                web = web_versions(saved[0], out_dir / "web")
                res["web"] = {k: (f"{cid}/{v}" if k in ("card", "poster", "full") and v else v) for k, v in web.items()}
        except Exception as e:  # keep going: one broken LoRA must not stop the batch
            res["error"] = f"{type(e).__name__}: {e}"
        return res

    def run_all(self, cases: list[dict]) -> list[dict]:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        results = []
        meta = {"gpu": self.vram.gpu_name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": len(cases)}
        (self.results_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        with open(self.results_dir / "results.jsonl", "a", encoding="utf-8") as f:
            for c in cases:
                r = self.run_case(c)
                results.append(r)
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                flag = "✓" if r["status"] == "ok" else "✗"
                vram = f"{r['peak_vram_gb']:.1f} GB" if r["peak_vram_gb"] is not None else "n/a"
                print(f"{flag} {r['id']:<34} {r['app']:<18} {r['seconds'] or 0:>7.1f}s  peak {vram:>8}  {r['error'] or ''}")
                self.on_case_done()
        self.vram.stop()
        return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--comfy-dir", type=Path, required=True)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    a = ap.parse_args(argv)
    cases = json.loads(a.cases.read_text(encoding="utf-8"))["cases"]
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    lab = Lab(a.url, a.comfy_dir / "input", a.comfy_dir / "output", a.out)
    results = lab.run_all(cases)
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

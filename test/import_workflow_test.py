"""tools/import_workflow.py against workflows whose app.json was written by hand.

    python test/import_workflow_test.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import import_workflow as iw  # tools/import_workflow.py

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def binds(app):
    return {(b["node"], b["field"]) for i in app["inputs"] for b in i.get("bind", [])}


def kinds(app):
    return {(b["node"], b["field"]): i["type"] for i in app["inputs"] for b in i.get("bind", [])}


def files(app, required_only=False):
    return {m["file"].rsplit("/", 1)[-1] for m in app["models"] if not (required_only and m.get("optional"))}


def imported(app_id):
    hand = json.loads((ROOT / "apps" / app_id / "app.json").read_text(encoding="utf-8"))
    api = json.loads((ROOT / "apps" / app_id / "workflow.api.json").read_text(encoding="utf-8"))
    app, out_api, report = iw.build(api, f"imp-{app_id}", None, None, "workflow.api.json")
    return hand, app, out_api, report


# the same inputs, outputs and models as the hand-written app
for app_id in ("z-image", "remove-bg", "edit"):
    hand, app, api, report = imported(app_id)
    check(binds(app) == binds(hand), f"{app_id}: inputs write the same node fields ({sorted(binds(app))})")
    check(all(kinds(app)[k] == t for k, t in kinds(hand).items()), f"{app_id}: each input has the hand-written type")
    check({o["node"] for o in app["outputs"]} == {o["node"] for o in hand["outputs"]}, f"{app_id}: same output nodes")
    check(files(app) == files(hand), f"{app_id}: same model files")
    check(app["pack"] == hand["pack"], f"{app_id}: pack {app['pack']} (hand-written: {hand['pack']})")
    check(all(m["repo"] == h["repo"] and m["dir"] == h["dir"] and m["phase"] == h["phase"]
              for m in app["models"] for h in hand["models"] if m["file"] == h["file"]), f"{app_id}: repo, folder and phase match")
    check(app["status"] == "draft" and not report["unknown"], f"{app_id}: a draft with no unknown model")
    check(all(n["inputs"]["filename_prefix"] == f"freefield/imp-{app_id}" for n in api.values() if "filename_prefix" in n["inputs"]),
          f"{app_id}: outputs saved under freefield/imp-{app_id}")

# a bigger graph (LTX-2.5 image to video): everything the hand-written app exposes, plus what it chose to hide
hand, app, api, report = imported("video")
check(binds(hand) <= binds(app), "video: every hand-written binding is found")
check(files(app) == files(hand), "video: same model files (the optional prompt enhancer included)")
check({o["node"] for o in app["outputs"]} == {"75"}, "video: the SaveVideo output")
check(app["section"] == "video" and app["pack"] == "video-ltx25", "video: section and pack from the outputs and models")
check(any("seed writes 2 nodes" in c for c in report["check"]), "video: the report says the seed has two targets")
check(next(i for i in app["inputs"] if i["id"] == "prompt")["bind"] == [{"node": "398:376", "field": "value"}],
      "video: the prompt is the PrimitiveStringMultiline upstream of the switch")

# a file Freefield does not know is marked, never given a made-up repo
api = json.loads((ROOT / "apps" / "z-image" / "workflow.api.json").read_text(encoding="utf-8"))
api["57:28"]["inputs"]["unet_name"] = "someone_elses_model.safetensors"
app, _, report = iw.build(api, "imp-unknown", None, None, "x.json")
m = next(m for m in app["models"] if m["file"] == "someone_elses_model.safetensors")
check(m["repo"] == "TODO/unknown" and m["dir"] == "diffusion_models", "unknown file: TODO repo, folder from the loader")
check(report["unknown"] and app["pack"] == "imp-unknown", "unknown file: reported, and the app gets its own pack")

# a UI workflow (nodes + links) goes through tools/ui2api.py
ui = {"nodes": [
    {"id": 1, "type": "LoadImage", "mode": 0, "inputs": [], "widgets_values": ["photo.png", "image"],
     "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [1]}, {"name": "MASK", "type": "MASK", "links": []}]},
    {"id": 2, "type": "PreviewImage", "mode": 0, "inputs": [{"name": "images", "type": "IMAGE", "link": 1}], "widgets_values": []},
], "links": [[1, 1, 0, 2, 0, "IMAGE"]]}
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "ui.json"
    p.write_text(json.dumps(ui), encoding="utf-8")
    api, notes = iw.load_workflow(p, None)
    app, api, report = iw.build(api, "imp-ui", None, None, "ui.json")
    check(api["2"]["class_type"] == "SaveImage" and app["outputs"] == [{"node": "2", "type": "image", "label": "Image"}],
          "UI workflow: converted, PreviewImage became the output")
    check(binds(app) == {("1", "image")}, "UI workflow: the LoadImage is the image input")

    # the command end to end: files written, validator run on the new app alone
    out = Path(tmp) / "app"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "import_workflow.py"), str(ROOT / "apps" / "edit" / "workflow.api.json"),
                        "--id", "imp-edit", "--name", "Imported edit", "--out", str(out)], capture_output=True, text=True)
    check(r.returncode == 0, f"command exits 0 ({r.stdout.splitlines()[-1] if r.stdout else r.stderr.strip()})")
    written = json.loads((out / "app.json").read_text(encoding="utf-8"))
    check(written["name"] == "Imported edit" and (out / "workflow.api.json").exists(), "command writes app.json and workflow.api.json")
    checked = iw.validate(written, json.loads((out / "workflow.api.json").read_text(encoding="utf-8")))
    check(checked is None or not checked[0], f"the written app validates ({checked})")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "import_workflow.py"), str(ROOT / "apps" / "edit" / "workflow.api.json"),
                        "--id", "imp-edit", "--out", str(out)], capture_output=True, text=True)
    check(r.returncode == 2, "an existing folder is not overwritten without --force")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "import_workflow.py"), str(p), "--id", "Bad_Id"], capture_output=True, text=True)
    check(r.returncode == 2, "a bad id is refused")

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)

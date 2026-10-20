#!/usr/bin/env python3
"""Build every apps/<id>/workflow.api.json from official sources, reproducibly.

Each app starts from an official workflow (ComfyUI's templates package or Lightricks'
ComfyUI-LTXVideo examples), is converted to API format with ui2api, and then gets a few
explicit edits (drop UI-only nodes, swap to int8 weights, remove the LTX cloud text
encoder, set the LoRA). Nothing is edited by hand, so a new ComfyUI release means
re-running this script.

    pip download --no-deps comfyui-workflow-templates-json==0.1.115 -d /tmp/t && unzip -q /tmp/t/*.whl -d /tmp/t
    git clone https://github.com/Lightricks/ComfyUI-LTXVideo /tmp/ltx   (commit 44c8a36)
    git clone https://github.com/Comfy-Org/comfy-reshoot /tmp/reshoot   (commit dc53fc7)
    python tools/build_apps.py --templates /tmp/t/comfyui_workflow_templates_json/templates \
        --ltx /tmp/ltx/example_workflows/2.5 --reshoot /tmp/reshoot/workflows --object-info tools/object_info.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui2api import convert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Api = dict[str, dict]


# ---------------------------------------------------------------- graph edits
def is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def drop(api: Api, *ids: str) -> None:
    """Remove nodes and any input that pointed at them."""
    for i in ids:
        if i not in api:
            raise KeyError(f"drop: node {i} not in workflow")
        del api[i]
    gone = set(ids)
    for node in api.values():
        for k, v in list(node["inputs"].items()):
            if is_link(v) and v[0] in gone:
                del node["inputs"][k]


def drop_preview(api: Api, node: str) -> None:
    """PreviewAny shows text in the UI. Drop it only when nothing reads its output:
    some templates use it as an any-to-string converter in the middle of the graph."""
    used = any(is_link(v) and v[0] == node for n in api.values() for v in n["inputs"].values())
    if not used:
        drop(api, node)


def put(api: Api, node: str, field: str, value) -> None:
    if node not in api:
        raise KeyError(f"set: node {node} not in workflow")
    api[node]["inputs"][field] = value


def rewire(api: Api, old: list, new: list) -> None:
    """Point every consumer of output `old` ([node, slot]) at `new`."""
    for node in api.values():
        for k, v in node["inputs"].items():
            if is_link(v) and v[0] == old[0] and v[1] == old[1]:
                node["inputs"][k] = list(new)


def find(api: Api, class_type: str, **match) -> str:
    hits = [i for i, n in api.items() if n["class_type"] == class_type
            and all(n["inputs"].get(k) == v for k, v in match.items())]
    if len(hits) != 1:
        raise LookupError(f"expected one {class_type} {match or ''}, found {hits}")
    return hits[0]


def swap_files(api: Api, mapping: dict[str, str]) -> None:
    for node in api.values():
        for k, v in node["inputs"].items():
            if isinstance(v, str) and v in mapping:
                node["inputs"][k] = mapping[v]


def to_save_image(api: Api, node: str, prefix: str) -> None:
    api[node]["class_type"] = "SaveImage"
    api[node]["inputs"]["filename_prefix"] = prefix
    api[node]["_meta"] = {"title": "Save Image"}


def add_lora_after(api: Api, model_node: str, lora: str, strength: float = 1.0, nid: str = "ff_lora") -> None:
    rewire(api, [model_node, 0], [nid, 0])
    api[nid] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": [model_node, 0], "lora_name": lora, "strength_model": strength},
                "_meta": {"title": "Freefield LoRA"}}


def prefix_outputs(api: Api, app_id: str) -> None:
    for node in api.values():
        if "filename_prefix" in node["inputs"]:
            node["inputs"]["filename_prefix"] = f"freefield/{app_id}"


# ---------------------------------------------------------------- LTX specifics
LTX_INT8 = {
    "ltx-2.5-22b-distilled-transformer-bf16.safetensors": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    "gemma4_e2b_it_bf16.safetensors": "gemma4_e2b_it_int8_convrot.safetensors",
}


def ltx_local_text(api: Api) -> None:
    """Make a Lightricks LTX-2.5 example fully local.

    Their examples can send the prompt to the LTX cloud API (GemmaAPITextEncode) when an
    API key is set; a switch picks that branch or the local Gemma 4 encoder. Every
    consumer of those switches is pointed at the local branch and the API nodes are
    removed. Weights are swapped to int8 so the DiT fits a 24 GB card by phases.
    """
    for k in list(LTX_INT8):  # the examples store long bf16 names; normalise them first
        for node in api.values():
            for f, v in node["inputs"].items():
                if isinstance(v, str) and v.startswith(k.replace(".safetensors", "")):
                    node["inputs"][f] = k
    swap_files(api, LTX_INT8)
    api_nodes = {i for i, n in api.items() if n["class_type"] == "GemmaAPITextEncode"}
    switches = [i for i, n in api.items() if n["class_type"] == "ComfySwitchNode"
                and any(is_link(v) and v[0] in api_nodes for v in n["inputs"].values())]
    for sw in switches:
        local = api[sw]["inputs"].get("on_false")   # the API branch is on_true, taken only with a key
        assert is_link(local) and local[0] not in api_nodes, (sw, local)
        rewire(api, [sw, 0], local)
    drop(api, *api_nodes, *switches, *[i for i, n in api.items() if n["class_type"] == "StringContains"])
    for p in [i for i, n in api.items() if n["class_type"] == "PreviewAny"]:
        drop_preview(api, p)


def ltx_v2v_local(api: Api, lora_file: str) -> None:
    """Lightricks' V2V IC-LoRA example: local text, first frame from the clip, chosen IC-LoRA."""
    ltx_local_text(api)
    # first frame: take frame 0 of the reference instead of a separate upload (it stays bypassed)
    load_image = find(api, "LoadImage")
    components = find(api, "GetVideoComponents")
    api["ff_first_frame"] = {"class_type": "ImageFromBatch",
                             "inputs": {"image": [components, 0], "batch_index": 0, "length": 1},
                             "_meta": {"title": "First frame of the reference"}}
    rewire(api, [load_image, 0], ["ff_first_frame", 0])
    drop(api, load_image)
    put(api, find(api, "LTXICLoRALoaderModelOnly"), "lora_name", lora_file)


CAMERAMAN = "LTX2.3-22B_IC-LoRA-Cameraman_v2_14000.safetensors"


def ltx_cameraman(api: Api) -> None:
    """V2V IC-LoRA example used the other way round: the clip only lends its camera move.

    Cseti's Cameraman v2 IC-LoRA (trained on LTX-2.3) copies the camera motion of the guide
    clip. The start frame is the user's own image (the example's LoadImage stays), always on,
    at 0.6 strength as the LoRA card recommends so the camera has room to move.
    """
    ltx_local_text(api)
    put(api, find(api, "LTXICLoRALoaderModelOnly"), "lora_name", CAMERAMAN)
    use_image = "5014:5506"
    assert api[use_image]["class_type"] == "PrimitiveBoolean", api[use_image]
    put(api, use_image, "value", True)
    put(api, find(api, "LTXVImgToVideoInplace"), "strength", 0.6)


def ltx_a2v_local(api: Api) -> None:
    """Lightricks' audio-to-video example: local text, and the portrait is always used."""
    ltx_local_text(api)
    use_image = "5014:5506"
    assert api[use_image]["class_type"] == "PrimitiveBoolean", api[use_image]
    put(api, use_image, "value", True)


# ---------------------------------------------------------------- recipes
SMOKE: Api = {
    "1": {"class_type": "EmptyImage", "inputs": {"width": 256, "height": 256, "batch_size": 1, "color": 0x2A6F97},
          "_meta": {"title": "Solid color"}},
    "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "freefield/smoke"},
          "_meta": {"title": "Save Image"}},
}


USED_TYPES: set[str] = set()


def _collect_types(ui: dict) -> None:
    for n in ui.get("nodes", []):
        USED_TYPES.add(n["type"])
    for sg in (ui.get("definitions") or {}).get("subgraphs", []):
        for n in sg.get("nodes", []):
            USED_TYPES.add(n["type"])


SMOKE_INVERT: Api = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}, "_meta": {"title": "Load Image"}},
    "2": {"class_type": "ImageInvert", "inputs": {"image": ["1", 0]}, "_meta": {"title": "Invert"}},
    "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "freefield/smoke-invert"},
          "_meta": {"title": "Save Image"}},
}


def recipes(templates: Path, ltx: Path, info: dict, reshoot: Path | None = None) -> dict[str, Api]:
    def load(path: Path) -> Api:
        ui = json.loads(path.read_text(encoding="utf-8"))
        _collect_types(ui)
        api, warnings = convert(ui, info)
        for w in warnings:
            print(f"  [{path.name}] {w}")
        return api

    def tpl(name: str) -> Api:
        return load(templates / name)

    def ltxwf(name: str) -> Api:
        return load(ltx / name)

    out: dict[str, Api] = {"smoke": json.loads(json.dumps(SMOKE)), "smoke-invert": json.loads(json.dumps(SMOKE_INVERT))}

    z = tpl("image_z_image_turbo_int8.json")
    out["z-image"] = z
    out["cinema-studio"] = json.loads(json.dumps(z))

    e = tpl("image_flux3_klein_distilled_image_edit.json")
    # keep load → reference latent → sample → save; drop the bounding-box layout tool,
    # the 9B prompt upsampler and UI previews. The prompt goes straight into node 4.
    drop(e, "18", "33", "34", "44", "46", "47", "48", "49", "50", "51", "52")
    put(e, "4", "text", "Change the jacket to deep red leather, keep everything else the same.")
    out["edit"] = e
    out["character"] = json.loads(json.dumps(e))   # same pipeline; the manifest wraps the prompt in a template
    out["product-shot"] = json.loads(json.dumps(e))  # same again, with product-photography scenes

    u = tpl("utility_seedvr2_3b_int8_upscale_image.json")
    drop(u, find(u, "ImageCompare"))
    out["upscale"] = u
    out["upscale-video"] = tpl("utility_seedvr2_3b_int8_upscale_video.json")

    b = tpl("utility_birefnet_remove_background.json")
    to_save_image(b, find(b, "PreviewImage"), "freefield/remove-bg")
    drop(b, find(b, "MaskPreview"))
    out["remove-bg"] = b

    out["video"] = tpl("video_ltx2_5_i2v.json")
    out["speak"] = tpl("video_ltx2_5_i2v.json")   # LTX-2.5 voices a quoted line itself; the manifest builds the prompt
    out["video-t2v"] = tpl("video_ltx2_5_t2v.json")

    t = tpl("video_ltx2_5_flf2v.json")
    add_lora_after(t, find(t, "UNETLoader"), "ltx2.3-transition.safetensors", 1.0)
    out["transitions"] = t

    for app_id, lora in [("vfx-clean-plate", "ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors"),
                         ("vfx-day-to-night", "ltx-2.5-22b-ic-lora-day-to-night-0.9.safetensors"),
                         ("vfx-water", "ltx-2.5-22b-ic-lora-water-simulation-0.9.safetensors")]:
        v = ltxwf("LTX-2.5_V2V_ICLoRA_Single_Stage_Distilled.json")
        ltx_v2v_local(v, lora)
        out[app_id] = v

    cam = ltxwf("LTX-2.5_V2V_ICLoRA_Single_Stage_Distilled.json")
    ltx_cameraman(cam)
    out["camera-copy"] = cam

    talking = ltxwf("LTX-2.5_A2V_Two_Stage_Distilled.json")
    ltx_a2v_local(talking)
    out["talking"] = talking

    cm = tpl("video_wan2_2_14B_fun_camera.json")
    # The template's 4-step Lightning variant is bypassed; its LoRAs come back at strength 0, which
    # ComfyUI skips without loading the file. The app's "fast" preset turns them on.
    add_lora_after(cm, find(cm, "UNETLoader", unet_name="wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors"),
                   "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", 0.0, nid="ff_lora_high")
    add_lora_after(cm, find(cm, "UNETLoader", unet_name="wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors"),
                   "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", 0.0, nid="ff_lora_low")
    out["camera-moves"] = cm

    out["style-reference"] = tpl("image_krea2_turbo_int8_image_style_reference.json")   # Krea 2 Turbo + ostris' style LoRA, as shipped
    st = tpl("image_krea2_turbo_t2i_int8.json")
    # the template's own "use LoRA" switch (it also appends the trigger to the prompt) goes on;
    # the app's style picker writes the trigger and swaps the LoRA file
    put(st, find(st, "PrimitiveBoolean", value=False), "value", True)
    put(st, find(st, "LoraLoaderModelOnly"), "lora_name", "krea2_softwatercolor.safetensors")
    out["styles"] = st
    out["smooth"] = tpl("utility_video_frame_interpolation.json")       # FILM frame interpolation, as shipped
    rc = tpl("video_wan21_scail2_character_replacement_int8.json")
    # keep the first segment (81 frames); the template's "extend" subgraph needs a clip of 157+ frames
    # and fails on shorter ones, so it goes, with the nodes that only joined the two segments
    drop(rc, *[i for i in rc if i.startswith("262:")], "263", "264", "265", "269", "270", "271")
    out["recast"] = rc
    out["relight"] = tpl("image_qwen_image_edit_2509_relight.json")   # Qwen Image Edit 2509 + Relight + Lightning LoRAs, as shipped

    out["music"] = tpl("audio_minimax_music_3.json")
    out["sfx"] = tpl("audio_stable_audio_3_medium.json")
    out["motion-transfer"] = tpl("video_wan_animate2_distilled.json")
    if reshoot:
        # Comfy's own reference app (Comfy-Org/comfy-reshoot, MIT), already in API format
        out["reshoot"] = json.loads((reshoot / "generate.api.json").read_text(encoding="utf-8"))
    for app_id, api in out.items():
        prefix_outputs(api, app_id)
        for n in [i for i, node in api.items() if node["class_type"] == "PreviewAny"]:
            drop_preview(api, n)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", type=Path, required=True, help="comfyui_workflow_templates_json/templates folder")
    ap.add_argument("--ltx", type=Path, required=True, help="ComfyUI-LTXVideo/example_workflows/2.5 folder")
    ap.add_argument("--object-info", type=Path, default=ROOT / "tools" / "object_info.json")
    ap.add_argument("--reshoot", type=Path, help="comfy-reshoot/workflows folder (git clone https://github.com/Comfy-Org/comfy-reshoot)")
    ap.add_argument("--only", nargs="*", help="build only these app ids")
    ap.add_argument("--save-subset", type=Path, help="write the node definitions these recipes need to this file")
    a = ap.parse_args(argv)
    info = json.loads(a.object_info.read_text(encoding="utf-8"))
    built = recipes(a.templates, a.ltx, info, a.reshoot)
    if a.save_subset:
        keep = {t: info[t] for t in sorted(USED_TYPES | {n["class_type"] for api in built.values() for n in api.values()}) if t in info}
        a.save_subset.write_text(json.dumps(keep, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"{a.save_subset}: {len(keep)} node definitions")
    for app_id, api in built.items():
        if a.only and app_id not in a.only:
            continue
        d = ROOT / "apps" / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "workflow.api.json").write_text(json.dumps(api, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"apps/{app_id}/workflow.api.json  {len(api)} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

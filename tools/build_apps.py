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
EFFECT_LORA = "robot_face_reveal_35_epochs.safetensors"   # Remade-AI's Robot Face Reveal: the effects app's default option


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


def ltx_sdr_to_hdr(api: Api) -> None:
    """Lightricks' SDR → HDR IC-LoRA example: int8 DiT, no EXR dump, HLG master from core nodes.

    The scene-embeddings file replaces the text encoder, so there is no Gemma at all. The
    example's LTXVSaveHLG encodes HEVC through PyAV and reports no file to the API, so the
    gateway could never collect it; the same master (Rec.2020 / HLG, 10-bit) comes out of
    ImageColorSpace (ACEScct → HLG) + CreateVideo/SaveVideo in HDR, which do report it. The
    example's tone-mapped sRGB preview stays as the second output.
    """
    swap_files(api, LTX_INT8)
    put(api, "9012", "save_exr", False)
    drop(api, "9013")
    # the example keeps the clip's own size; a short-side resize (the app's "Resolution") goes after the
    # SDR → ACEScct mapping and before the example's round-to-32, where its note says to resize
    work = find(api, "LTXVSDRToHDRWorkingSpace")
    rewire(api, [work, 0], ["ff_resize", 0])
    api["ff_resize"] = {"class_type": "ResizeImageMaskNode",
                        "inputs": {"input": [work, 0], "resize_type": "scale shorter dimension", "resize_type.shorter_size": 720,
                                   "scale_method": "lanczos"},
                        "_meta": {"title": "Resolution (short side)"}}
    decode, source = "5518:5538", "5548:9006"
    assert api[decode]["class_type"] == "VAEDecodeTiled" and api[source]["class_type"] == "GetVideoComponents"
    api["ff_hlg"] = {"class_type": "ImageColorSpace",
                     "inputs": {"image": [decode, 0], "source": "HDR ACEScct", "destination": "HDR"},
                     "_meta": {"title": "ACEScct → Rec.2020 HLG"}}
    api["ff_hdr_video"] = {"class_type": "CreateVideo",
                           "inputs": {"images": ["ff_hlg", 0], "fps": [source, 2], "audio": [source, 1],
                                      "bit_depth": "auto", "color_space": "HDR", "codec": "none"},
                           "_meta": {"title": "HDR video (HLG, 10-bit)"}}
    preview = find(api, "SaveVideo")
    api["ff_hdr_save"] = {"class_type": "SaveVideo", "inputs": {**api[preview]["inputs"], "video": ["ff_hdr_video", 0]},
                          "_meta": {"title": "Save HDR master"}}


INGREDIENTS = "ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors"   # the example names the 2.3 file; the 2.5 one exists
IN_OUTPAINTING = "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"   # only a 2.3 file; Lightricks' own 2.5 example uses it
UNION_CONTROL = "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"   # same: 2.3 file, 2.5 example
DUBIT = "ltx-2.3-22b-ic-lora-dubit-0.9.safetensors"   # 2.3 file; Lightricks' example is 2.3-only, so this is a port (see ltx_v2v_local)


# Custom nodes in Lightricks' Union Control example (Video Depth Anything, comfyui_controlnet_aux): stand-ins
# with their widget order so the converter can read the graph; ltx_union_control drops them all.
UNION_STANDINS = {
    "VideoDepthAnythingProcess": {"input": {"required": {"vda_model": ["VDA_MODEL"], "images": ["IMAGE"], "input_size": ["INT", {}],
                                                         "max_res": ["INT", {}], "precision": [["fp16", "fp32"]]}},
                                  "output": ["IMAGE"], "output_name": ["IMAGE"]},
    "LoadVideoDepthAnythingModel": {"input": {"required": {"model": [["video_depth_anything_vits.pth"]]}},
                                    "output": ["VDA_MODEL"], "output_name": ["vda_model"]},
    "VideoDepthAnythingOutput": {"input": {"required": {"depths": ["IMAGE"], "colormap": [["gray"]]}},
                                 "output": ["IMAGE"], "output_name": ["IMAGE"]},
    "CannyEdgePreprocessor": {"input": {"required": {"image": ["IMAGE"], "low_threshold": ["INT", {}], "high_threshold": ["INT", {}],
                                                     "resolution": ["INT", {}]}},
                              "output": ["IMAGE"], "output_name": ["IMAGE"]},
    "DWPreprocessor": {"input": {"required": {"image": ["IMAGE"], "detect_hand": [["enable", "disable"]], "detect_body": [["enable", "disable"]],
                                              "detect_face": [["enable", "disable"]], "resolution": ["INT", {}],
                                              "bbox_detector": [["yolox_l.onnx"]], "pose_estimator": [["dw-ll_ucoco_384_bs5.torchscript.pt"]],
                                              "scale_stick_for_xinsr_cn": [["enable", "disable"]]}},
                       "output": ["IMAGE", "POSE_KEYPOINT"], "output_name": ["IMAGE", "POSE_KEYPOINT"]},
}


def ltx_dub(api: Api) -> None:
    """DubIt on LTX-2.5: the V2V IC-LoRA example with the DubIt LoRA and a fresh audio latent.

    Lightricks' DubIt workflow is 2.3-only (dev checkpoint + distilled LoRA), but its shape is the
    V2V one: the clip is the guide, its own audio the speaker reference (ref tokens), the new words
    come in the prompt. Two differences from the V2V example, which only *keeps* the clip's audio: it
    starts the sampler from that audio with noise_mask 0 ("frozen_audio"), so the first run
    (20261022-181155-h100) came back with the old words, and it never attaches the reference tokens
    (the node's conditioning outputs hang loose). DubIt's 2.3 example starts from an empty audio latent
    and feeds the guider the conditioning with the reference tokens, taken after the IC guide.
    """
    ltx_v2v_local(api, DUBIT)
    concat, ref, guide, guider = (find(api, t) for t in ("LTXVConcatAVLatent", "LTXVSetAudioRefTokens", "LTXAddVideoICLoRAGuide", "CFGGuider"))
    assert api[concat]["inputs"]["audio_latent"] == [ref, 2], api[concat]["inputs"]
    assert api[guider]["inputs"]["positive"] == [guide, 0], api[guider]["inputs"]
    size, source = find(api, "GetImageSize"), find(api, "GetVideoComponents")
    api["ff_audio_empty"] = {"class_type": "LTXVEmptyLatentAudio",
                             "inputs": {"audio_vae": [find(api, "VAELoader", vae_name="ltx-2.5-audio-vae-bf16.safetensors"), 0],
                                        "frames_number": [size, 2], "frame_rate": [source, 2], "batch_size": 1},
                             "_meta": {"title": "New audio (not the clip's)"}}
    put(api, concat, "audio_latent", ["ff_audio_empty", 0])
    put(api, ref, "positive", [guide, 0])
    put(api, ref, "negative", [guide, 1])
    put(api, guider, "positive", [ref, 0])
    put(api, guider, "negative", [ref, 1])
    api[ref]["_meta"] = {"title": "Speaker reference (the clip's own voice)"}


def merge(api: Api, other: Api, prefix: str) -> None:
    """Add every node of `other` to `api` under "<prefix>:<id>", links rewritten."""
    for i, n in other.items():
        node = json.loads(json.dumps(n))
        for k, v in node["inputs"].items():
            if is_link(v):
                node["inputs"][k] = [f"{prefix}:{v[0]}", v[1]]
        api[f"{prefix}:{i}"] = node


def ltx_union_control(api: Api, edit: Api) -> None:
    """Lightricks' Union Control IC-LoRA example (two stages) as a one-click restyle: the clip's first frame
    is redrawn in the chosen look by FLUX 3 Klein (the `edit` pipeline, merged in under "edit:"), that still
    opens the video ("use image input" on), and the clip's edges from the core Canny node keep the structure.

    The example turns the reference clip into a control signal with an annotator: Video Depth Anything by
    default, Canny or DWPose as alternatives, all three custom nodes; Canny exists in core, so that branch is
    wired in. The first run (20261022-181155-h100) with edges and the look only in the prompt gave the same
    photoreal footage in 14 of 16 looks: the control LoRA reproduces what it is guided with, and the look has
    to come in through the first frame, as the example's image input is meant to be used.
    """
    ltx_local_text(api)
    # the prompt is "<look>. <what is in the shot>": the look picker writes ff_style, the text box writes 5508
    rewire(api, ["5014:5556", 0], ["ff_prompt", 0])
    drop(api, "5014:5556", "5014:5555", "5014:5546", "5014:9004", "5004:5605")
    api["ff_style"] = {"class_type": "PrimitiveString", "inputs": {"value": "Japanese anime style, cel shading, clean line art, vibrant flat colors"},
                       "_meta": {"title": "Look"}}
    api["ff_prompt"] = {"class_type": "StringConcatenate", "inputs": {"string_a": ["ff_style", 0], "string_b": ["5508", 0], "delimiter": ". "},
                        "_meta": {"title": "Look + shot"}}
    frames = find(api, "ResizeImageMaskNode", **{"resize_type": "scale shorter dimension"})
    guide_out = find(api, "VideoDepthAnythingOutput")
    api["ff_canny"] = {"class_type": "Canny", "inputs": {"image": [frames, 0], "low_threshold": 0.35, "high_threshold": 0.75},
                       "_meta": {"title": "Edges of the reference clip"}}
    rewire(api, [guide_out, 0], ["ff_canny", 0])
    drop(api, guide_out, find(api, "VideoDepthAnythingProcess"), find(api, "LoadVideoDepthAnythingModel"),
         find(api, "CannyEdgePreprocessor"), find(api, "DWPreprocessor"))
    put(api, find(api, "LTXICLoRALoaderModelOnly"), "lora_name", UNION_CONTROL)
    # first frame → FLUX 3 Klein edit in the chosen look → the video's first frame
    merge(api, edit, "edit")
    drop(api, "edit:9")   # its SaveImage: the still is an intermediate, not an output
    source = find(api, "GetVideoComponents")
    api["ff_first_frame"] = {"class_type": "ImageFromBatch", "inputs": {"image": [source, 0], "batch_index": 0, "length": 1},
                             "_meta": {"title": "First frame of the clip"}}
    rewire(api, ["edit:11", 0], ["ff_first_frame", 0])
    drop(api, "edit:11")
    api["ff_edit_prompt"] = {"class_type": "StringConcatenate",
                             "inputs": {"string_a": "Redraw this exact photo in this look, keeping the composition, the people and the place:",
                                        "string_b": ["ff_style", 0], "delimiter": " "},
                             "_meta": {"title": "Edit instruction"}}
    put(api, "edit:4", "text", ["ff_edit_prompt", 0])
    styled = find(api, "VAEDecode", vae=["edit:3", 0])
    load_image = find(api, "LoadImage")
    rewire(api, [load_image, 0], [styled, 0])
    drop(api, load_image)
    use_image = find(api, "PrimitiveBoolean", value=False)
    put(api, use_image, "value", True)


def ltx_ingredients(api: Api) -> None:
    """Lightricks' Ingredients IC-LoRA example: local text, the 2.5 LoRA file."""
    ltx_local_text(api)
    put(api, find(api, "LTXICLoRALoaderModelOnly"), "lora_name", INGREDIENTS)


# KJNodes' ImagePadForOutpaintTargetSize sits in Lightricks' Outpaint example. It is not a core node, so
# the converter gets this stand-in (its widget order) and ltx_outpaint rebuilds it from core nodes.
KJ_PAD = {"input": {"required": {"image": ["IMAGE"], "target_width": ["INT", {}], "target_height": ["INT", {}],
                                 "feathering": ["INT", {}],
                                 "upscale_method": [["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]]},
                    "optional": {"mask": ["MASK"]}},
          "output": ["IMAGE", "MASK"], "output_name": ["IMAGE", "MASK"]}


def ltx_outpaint(api: Api) -> None:
    """Lightricks' Outpaint IC-LoRA example (two stages): local text, no enhancer, no start image,
    and the KJNodes pad node rebuilt from core nodes.

    KJNodes' ImagePadForOutpaintTargetSize scales the frames down to fit the target (never up),
    then pads them to it, centred, and returns the padded frames and the mask of the padding.
    GetImageSize + ComfyMathExpression + ImageScale + ImagePadForOutpaint do the same arithmetic.
    The optional start image is off in the example; the two nodes that would condition on it
    pass the latent through when bypassed, so they go with the image chain.
    """
    ltx_local_text(api)
    # enhancer (Gemma 4 E2B) and its switches: the prompt feeds the encoder directly
    rewire(api, ["5408:5610", 0], ["5404", 0])
    drop(api, "5408:5610", "5408:5609", "5408:5608", "5408:5406", "5407:5605")
    # start image chain
    for node in ("5409:3159", "5413:5213"):
        assert api[node]["class_type"] == "LTXVImgToVideoConditionOnly", node
    rewire(api, ["5409:3159", 0], ["5409:3059", 0])
    rewire(api, ["5413:5213", 0], ["5413:5267", 0])
    drop(api, "5409:3159", "5413:5213", "5409:5388", "5408:5188", "2004", "5408:9019", "5408:9018", "5408:5022")
    drop(api, "5407:5604")   # latent upscaler: loaded but unused (stage 2 re-encodes the upscaled pixels)
    # the pad node
    pad = find(api, "ImagePadForOutpaintTargetSize")
    src, tw, th = (api[pad]["inputs"][k] for k in ("image", "target_width", "target_height"))
    api["ff_size"] = {"class_type": "GetImageSize", "inputs": {"image": src}, "_meta": {"title": "Frame size"}}
    w, h = ["ff_size", 0], ["ff_size", 1]

    def expr(nid: str, title: str, expression: str, **values) -> None:
        api[nid] = {"class_type": "ComfyMathExpression",
                    "inputs": {"expression": expression, **{f"values.{k}": v for k, v in values.items()}},
                    "_meta": {"title": title}}

    expr("ff_scale", "fit scale (never up)", "min(1, min(c / a, d / b))", a=w, b=h, c=tw, d=th)
    expr("ff_w", "fitted width", "floor(a * b)", a=w, b=["ff_scale", 0])
    expr("ff_h", "fitted height", "floor(a * b)", a=h, b=["ff_scale", 0])
    api["ff_fit"] = {"class_type": "ImageScale",
                     "inputs": {"image": src, "upscale_method": "lanczos", "width": ["ff_w", 1], "height": ["ff_h", 1], "crop": "disabled"},
                     "_meta": {"title": "Fit inside the target"}}
    expr("ff_left", "pad left", "max(0, floor((c - a) / 2))", a=["ff_w", 1], c=tw)
    expr("ff_right", "pad right", "max(0, c - a - floor((c - a) / 2))", a=["ff_w", 1], c=tw)
    expr("ff_top", "pad top", "max(0, floor((c - a) / 2))", a=["ff_h", 1], c=th)
    expr("ff_bottom", "pad bottom", "max(0, c - a - floor((c - a) / 2))", a=["ff_h", 1], c=th)
    api["ff_pad"] = {"class_type": "ImagePadForOutpaint",
                     "inputs": {"image": ["ff_fit", 0], "left": ["ff_left", 1], "top": ["ff_top", 1], "right": ["ff_right", 1],
                                "bottom": ["ff_bottom", 1], "feathering": api[pad]["inputs"].get("feathering", 0)},
                     "_meta": {"title": "Pad to the target"}}
    # the core pad returns one mask, the KJ node one per frame; the example's Laplacian blends trim every
    # input to the shortest, so a one-frame mask leaves a one-frame video (run 20261022-181155-h100)
    api["ff_mask_img"] = {"class_type": "MaskToImage", "inputs": {"mask": ["ff_pad", 1]}, "_meta": {"title": "Mask as image"}}
    api["ff_mask_rep"] = {"class_type": "RepeatImageBatch", "inputs": {"image": ["ff_mask_img", 0], "amount": ["ff_size", 2]},
                          "_meta": {"title": "One mask per frame"}}
    api["ff_mask"] = {"class_type": "ImageToMask", "inputs": {"image": ["ff_mask_rep", 0], "channel": "red"},
                      "_meta": {"title": "Padding mask"}}
    rewire(api, [pad, 0], ["ff_pad", 0])
    rewire(api, [pad, 1], ["ff_mask", 0])
    drop(api, pad)
    put(api, find(api, "LTXICLoRALoaderModelOnly"), "lora_name", IN_OUTPAINTING)


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
    def load(path: Path, extra: dict | None = None) -> Api:
        ui = json.loads(path.read_text(encoding="utf-8"))
        _collect_types(ui)
        api, warnings = convert(ui, {**info, **(extra or {})})
        for w in warnings:
            print(f"  [{path.name}] {w}")
        return api

    def tpl(name: str) -> Api:
        return load(templates / name)

    def ltxwf(name: str, extra: dict | None = None) -> Api:
        return load(ltx / name, extra)

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

    hdr = ltxwf("HDR_workflows/LTX-2.5_ICLoRA_SDR_to_HDR_Distilled.json")
    ltx_sdr_to_hdr(hdr)
    out["sdr-hdr"] = hdr
    ing = ltxwf("LTX-2.5_ICLoRA_Ingredients_Single_Stage_Distilled.json")
    ltx_ingredients(ing)
    out["genjutsu"] = ing
    op = ltxwf("LTX-2.5_ICLoRA_Outpaint_Two_Stage_Distilled.json", {"ImagePadForOutpaintTargetSize": KJ_PAD})
    ltx_outpaint(op)
    out["reframe"] = op
    uc = ltxwf("LTX-2.5_ICLoRA_Union_Control_Distilled.json", UNION_STANDINS)
    ltx_union_control(uc, e)
    out["mixed-media"] = uc
    # DubIt on 2.5: Lightricks only published a 2.3 workflow (dev checkpoint + distilled LoRA), but its shape is
    # the V2V IC-LoRA one: the clip is the guide, its audio the speaker reference, the new words come in the
    # prompt. The 2.5 V2V example already freezes the clip's audio as reference tokens, so only the LoRA differs.
    dub = ltxwf("LTX-2.5_V2V_ICLoRA_Single_Stage_Distilled.json")
    ltx_dub(dub)
    out["dub"] = dub

    cm = tpl("video_wan2_2_14B_fun_camera.json")
    # The template's 4-step Lightning variant is bypassed; its LoRAs come back at strength 0, which
    # ComfyUI skips without loading the file. The app's "fast" preset turns them on.
    add_lora_after(cm, find(cm, "UNETLoader", unet_name="wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors"),
                   "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", 0.0, nid="ff_lora_high")
    add_lora_after(cm, find(cm, "UNETLoader", unet_name="wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors"),
                   "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", 0.0, nid="ff_lora_low")
    out["camera-moves"] = cm

    ef = tpl("image_to_video_wan.json")
    # Wan 2.1 I2V 14B 480p, the model Remade-AI trained its effect LoRAs on, in fp8 so the 14B
    # model fits a 24 GB card by phases. The effect LoRA goes right after the loader (each effect
    # option in app.json swaps the file and writes its prompt); lightx2v's step-distill LoRA follows
    # at strength 0 (a no-op) for the "fast" preset. Flow shift 5, as the effect LoRA cards say.
    swap_files(ef, {"wan2.1_i2v_480p_14B_fp16.safetensors": "wan2.1_i2v_480p_14B_fp8_scaled.safetensors"})
    add_lora_after(ef, find(ef, "UNETLoader"), EFFECT_LORA, 1.0, nid="ff_effect")
    add_lora_after(ef, "ff_effect", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", 0.0, nid="ff_lora_fast")
    put(ef, find(ef, "ModelSamplingSD3"), "shift", 5.0)
    i2v = find(ef, "WanImageToVideo")
    for field, value in (("width", 480), ("height", 832), ("length", 81)):   # the app's defaults: 9:16, 5 s at 16 fps
        put(ef, i2v, field, value)
    out["effects"] = ef

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
    # the pose offset (b - c) * (a - 1) reads b and c from subgraph inputs the conversion cannot see;
    # for the first segment it is 0, so the frame range starts at 0 and the expression goes
    put(rc, "213:177", "batch_index", 0)
    drop(rc, "213:184", "213:183")
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

#!/usr/bin/env python3
"""Convert a ComfyUI workflow saved from the UI (with subgraphs) into API format.

ComfyUI's official templates are UI workflows: node positions, links, and nested
subgraphs. The runner needs the flat API format ({node_id: {class_type, inputs}}).
This does the same flattening the ComfyUI frontend does on "Export (API)", using the
node definitions from a running ComfyUI (GET /object_info) so widget values land on
the right inputs.

    python tools/ui2api.py template.json --object-info tools/object_info.json -o app/workflow.api.json

Subgraph nodes get ids like "57:27" (instance id : inner node id), as the frontend does.
Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FRONTEND_ONLY_SKIP = {"Note", "MarkdownNote", "Label (rgthree)", "Fast Groups Bypasser (rgthree)"}
CONTROL_VALUES = {"fixed", "increment", "decrement", "randomize"}
UPLOAD_VALUES = {"image", "video", "audio", "upload", "file"}
PRIMITIVE_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COLOR"}
DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"   # a combo whose selected option adds its own inputs ("format" → "format.codec")

MODE_NORMAL, MODE_MUTED, MODE_BYPASS = 0, 2, 4


class ConversionError(Exception):
    pass


@dataclass
class Ctx:
    """One graph level: the root workflow or one subgraph instance."""
    nodes: dict[int, dict]
    links: dict[int, tuple[int, int, int, int]]   # link id -> (origin, origin_slot, target, target_slot)
    prefix: str = ""
    sg_def: dict | None = None
    instance: dict | None = None
    parent: "Ctx | None" = None
    overrides: dict[tuple[str, str], Any] = field(default_factory=dict)  # (inner node id, widget) -> value


def _links_of(raw_links: list) -> dict[int, tuple[int, int, int, int]]:
    out = {}
    for l in raw_links or []:
        if isinstance(l, dict):
            out[int(l["id"])] = (int(l["origin_id"]), int(l["origin_slot"]), int(l["target_id"]), int(l["target_slot"]))
        else:  # [id, origin, origin_slot, target, target_slot, type]
            out[int(l[0])] = (int(l[1]), int(l[2]), int(l[3]), int(l[4]))
    return out


def _is_widget(spec: list) -> bool:
    if not spec:
        return False
    t = spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if opts.get("forceInput"):
        return False
    if isinstance(t, list):
        return True
    # "FLOAT,INT" style multi-types declare the widget they use; custom widget types
    # (bounding-box editors, image compare) say whether they have a socket.
    if "widgetType" in opts or "socketless" in opts:
        return True
    return t in PRIMITIVE_TYPES or t == DYNAMIC_COMBO


def _ordered_widgets(inputs: dict, order: dict | None = None) -> list[tuple[str, list]]:
    order = order or {k: list((v or {}).keys()) for k, v in inputs.items()}
    out = []
    for section in ("required", "optional"):
        specs = inputs.get(section, {}) or {}
        for name in order.get(section, []) or []:
            spec = specs.get(name)
            if spec is not None and _is_widget(spec):
                out.append((name, spec))
    return out


def _widget_inputs(info: dict) -> list[tuple[str, list]]:
    return _ordered_widgets(info.get("input", {}) or {}, info.get("input_order"))


def _assign(widgets: list[tuple[str, list]], values: list, i: int, out: dict, prefix: str = "") -> int:
    for name, spec in widgets:
        if i >= len(values):
            return i
        full = prefix + name
        val = values[i]
        out[full] = val
        i += 1
        opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        # the frontend adds a "control after generate" widget after seed-like INTs
        if (opts.get("control_after_generate") or name in ("seed", "noise_seed")) and i < len(values) \
                and isinstance(values[i], str) and values[i] in CONTROL_VALUES:
            i += 1
        # and an upload button after file combos
        if any(opts.get(k) for k in ("image_upload", "video_upload", "audio_upload", "upload")) and i < len(values) \
                and isinstance(values[i], str) and values[i] in UPLOAD_VALUES:
            i += 1
        # a dynamic combo's selected option brings its own widgets, named "<combo>.<input>"
        if spec[0] == DYNAMIC_COMBO:
            option = next((o for o in opts.get("options", []) if o.get("key") == val), None)
            if option:
                i = _assign(_ordered_widgets(option.get("inputs") or {}), values, i, out, prefix=full + ".")
    return i


def _map_widgets(node: dict, info: dict, warnings: list[str], where: str) -> dict[str, Any]:
    values = node.get("widgets_values")
    if values is None:
        return {}
    if isinstance(values, dict):   # some nodes store values by name
        return {k: v for k, v in values.items() if k not in ("videopreview", "preview")}
    out: dict[str, Any] = {}
    i = _assign(_widget_inputs(info), values, 0, out)
    if i < len(values):
        extra = values[i:]
        if any(v not in (None, "", []) for v in extra):
            warnings.append(f"{where}: {len(extra)} widget value(s) left over: {json.dumps(extra)[:120]}")
    return out


class Converter:
    def __init__(self, workflow: dict, object_info: dict):
        self.wf = workflow
        self.info = object_info
        self.subgraphs = {sg["id"]: sg for sg in (workflow.get("definitions") or {}).get("subgraphs", [])}
        self.warnings: list[str] = []
        self.api: dict[str, dict] = {}

    # ---- contexts -------------------------------------------------------
    def root(self) -> Ctx:
        return Ctx(nodes={int(n["id"]): n for n in self.wf.get("nodes", [])}, links=_links_of(self.wf.get("links")))

    def child(self, parent: Ctx, instance: dict) -> Ctx:
        sg = self.subgraphs[instance["type"]]
        ctx = Ctx(
            nodes={int(n["id"]): n for n in sg.get("nodes", [])},
            links=_links_of(sg.get("links")),
            prefix=f"{parent.prefix}{instance['id']}:",
            sg_def=sg,
            instance=instance,
            parent=parent,
        )
        # promoted widgets whose value was edited on the instance
        proxy = (instance.get("properties") or {}).get("proxyWidgets") or []
        wv = instance.get("widgets_values") or []
        if isinstance(wv, list) and wv:
            k = 0
            for inner_id, wname in proxy:
                if wname == "control_after_generate":
                    continue
                if k < len(wv):
                    ctx.overrides[(str(inner_id), wname)] = wv[k]
                k += 1
        return ctx

    # ---- link resolution -----------------------------------------------
    def resolve_link(self, ctx: Ctx, link_id: int):
        if link_id not in ctx.links:
            raise ConversionError(f"link {link_id} not found at level '{ctx.prefix or 'root'}'")
        origin, oslot, _, _ = ctx.links[link_id]
        return self.resolve_origin(ctx, origin, oslot)

    def resolve_origin(self, ctx: Ctx, origin: int, oslot: int):
        if origin == -10:  # the subgraph's input node
            name = ctx.sg_def["inputs"][oslot]["name"]
            for inp in ctx.instance.get("inputs", []) or []:
                if inp.get("name") == name and inp.get("link") is not None:
                    return self.resolve_link(ctx.parent, int(inp["link"]))
            return ("unlinked",)
        node = ctx.nodes.get(origin)
        if node is None:
            raise ConversionError(f"origin node {origin} missing at level '{ctx.prefix or 'root'}'")
        t = node["type"]
        mode = node.get("mode", MODE_NORMAL)
        if mode == MODE_BYPASS:
            out_type = (node.get("outputs") or [{}])[oslot].get("type")
            for inp in node.get("inputs", []) or []:
                if inp.get("type") == out_type and inp.get("link") is not None:
                    return self.resolve_link(ctx, int(inp["link"]))
            return ("unlinked",)
        if mode == MODE_MUTED:
            return ("unlinked",)
        if t == "Reroute":
            inp = (node.get("inputs") or [{}])[0]
            return self.resolve_link(ctx, int(inp["link"])) if inp.get("link") is not None else ("unlinked",)
        if t == "PrimitiveNode":
            return ("value", (node.get("widgets_values") or [None])[0])
        if t in self.subgraphs:
            sub = self.child(ctx, node)
            out = sub.sg_def["outputs"][oslot]
            ids = out.get("linkIds") or []
            if not ids:
                return ("unlinked",)
            return self.resolve_link(sub, int(ids[0]))
        return ("node", f"{ctx.prefix}{origin}", oslot)

    # ---- emission -------------------------------------------------------
    def emit(self, ctx: Ctx) -> None:
        for nid, node in ctx.nodes.items():
            t = node["type"]
            mode = node.get("mode", MODE_NORMAL)
            if t in FRONTEND_ONLY_SKIP or t in ("Reroute", "PrimitiveNode"):
                continue
            if t in self.subgraphs:
                if mode in (MODE_MUTED, MODE_BYPASS):
                    continue
                self.emit(self.child(ctx, node))
                continue
            if mode in (MODE_MUTED, MODE_BYPASS):
                continue
            info = self.info.get(t)
            where = f"{ctx.prefix}{nid} ({t})"
            if info is None:
                raise ConversionError(f"{where}: node type not in object_info (custom node not installed?)")
            widgets = _map_widgets(node, info, self.warnings, where)
            for (inner_id, wname), val in ctx.overrides.items():
                if inner_id == str(nid) and wname in widgets:
                    widgets[wname] = val
            inputs: dict[str, Any] = {}
            for inp in node.get("inputs", []) or []:
                link = inp.get("link")
                if link is None:
                    continue
                r = self.resolve_link(ctx, int(link))
                if r[0] == "node":
                    inputs[inp["name"]] = [r[1], r[2]]
                elif r[0] == "value":
                    inputs[inp["name"]] = r[1]
            for k, v in widgets.items():
                # a bare list means "link" in API format, so list-valued widgets are wrapped
                inputs.setdefault(k, {"__value__": v} if isinstance(v, list) else v)
            # required widgets the UI never stored (e.g. socketless editors) fall back to their default
            for name, spec in (info.get("input", {}).get("required") or {}).items():
                opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if name not in inputs and _is_widget(spec):
                    if "default" in opts:
                        d = opts["default"]
                        inputs[name] = {"__value__": d} if isinstance(d, list) else d
                    elif opts.get("socketless"):
                        inputs[name] = None
            title = node.get("title") or info.get("display_name") or t
            self.api[f"{ctx.prefix}{nid}"] = {"class_type": t, "inputs": inputs, "_meta": {"title": title}}

    def run(self) -> dict:
        self.emit(self.root())
        # drop dangling references to nodes that were skipped
        for nid, node in self.api.items():
            for k, v in list(node["inputs"].items()):
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in self.api:
                    self.warnings.append(f"{nid}: input '{k}' pointed to skipped node {v[0]}; removed")
                    del node["inputs"][k]
        return dict(sorted(self.api.items(), key=lambda kv: [int(p) if p.isdigit() else p for p in kv[0].split(":")]))


def convert(workflow: dict, object_info: dict) -> tuple[dict, list[str]]:
    c = Converter(workflow, object_info)
    api = c.run()
    return api, c.warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--object-info", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    api, warnings = convert(json.loads(a.workflow.read_text(encoding="utf-8")),
                            json.loads(a.object_info.read_text(encoding="utf-8")))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    text = json.dumps(api, indent=2, ensure_ascii=False)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n", encoding="utf-8")
        print(f"{a.out}: {len(api)} nodes")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

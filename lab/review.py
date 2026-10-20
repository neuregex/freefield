#!/usr/bin/env python3
"""Build a local review page for a lab run and, optionally, write measured VRAM back.

    python lab/review.py lab/results/<run_id>            → lab/results/<run_id>/review.html
    python lab/review.py lab/results/<run_id> --apply-peaks   also stores each app's highest
                                                           measured peak in apps/<id>/app.json

The page plays every output next to its settings. Ratings (good / meh / bad) and notes are
kept in your browser and can be exported as ratings.json for the next round.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Freefield lab · {run}</title>
<style>
:root{{--bg:#0d1520;--card:#152232;--line:#2a3d52;--ink:#e8eef5;--dim:#8fa3b8;--good:#74d97a;--meh:#f5cf4a;--bad:#ff7466}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
header{{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
h1{{font-size:20px;margin:0}} .meta{{color:var(--dim)}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:16px 24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;display:grid;gap:8px}}
.card.err{{border-color:var(--bad)}} video,img,audio{{width:100%;border-radius:6px;background:#000}}
.id{{font-weight:600}} .small{{color:var(--dim);font-size:13px;word-break:break-word}}
.rate{{display:flex;gap:8px}} .rate button{{flex:1;padding:6px;border-radius:6px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer}}
.rate button.on[data-v=good]{{background:var(--good);color:#0d1520}} .rate button.on[data-v=meh]{{background:var(--meh);color:#0d1520}} .rate button.on[data-v=bad]{{background:var(--bad);color:#0d1520}}
textarea{{width:100%;box-sizing:border-box;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;min-height:48px}}
button.export{{padding:8px 14px;border-radius:6px;border:0;background:var(--ink);color:var(--bg);cursor:pointer}}
</style></head><body>
<header><h1>Lab run {run}</h1><span class="meta">{gpu} · {ok}/{n} ok</span><button class="export" id="export">Export ratings.json</button></header>
<main>{cards}</main>
<script>
const KEY = "freefield-lab-{run}";
let state = {{}}; try {{ state = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
const save = () => {{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}} }};
document.querySelectorAll(".card").forEach(card => {{
  const id = card.dataset.id; const s = state[id] || {{}};
  card.querySelectorAll(".rate button").forEach(b => {{
    if (s.rating === b.dataset.v) b.classList.add("on");
    b.onclick = () => {{ state[id] = {{...state[id], rating: b.dataset.v}}; save();
      card.querySelectorAll(".rate button").forEach(x => x.classList.toggle("on", x === b)); }};
  }});
  const t = card.querySelector("textarea"); t.value = s.note || "";
  t.oninput = () => {{ state[id] = {{...state[id], note: t.value}}; save(); }};
}});
document.getElementById("export").onclick = () => {{
  const blob = new Blob([JSON.stringify({{run: "{run}", ratings: state}}, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ratings.json"; a.click();
}};
</script></body></html>"""


def media(path: str) -> str:
    p = html.escape(path)
    low = path.lower()
    if low.endswith((".mp4", ".webm", ".mov")):
        return f'<video src="{p}" controls loop muted playsinline preload="metadata"></video>'
    if low.endswith((".mp3", ".wav", ".flac", ".ogg")):
        return f'<audio src="{p}" controls preload="none"></audio>'
    return f'<img src="{p}" loading="lazy" alt="">'


def card(r: dict) -> str:
    vals = ", ".join(f"{k}={json.dumps(v)[:80]}" for k, v in r.get("values", {}).items())
    loras = ", ".join(f"{l['file'].rsplit('/', 1)[-1]} @{l.get('strength', 1.0)}" for l in r.get("loras", []))
    ovr = ", ".join(f"{o['node']}.{o['field']}={json.dumps(o['value'])[:60]}" for o in r.get("overrides", []))
    peak = f"{r['peak_vram_gb']:.1f} GB" if r.get("peak_vram_gb") is not None else "n/a"
    body = "".join(media(f) for f in r.get("files", [])) or f'<div class="small">{html.escape(r.get("error") or "no output")}</div>'
    return f"""<section class="card{' err' if r['status'] != 'ok' else ''}" data-id="{html.escape(r['id'])}">
<div class="id">{html.escape(r['id'])} <span class="small">· {html.escape(r['app'])} · {r.get('seconds') or 0:.0f}s · peak {peak}</span></div>
{body}
<div class="small">{html.escape(r.get('note', ''))}</div>
<div class="small">{html.escape(vals)}{('<br>LoRA: ' + html.escape(loras)) if loras else ''}{('<br>overrides: ' + html.escape(ovr)) if ovr else ''}</div>
<div class="rate"><button data-v="good">good</button><button data-v="meh">meh</button><button data-v="bad">bad</button></div>
<textarea placeholder="notes"></textarea></section>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--apply-peaks", action="store_true")
    a = ap.parse_args(argv)
    lines = (a.run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    results = {}
    for line in lines:   # a re-run of the same id replaces the earlier row
        if line.strip():
            r = json.loads(line)
            results[r["id"]] = r
    rows = list(results.values())
    meta = json.loads((a.run_dir / "run.json").read_text()) if (a.run_dir / "run.json").exists() else {}
    page = PAGE.format(run=html.escape(a.run_dir.name), gpu=html.escape(meta.get("gpu") or "unknown GPU"),
                       ok=sum(r["status"] == "ok" for r in rows), n=len(rows), cards="\n".join(card(r) for r in rows))
    out = a.run_dir / "review.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    if a.apply_peaks:
        peaks: dict[str, float] = {}
        for r in rows:
            if r["status"] == "ok" and r.get("peak_vram_gb"):
                peaks[r["app"]] = max(peaks.get(r["app"], 0), r["peak_vram_gb"])
        for app_id, peak in peaks.items():
            f = ROOT / "apps" / app_id / "app.json"
            m = json.loads(f.read_text(encoding="utf-8"))
            m["vram"] = {"peak_gb": peak, "measured_on": f"{meta.get('gpu', 'GPU')} · {meta.get('started', '')[:10]}"}
            f.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"apps/{app_id}: peak {peak:.1f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

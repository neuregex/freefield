#!/usr/bin/env bash
# A CPU-only ComfyUI at the commit Freefield pins, with every custom node the packs pin, started
# in the background. Enough for tools/comfy_validate.py; no GPU and no model weights needed.
#
#   bash tools/ci_comfyui.sh /tmp/comfyui            # then:
#   python tools/comfy_validate.py --comfy-dir /tmp/comfyui --placeholders
#
# Uses the current python3; run it inside a virtualenv on your own machine.
set -euo pipefail

DIR=${1:?usage: ci_comfyui.sh <dir> [port]}
PORT=${2:-8188}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
COMMIT=$(sed -n 's/^COMFYUI_COMMIT *= *"\([0-9a-f]*\)".*/\1/p' "$ROOT/infra/common.py")
[ -n "$COMMIT" ] || { echo "COMFYUI_COMMIT not found in infra/common.py" >&2; exit 1; }

if [ ! -d "$DIR/.git" ]; then
  git clone --quiet --filter=blob:none https://github.com/comfyanonymous/ComfyUI "$DIR"
fi
git -C "$DIR" checkout --quiet "$COMMIT"

# CPU wheels first, so ComfyUI's unpinned torch requirement is already satisfied
python3 -m pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install --quiet -r "$DIR/requirements.txt"

python3 - "$ROOT" "$DIR" <<'EOF'
import json, pathlib, subprocess, sys
root, comfy = map(pathlib.Path, sys.argv[1:3])
pinned = {}
for p in sorted((root / "packs").glob("*.json")):
    if p.name != "index.json":
        for cn in json.loads(p.read_text(encoding="utf-8")).get("custom_nodes", []):
            pinned[cn["repo"]] = cn["commit"]
for repo, commit in sorted(pinned.items()):
    dst = comfy / "custom_nodes" / repo.rstrip("/").rsplit("/", 1)[-1]
    if not dst.exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", repo, str(dst)], check=True)
    subprocess.run(["git", "-C", str(dst), "checkout", "--quiet", commit], check=True)
    req = dst / "requirements.txt"
    if req.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)], check=True)
    print(f"custom node {dst.name} @ {commit[:7]}")
EOF

cd "$DIR"
nohup python3 main.py --cpu --listen 127.0.0.1 --port "$PORT" --disable-auto-launch > "$DIR/comfyui.log" 2>&1 &
for _ in $(seq 1 150); do
  if curl -fsS "http://127.0.0.1:$PORT/object_info/KSampler" > /dev/null 2>&1; then
    echo "ComfyUI $COMMIT is up on :$PORT"
    exit 0
  fi
  sleep 2
done
echo "ComfyUI did not start; last log lines:" >&2
tail -50 "$DIR/comfyui.log" >&2
exit 1

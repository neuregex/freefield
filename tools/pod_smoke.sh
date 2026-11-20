#!/usr/bin/env bash
# End-to-end check of the Docker image without a GPU or model weights: the container starts as on RunPod or Vast,
# the studio's passcode door opens, the smoke app runs through studio → gateway → comfy-api-proxy → ComfyUI (--cpu),
# and its image comes back. It asks for the FLUX 3 pack with no Hugging Face token and Hugging Face out of reach
# (HF_ENDPOINT): the gated files wait for a token, the other one fails, and the studio says which is which.
# CI runs it on the CPU build; locally:
#
#   docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu --build-arg TUNNEL=0 -t freefield:cpu .
#   bash tools/pod_smoke.sh freefield:cpu
set -euo pipefail

IMAGE=${1:?usage: pod_smoke.sh <image>}
NAME=ff-smoke-$$
JAR=$(mktemp)
STUDIO=http://127.0.0.1:3000
cleanup() { docker logs "$NAME" > "${SMOKE_LOG:-/tmp/ff-smoke.log}" 2>&1 || true; docker rm -f "$NAME" > /dev/null 2>&1 || true; rm -f "$JAR"; }
trap cleanup EXIT
fail() { echo "✗ $*" >&2; docker logs --tail 60 "$NAME" >&2 || true; exit 1; }

docker run -d --name "$NAME" -p 3000:3000 -p 8000:8000 \
  -e FREEFIELD_PACKS=image-flux3 -e HF_ENDPOINT=http://127.0.0.1:9 -e FREEFIELD_COMFY_ARGS=--cpu -e FREEFIELD_DESKTOP_ICON=1 \
  -e FREEFIELD_PASSCODE=smoke-pass -e FREEFIELD_TOKEN=smoke-token "$IMAGE" > /dev/null

# up when the studio answers (401: the door is closed without the passcode)
for i in $(seq 1 180); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' "$STUDIO/api/gpu" || true)
  [ "$code" = 401 ] && break
  docker inspect -f '{{.State.Running}}' "$NAME" | grep -q true || fail "the container exited"
  sleep 2
done
[ "$code" = 401 ] || fail "the studio did not come up in 6 min (last answer: $code)"
docker logs "$NAME" 2>&1 | grep -q "Freefield is ready" || { sleep 3; docker logs "$NAME" 2>&1 | grep -q "Freefield is ready" || fail "no ready banner"; }
echo "✓ studio up, closed without the passcode"

code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -c "$JAR" "$STUDIO/?key=smoke-pass")
[ "$code" = 303 ] || fail "the passcode link answered $code, not 303"
gpu=$(curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/gpu")
echo "$gpu" | grep -q '"always_on":true' || fail "GPU status is not always on: $gpu"
echo "$gpu" | grep -q '"warm":true' || fail "GPU status is not warm: $gpu"
echo "✓ passcode cookie works; the pill says always on: $(echo "$gpu" | sed -n 's/.*"host":"\([^"]*\)".*/\1/p')"

# the studio opened while the download went on; it ends quickly here (no token, Hugging Face out of reach)
for i in $(seq 1 90); do
  state=$(curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/models?fresh=1" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("job") or {}).get("state"))' || true)
  [ "$state" = done ] && break
  sleep 2
done
[ "$state" = done ] || fail "the download in the background did not end (state: $state)"
curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/models" | python3 -c '
import json, sys
m = json.load(sys.stdin)
assert m["available"] and m["token"]["source"] is None, (m["available"], m["token"])
why = {k.split("/")[-1]: v["reason"] for k, v in m["failed"].items()}
assert why.pop("mediapipe_face_fp32.safetensors") == "failed", why
assert len(why) == 4 and set(why.values()) == {"token_missing"}, why
assert m["needs"]["create-image"] == {"kind": "token", "pack": "image-flux3", "repos": ["black-forest-labs/flux-3-image-klein-comfy"]}, m["needs"]["create-image"]
assert m["needs"]["z-image"]["kind"] == "pack", m["needs"]["z-image"]
' || fail "the Models panel does not say why the files are missing"
echo "✓ the studio opened during the download; gated files wait for a token, the rest says it failed"

# apps that lack files are marked with why, and refuse to run; the smoke app is not
curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/apps" | python3 -c '
import json, sys
d = json.load(sys.stdin)
a = {x["id"]: x for x in d["apps"]}
assert d["models_panel"] is True
assert a["smoke"]["missing_pack"] is None and a["smoke"]["needs"] is None, a["smoke"]["needs"]
assert a["z-image"]["missing_pack"] == "image" and a["z-image"]["needs"]["kind"] == "pack", a["z-image"]["needs"]
assert a["create-image"]["needs"]["kind"] == "token", a["create-image"]["needs"]
' || fail "apps without their files are not marked"
code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -b "$JAR" -X POST -F prompt=x "$STUDIO/api/apps/z-image/run")
[ "$code" = 400 ] || fail "an app without its pack was accepted ($code)"
curl -s --noproxy '*' -b "$JAR" -X POST -F prompt=x "$STUDIO/api/apps/create-image/run" | grep -q "accept its license" \
  || fail "an app waiting for a license does not say so"
echo "✓ apps whose files are missing are marked and refused, with the reason"

code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -b "$JAR" -X PUT -H 'content-type: application/json' \
  -d '{"token":"not-a-token"}' "$STUDIO/api/models/token")
[ "$code" = 400 ] || fail "a malformed Hugging Face token was taken ($code)"
code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -b "$JAR" -X POST -H 'content-type: application/json' \
  -d '{"packs":["nope"]}' "$STUDIO/api/models/download")
[ "$code" = 400 ] || fail "an unknown pack was accepted ($code)"
[ "$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' http://127.0.0.1:8000/freefield/downloads)" = 401 ] || fail "the gateway's downloads answered without its token"
echo "✓ the Models panel refuses a malformed token and unknown packs; the gateway keeps them behind its token"

# as the Windows launcher starts it: the studio asks about the desktop icon, the launcher's window makes it
icon() { curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/gpu" | python3 -c 'import json,sys; print(json.load(sys.stdin)["desktop_icon"])'; }
[ "$(icon)" = ask ] || fail "the studio does not ask about the desktop icon"
curl -sf --noproxy '*' -b "$JAR" -X POST -H 'content-type: application/json' -d '{"want":true}' "$STUDIO/api/desktop-icon" > /dev/null || fail "the icon answer was refused"
[ "$(docker exec "$NAME" cat /workspace/freefield/desktop-icon)" = wanted ] || fail "the answer is not in the volume for the launcher"
docker exec "$NAME" sh -c 'printf created > /workspace/freefield/desktop-icon'
[ "$(icon)" = created ] || fail "the studio does not see the icon the launcher made"
echo "✓ the desktop icon: asked in the studio, answered in the volume, made by the launcher"

[ "$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' http://127.0.0.1:8000/freefield/status)" = 401 ] || fail "the gateway answered without its token"
curl -sf --noproxy '*' -H "Authorization: Bearer smoke-token" http://127.0.0.1:8000/freefield/status > /dev/null || fail "the gateway refused its own token"
echo "✓ gateway on :8000 needs the token"

run=$(curl -sf --noproxy '*' -b "$JAR" -X POST -F width=128 -F height=128 "$STUDIO/api/apps/smoke/run") || fail "POST /api/apps/smoke/run failed"
id=$(echo "$run" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
for i in $(seq 1 120); do
  entry=$(curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/history/$id")
  status=$(echo "$entry" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  case "$status" in succeeded) break ;; failed|canceled|expired|lost) fail "the smoke run ended $status: $entry" ;; esac
  sleep 1
done
[ "$status" = succeeded ] || fail "the smoke run is still $status after 2 min"
url=$(echo "$entry" | python3 -c 'import json,sys; print(json.load(sys.stdin)["outputs"][0]["url"])')
curl -sf --noproxy '*' -b "$JAR" "$STUDIO$url" | head -c 8 | od -An -tx1 | grep -q '89 50 4e 47' || fail "the output is not a PNG"
echo "✓ smoke app ran on ComfyUI --cpu and its PNG came back ($id)"

# a second browser with the passcode sees the same history (one owner per pod)
JAR2=$(mktemp)
curl -s -o /dev/null --noproxy '*' -c "$JAR2" "$STUDIO/?key=smoke-pass"
curl -sf --noproxy '*' -b "$JAR2" "$STUDIO/api/history" | grep -q "\"$id\"" || { rm -f "$JAR2"; fail "another browser does not see the run"; }
rm -f "$JAR2"
echo "✓ every browser with the passcode sees the same history"
echo "all good"

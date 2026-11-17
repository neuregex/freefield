#!/usr/bin/env bash
# End-to-end check of the Docker image without a GPU or model weights: the container starts as on RunPod or Vast,
# the studio's passcode door opens, the smoke app runs through studio → gateway → comfy-api-proxy → ComfyUI (--cpu),
# and its image comes back. CI runs it on the CPU build; locally:
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
  -e FREEFIELD_PACKS=none -e FREEFIELD_COMFY_ARGS=--cpu \
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

# FREEFIELD_PACKS=none: apps that need model files are marked with their pack and refuse to run; the smoke app is not
curl -sf --noproxy '*' -b "$JAR" "$STUDIO/api/apps" | python3 -c '
import json, sys
a = {x["id"]: x for x in json.load(sys.stdin)["apps"]}
assert a["smoke"]["missing_pack"] is None, a["smoke"]["missing_pack"]
assert a["z-image"]["missing_pack"] == "image", a["z-image"]["missing_pack"]
' || fail "apps without their pack are not marked"
code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -b "$JAR" -X POST -F prompt=x "$STUDIO/api/apps/z-image/run")
[ "$code" = 400 ] || fail "an app without its pack was accepted ($code)"
echo "✓ apps whose pack is not downloaded are marked and refused"

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

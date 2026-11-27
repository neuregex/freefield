#!/usr/bin/env bash
# Freefield on your own NVIDIA GPU, on Linux, with one line:
#
#   curl -fsSL https://raw.githubusercontent.com/neuregex/freefield/main/start.sh | bash
#
# The Linux twin of start.ps1. It checks the GPU, its driver, Docker and the NVIDIA Container Toolkit, runs the
# ghcr.io/neuregex/freefield image with the models in a Docker volume and opens the studio in the browser while the
# models download. It asks nothing else here: as on RunPod and Vast.ai, the studio shows how the download goes and
# asks for a Hugging Face token when a model needs one (its Models panel). Next time: the same line. A new image is
# picked up whenever Freefield is not already running. Its messages are in English, like the video and the README.
# From the copy it keeps:  bash ~/.local/share/freefield/start.sh stop|logs|uninstall
# (or the same line with "| bash -s -- stop").
# Optional: FREEFIELD_PACKS picks the model packs (packs/index.json), HF_TOKEN goes in at the first start,
# FREEFIELD_IMAGE runs another image (a branch's, to try it before it is merged), FREEFIELD_LAUNCHER_REF the branch
# whose launcher it keeps.
# Under the hood these are the same docker commands as in docs/cloud-gpus.md. It never asks for sudo: what needs it
# (installing Docker or the toolkit) it says, with the link. In WSL 2 with Docker Desktop it works too: there Docker
# Desktop reaches the GPU itself, and the studio opens in Windows' browser.
#
# Everything runs from main() at the end, so "curl | bash" has read the whole script before anything starts.

NAME=freefield                         # the container and the volume, as in docs/cloud-gpus.md
IMAGE=${FREEFIELD_IMAGE:-ghcr.io/neuregex/freefield:latest}
REF=${FREEFIELD_LAUNCHER_REF:-main}
RAW="https://raw.githubusercontent.com/neuregex/freefield/$REF"
APPDIR=${XDG_DATA_HOME:-$HOME/.local/share}/freefield
COPY=$APPDIR/start.sh
TOOLKIT_URL=https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
RAM_GB=0
KEY=''
DOWNLOADING=0
ENVS=''
DESKTOP=0                              # 1: Docker Desktop in WSL 2, which brings its own GPU support and VM

msg() {
  local key=$1
  shift
  local s
  case $key in
    title) s='Freefield on your own GPU' ;;
    gpu_ok) s='GPU: %s, %s GB of VRAM, CUDA %s' ;;
    gpu_none) s='No NVIDIA GPU found (no nvidia-smi). Freefield needs an NVIDIA card (24 GB for most apps) and its driver. Without one, use RunPod or Vast.ai in one click: https://github.com/neuregex/freefield#one-click-on-runpod-or-vastai' ;;
    driver_old) s='Your NVIDIA driver goes up to CUDA %s, and Freefield needs CUDA 13 (driver 580 or newer). Update it with your distribution'"'"'s driver tool or from https://www.nvidia.com/drivers, reboot, and run this again.' ;;
    gpu_old) s='%s is older than what CUDA 13 supports: it needs an RTX 20 series card or newer.' ;;
    vram_low) s='Only %s GB of VRAM: most apps need 24 GB, so some will not run on this card.' ;;
    docker_missing) s='Docker is not installed. Freefield runs inside it, so you do not need Python, CUDA or ComfyUI.' ;;
    docker_manual) s="Install Docker Engine (https://docs.docker.com/engine/install/) and the NVIDIA Container Toolkit ($TOOLKIT_URL), then run this again." ;;
    docker_perm)
      # shellcheck disable=SC2016  # $USER is for the reader to type
      s='Your user cannot use Docker yet. Add it to the docker group with "sudo usermod -aG docker $USER", log out and back in, and run this again.' ;;
    docker_down) s='Docker is installed but not running. Start it with "sudo systemctl start docker" and run this again.' ;;
    docker_fail) s='Docker did not answer:' ;;
    docker_ok) s='Docker %s, %s GB of RAM' ;;
    toolkit_missing) s="The NVIDIA Container Toolkit does not seem to be installed, and Docker needs it to reach the GPU: $TOOLKIT_URL" ;;
    hdd) s='Docker keeps Freefield in %s, which is on a hard disk: models load slowly from it, so the first image can take several minutes. On an SSD it takes seconds: move Docker'"'"'s data-root (/etc/docker/daemon.json) to an SSD.' ;;
    lowram) s='This computer has %s GB of RAM: apps that do not fit in the GPU spill into RAM, and with less than 16 GB they may close while they load a model.' ;;
    pulling) s='Getting the latest Freefield (about 4.5 GB the first time, only the changes after that)...' ;;
    pull_failed) s='Could not check for a new version (no internet?); starting the one you have.' ;;
    pull_none) s='Could not download Freefield. Check your internet connection and run this again.' ;;
    updating) s='There is a new version of Freefield: updating it (your models and history stay)...' ;;
    first_run) s='Downloading the models (%s GB, only this once). The studio opens in about a minute and shows how it goes.' ;;
    bg_download) s='The models keep downloading in the background: the studio shows how it goes, and each app works as soon as its files are in.' ;;
    starting) s='Starting Freefield...' ;;
    dl) s='Downloading models: %s of %s GB' ;;
    loading) s='Starting ComfyUI and the studio' ;;
    models_ok) s='Models ready (%s)' ;;
    ready) s='Freefield is ready: %s' ;;
    opening) s='Opening it in your browser.' ;;
    open_by_hand) s='Open that link in your browser.' ;;
    already) s='Freefield is already running.' ;;
    gpu_fail_desktop) s='Docker Desktop could not use the GPU. Update the NVIDIA driver on Windows (https://www.nvidia.com/drivers), check that Docker Desktop uses the WSL 2 based engine (Settings, General), and run this again.' ;;
    gpu_fail) s="Docker could not use the GPU. Install the NVIDIA Container Toolkit, run \"sudo nvidia-ctk runtime configure --runtime=docker\" and \"sudo systemctl restart docker\", then run this again: $TOOLKIT_URL" ;;
    port_busy) s='Port %s is busy; using %s.' ;;
    run_fail) s='Freefield did not start:' ;;
    exited) s='Freefield stopped (exit code %s). The end of its log:' ;;
    oom_desktop) s='It ran out of memory: Docker Desktop gives it %s GB of RAM. Give it more: put [wsl2] and memory=40GB on two lines in %%UserProfile%%\\.wslconfig, run "wsl --shutdown" in PowerShell and start it again.' ;;
    oom) s='It ran out of memory: this computer has %s GB of RAM. Close other programs, or use apps that fit in your GPU (the studio'"'"'s My GPU picker says which).' ;;
    log_saved) s='Its whole log (passcode and token removed) is in %s: attach it to an issue at https://github.com/neuregex/freefield/issues if you need help.' ;;
    stop_hint) s='Press Enter here to stop Freefield and free the GPU, or Ctrl+C to leave it running' ;;
    left_running) s='Freefield keeps running. Stop it later with: bash %s stop' ;;
    stopping) s='Stopping Freefield...' ;;
    stopped) s='Stopped. The models and the history stay; next time it starts in about a minute.' ;;
    not_installed) s='Freefield is not installed on this computer yet.' ;;
    uninstall_q) s='Remove the Freefield container, its image and this launcher?' ;;
    uninstall_models_q) s='Also delete the downloaded models and your history (the "freefield" volume)?' ;;
    uninstalled) s='Freefield removed.' ;;
    unknown_action) s='Unknown command "%s". Use start, stop, logs or uninstall.' ;;
    *) s=$key ;;
  esac
  # shellcheck disable=SC2059  # the formats are the messages above
  printf "$s" "$@"
}

if [ -t 1 ]; then
  C_OK=$'\033[32m' C_WARN=$'\033[33m' C_BAD=$'\033[31m' C_STEP=$'\033[36m' C_DIM=$'\033[90m' C_END=$'\033[0m'
else
  C_OK='' C_WARN='' C_BAD='' C_STEP='' C_DIM='' C_END=''
fi

say() {
  case $1 in
    ok) printf '  %s[ok]%s %s\n' "$C_OK" "$C_END" "$2" ;;
    warn) printf '  %s[!] %s %s\n' "$C_WARN" "$C_END" "$2" ;;
    bad) printf '  %s[x] %s %s\n' "$C_BAD" "$C_END" "$2" ;;
    step) printf '%s%s%s\n' "$C_STEP" "$2" "$C_END" ;;
    dim) printf '    %s%s%s\n' "$C_DIM" "$2" "$C_END" ;;
    *) printf '       %s\n' "$2" ;;
  esac
}

# one line that rewrites itself in a terminal; nothing when the output goes to a file
progress() { if [ -t 1 ]; then printf '\r\033[K  %s' "$1"; fi; }
progress_clear() { if [ -t 1 ]; then printf '\r\033[K'; fi; }

has_tty() { [ -r /dev/tty ] && [ -w /dev/tty ] && { : </dev/tty; } 2>/dev/null; }

# a yes/no question on the terminal, even when this script comes through "curl | bash"; no terminal = the default
ask() {
  local question=$1 default_yes=$2 suffix=' [y/N]' a=''
  [ "$default_yes" = 1 ] && suffix=' [Y/n]'
  if ! has_tty; then [ "$default_yes" = 1 ]; return; fi
  printf '%s%s ' "$question" "$suffix" >/dev/tty
  IFS= read -r a </dev/tty || a=''
  a=$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')
  if [ -z "$a" ]; then [ "$default_yes" = 1 ]; return; fi
  case $a in y* | s*) return 0 ;; *) return 1 ;; esac
}

fmt_dur() {
  local s=$1
  if [ "$s" -ge 60 ]; then printf '%d min %d s' $((s / 60)) $((s % 60)); else printf '%d s' "$s"; fi
}

dk() { docker "$@" </dev/null; }

check_gpu() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then say bad "$(msg gpu_none)"; return 1; fi
  local rows caps head best name mem cc cuda major gb
  rows=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null </dev/null)
  caps=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null </dev/null)
  head=$(nvidia-smi 2>/dev/null </dev/null)
  # the card with the most memory; compute capability 0 when this nvidia-smi does not know it (the check is skipped)
  best=$(awk -v caps="$caps" '
    BEGIN { n = split(caps, c, "\n") }
    {
      i++; k = index($0, ","); if (k == 0) next
      nm = substr($0, 1, k - 1); m = substr($0, k + 1)
      gsub(/^[ \t]+|[ \t]+$/, "", nm); gsub(/[^0-9.]/, "", m); if (m == "") next
      cap = (i <= n) ? c[i] : ""; gsub(/[^0-9.]/, "", cap); if (cap == "") cap = 0
      if (best == "" || m + 0 > bm) { best = nm; bm = m + 0; bc = cap + 0 }
    }
    END { if (best != "") printf "%s|%s|%s\n", best, bm, bc }' <<<"$rows")
  if [ -z "$best" ]; then say bad "$(msg gpu_none)"; return 1; fi
  IFS='|' read -r name mem cc <<<"$best"
  cuda=$(sed -nE 's/.*CUDA (UMD )?Version: *([0-9]+\.[0-9]+).*/\2/p' <<<"$head" | head -n 1)
  if [ -n "$cuda" ]; then major=${cuda%%.*}; else cuda='?'; major=99; fi
  if [ "$major" -lt 13 ]; then say bad "$(msg driver_old "$cuda")"; return 1; fi
  if awk -v c="$cc" 'BEGIN { exit !(c > 0 && c < 7.5) }'; then say bad "$(msg gpu_old "$name")"; return 1; fi
  gb=$(awk -v m="$mem" 'BEGIN { printf "%d", m / 1024 + 0.5 }')
  say ok "$(msg gpu_ok "$name" "$gb" "$cuda")"
  if [ "$gb" -lt 20 ]; then say warn "$(msg vram_low "$gb")"; fi
  return 0
}

# Docker and its engine: "OSType|version|memory|data root" on stdout, or a message and a failure
# WSL 2, the Linux inside Windows, where Docker is usually Docker Desktop's: WSL sets these in every terminal
is_wsl() { [ -n "${WSL_DISTRO_NAME:-}" ] || [ -n "${WSL_INTEROP:-}" ]; }

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    say bad "$(msg docker_missing)"
    say plain "$(msg docker_manual)"
    return 1
  fi
  local out line
  out=$(dk info --format '{{.OSType}}|{{.ServerVersion}}|{{.MemTotal}}|{{.DockerRootDir}}|{{.OperatingSystem}}' 2>&1)
  line=$(grep -m 1 -E '^linux\|' <<<"$out")
  if [ -z "$line" ]; then
    if grep -qi 'permission denied' <<<"$out"; then say bad "$(msg docker_perm)"
    elif grep -qiE 'cannot connect|is the docker daemon running' <<<"$out"; then say bad "$(msg docker_down)"
    else
      say bad "$(msg docker_fail)"
      while IFS= read -r l; do say dim "$l"; done < <(tail -n 5 <<<"$out")
    fi
    return 1
  fi
  local version mem root os
  IFS='|' read -r _ version mem root os <<<"$line"
  RAM_GB=$(awk -v m="$mem" 'BEGIN { printf "%.1f", m / 1073741824 }')
  say ok "$(msg docker_ok "$version" "$RAM_GB")"
  if awk -v r="$RAM_GB" 'BEGIN { exit !(r > 0 && r < 16) }'; then say warn "$(msg lowram "$RAM_GB")"; fi
  # Docker Desktop in WSL 2 reaches the GPU without the toolkit, and keeps its data in its own VM, out of sight here.
  # WSL's own disks are virtual: what lsblk says of them is no sign of a hard disk
  if is_wsl; then
    if [ "$os" = "Docker Desktop" ]; then DESKTOP=1; return 0; fi
    root=''
  fi
  if ! command -v nvidia-container-runtime-hook >/dev/null 2>&1 && ! command -v nvidia-ctk >/dev/null 2>&1 \
    && ! command -v nvidia-container-cli >/dev/null 2>&1; then
    say warn "$(msg toolkit_missing)"
  fi
  if [ -n "$root" ]; then check_disk "$root"; fi
  return 0
}

# Docker keeps the image and the models' volume in its data root; on a hard disk every model loads at ~100 MB/s,
# which makes the first image take minutes: say so. Quiet when it cannot tell.
check_disk() {
  local root=${1:-/var/lib/docker} src rota
  command -v findmnt >/dev/null 2>&1 && command -v lsblk >/dev/null 2>&1 || return 0
  src=$(findmnt -no SOURCE -T "$root" 2>/dev/null | head -n 1)
  case $src in /dev/*) ;; *) return 0 ;; esac
  rota=$(lsblk -dno ROTA "$src" 2>/dev/null | head -n 1 | tr -d ' ')
  if [ "$rota" = 1 ]; then say warn "$(msg hdd "$root")"; fi
  return 0
}

# Freefield's container now: "status|image id", empty when there is none. "container inspect": a bare
# "docker inspect freefield" also finds the volume of that name once the container is gone
box_state() { dk container inspect "$NAME" --format '{{.State.Status}}|{{.Image}}' 2>/dev/null | head -n 1; }

# the env it was made with (HF_TOKEN and FREEFIELD_*), one KEY=value per line
box_env() {
  dk container inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null |
    grep -E '^(HF_TOKEN|FREEFIELD_[A-Z0-9_]+)=' || true
}

# its port binding "ip|port" (the studio's 3000 inside)
box_port() {
  # shellcheck disable=SC2016  # a Go template, not shell
  local fmt='{{range $p, $b := .HostConfig.PortBindings}}{{if eq $p "3000/tcp"}}{{range $b}}{{.HostIp}}|{{.HostPort}}{{println}}{{end}}{{end}}{{end}}'
  dk container inspect "$NAME" --format "$fmt" 2>/dev/null | grep -m 1 '|' || true
}

env_get() { grep -m 1 "^$1=" <<<"$ENVS" | cut -d= -f2- || true; }

env_set() {
  local k=$1 v=$2
  ENVS=$(grep -v "^$k=" <<<"$ENVS" || true)
  ENVS=$(printf '%s\n%s=%s' "$ENVS" "$k" "$v" | sed '/^$/d')
}

port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

find_port() {
  local p
  for p in $(seq 3000 3020); do
    if port_free "$p"; then
      if [ "$p" != 3000 ]; then say warn "$(msg port_busy 3000 "$p")" >&2; fi
      echo "$p"
      return
    fi
  done
  echo 3000
}

# docker run, with HF_TOKEN and FREEFIELD_* passed through the environment (never on the command line)
new_box() {
  local port=$1 bind=$2 map line k v
  local -a args sets=()
  if [ -n "$bind" ] && [ "$bind" != 0.0.0.0 ]; then map="$bind:$port:3000"; else map="$port:3000"; fi
  args=(run -d --name "$NAME" --gpus all -p "$map" -v "$NAME:/workspace")
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    k=${line%%=*}
    v=${line#*=}
    [ -n "$v" ] || continue
    sets+=("$k=$v")
    args+=(-e "$k")
  done <<<"$ENVS"
  env "${sets[@]}" docker "${args[@]}" "$IMAGE" </dev/null 2>&1
}

show_run_error() {
  say bad "$(msg run_fail)"
  while IFS= read -r l; do say dim "$l"; done < <(tail -n 8 <<<"$1")
  if grep -qiE 'gpu|nvidia|device driver' <<<"$1"; then
    if [ "$DESKTOP" = 1 ]; then say warn "$(msg gpu_fail_desktop)"; else say warn "$(msg gpu_fail)"; fi
  fi
}

save_log() {
  mkdir -p "$APPDIR" 2>/dev/null || return 0
  local f=$APPDIR/freefield-log.txt
  dk logs "$NAME" 2>&1 | sed -E 's/(\?key=)[^[:space:]]+/\1<passcode>/g; s/(Passcode:[[:space:]]+)[^[:space:]]+/\1<passcode>/g; s/(FREEFIELD_TOKEN=)[^[:space:]]+/\1<token>/g' >"$f" 2>/dev/null &&
    say plain "$(msg log_saved "$f")"
}

# follows the log from $1: download progress, errors, then the banner's passcode (KEY, '' if Freefield stopped) and
# whether the models keep downloading after it (DOWNLOADING: the studio shows that part). With $2=1 (Freefield was
# already running) what the log said before is not told again, only what comes next.
wait_ready() {
  local since=$1 attach=$2
  local down='↓' cross='✗'
  local seen=0 need=0 done_gb=0 got=0 key='' ready=0 bg=0 hint=0 quiet=$attach
  local t0=$SECONDS last_du=-10 st code oom elapsed part pct i l
  local -a lines
  while :; do
    mapfile -t lines < <(dk logs --since "$since" "$NAME" 2>&1)
    for ((i = seen; i < ${#lines[@]}; i++)); do
      l=${lines[i]}
      if [[ $l =~ ^packs\ .*\ ([0-9]+)\ to\ download\ \(([0-9.]+)\ GB\) ]]; then
        if [ "${BASH_REMATCH[1]}" -gt 0 ]; then
          need=${BASH_REMATCH[2]}
          if [ "$quiet" = 0 ]; then progress_clear; say step "$(msg first_run "$need")"; fi
        fi
        hint=0
      elif [[ $l =~ ^[[:space:]]+${down}[[:space:]]+([^[:space:]]+)[[:space:]]+([0-9.]+)\ GB ]]; then
        done_gb=$(awk -v a="$done_gb" -v b="${BASH_REMATCH[2]}" 'BEGIN { printf "%.3f", a + b }')
        if [ "$quiet" = 0 ]; then progress_clear; say ok "${BASH_REMATCH[1]}  ${BASH_REMATCH[2]} GB"; fi
        hint=0
      elif [[ $l =~ ^[[:space:]]+${cross}[[:space:]]+(.+)$ ]]; then
        progress_clear
        say bad "${BASH_REMATCH[1]}"
        hint=1
      elif [ "$hint" = 1 ] && [[ $l =~ ^[[:space:]]{4}[^[:space:]] ]]; then
        say plain "  ${l#"${l%%[![:space:]]*}"}"
      elif [[ $l =~ ^models\ ready\ in\ ([0-9]+)\ s ]]; then
        need=0
        if [ "$quiet" = 0 ]; then progress_clear; say ok "$(msg models_ok "$(fmt_dur "${BASH_REMATCH[1]}")")"; fi
        hint=0
      elif [[ $l =~ ^!\ (.+)$ ]]; then
        local m=${BASH_REMATCH[1]} studio=0
        [[ $m == *"Models panel"* ]] && studio=1   # the studio shows it, with the button that fixes it
        if [ "$quiet" = 0 ] && [ "$studio" = 0 ]; then progress_clear; say warn "$m"; fi
        [[ $m == *"could not be downloaded"* ]] && need=0
        if [ "$quiet" = 0 ] && [ "$studio" = 0 ]; then hint=1; else hint=0; fi   # the links under it
      elif [[ $l == *"The models are still downloading"* ]]; then
        bg=1
      elif [[ $l =~ ^Freefield\ is\ ready\ on ]]; then
        ready=1
      elif [[ $l =~ \?key=([^[:space:]]+) ]]; then
        key=${BASH_REMATCH[1]}
      else
        hint=0
      fi
    done
    seen=${#lines[@]}
    quiet=0
    if [ "$ready" = 1 ] && [ -n "$key" ]; then break; fi

    st=$(dk container inspect "$NAME" --format '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}' 2>/dev/null | head -n 1)
    if [ -n "$st" ] && [[ $st != running* ]]; then
      progress_clear
      IFS='|' read -r _ code oom <<<"$st"
      say bad "$(msg exited "$code")"
      local from=$((${#lines[@]} > 25 ? ${#lines[@]} - 25 : 0))
      for l in "${lines[@]:from}"; do say dim "$l"; done
      if [ "$code" = 137 ] || [ "$oom" = true ]; then
        if [ "$DESKTOP" = 1 ]; then say warn "$(msg oom_desktop "$RAM_GB")"; else say warn "$(msg oom "$RAM_GB")"; fi
      fi
      save_log
      KEY=''
      DOWNLOADING=0
      return 1
    fi
    elapsed=$(fmt_dur $((SECONDS - t0)))
    if awk -v n="$need" 'BEGIN { exit !(n > 0) }'; then
      if [ $((SECONDS - last_du)) -ge 5 ]; then
        last_du=$SECONDS
        part=$(dk exec "$NAME" du -sb /workspace/freefield/models/.incoming 2>/dev/null | awk 'NR == 1 { print $1 + 0 }')
        got=$(awk -v n="$need" -v d="$done_gb" -v p="${part:-0}" 'BEGIN { g = d + p / 1e9; if (g > n) g = n; printf "%.1f", g }')
      fi
      pct=$(awk -v g="$got" -v n="$need" 'BEGIN { p = int(100 * g / n); if (p > 99) p = 99; print p }')
      progress "$(msg dl "$got" "$need")  ($pct%)  -  $elapsed"
    else
      progress "$(msg loading)  -  $elapsed"
    fi
    sleep 2
  done
  progress_clear
  KEY=$key
  if [ "$bg" = 1 ] && [ "$attach" = 0 ]; then DOWNLOADING=1; else DOWNLOADING=0; fi
  return 0
}

# keeps a copy of this launcher, for stop, logs and uninstall
save_copy() {
  mkdir -p "$APPDIR" 2>/dev/null || return 0
  local tmp=$APPDIR/start.sh.new
  if command -v curl >/dev/null 2>&1; then curl -fsSL --max-time 20 "$RAW/start.sh" -o "$tmp" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then wget -q -T 20 -O "$tmp" "$RAW/start.sh" 2>/dev/null
  fi
  if [ -s "$tmp" ] && grep -q 'neuregex/freefield' "$tmp"; then
    mv -f "$tmp" "$COPY" && chmod +x "$COPY"
  else
    rm -f "$tmp"
  fi
  return 0
}

# In WSL the browser is Windows': wslview or explorer.exe open the link there
open_url() {
  if is_wsl; then
    local opener
    for opener in wslview explorer.exe; do
      if command -v "$opener" >/dev/null 2>&1; then
        "$opener" "$1" >/dev/null 2>&1 &
        return 0
      fi
    done
  fi
  if { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; } && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 &
    return 0
  fi
  return 1
}

# Enter stops Freefield; Ctrl+C, or no terminal to wait in, leaves it running
wait_enter() {
  local hint
  hint=$(msg left_running "$COPY")
  if ! has_tty; then echo; say plain "$hint"; return 1; fi
  trap 'echo; say plain "$hint"; exit 0' INT
  echo
  printf '%s: ' "$(msg stop_hint)"
  read -r _ </dev/tty || true
  trap - INT
  return 0
}

main() {
  export LC_NUMERIC=C DOCKER_CLI_HINTS=false   # dots in numbers; no "What's next: docker scout ..." after the pull
  local action=${1:-start}
  action=$(printf '%s' "$action" | tr '[:upper:]' '[:lower:]')
  case $action in start | stop | logs | uninstall) ;; *) say bad "$(msg unknown_action "$action")"; return 2 ;; esac

  echo
  say step "$(msg title)"

  if [ "$action" = start ]; then check_gpu || return 1; fi
  check_docker || return 1

  local state status image_id
  state=$(box_state)
  status=${state%%|*}
  image_id=${state#*|}

  case $action in
    stop)
      if [ -n "$state" ]; then
        say step "$(msg stopping)"
        dk stop -t 30 "$NAME" >/dev/null 2>&1
        say ok "$(msg stopped)"
      else
        say warn "$(msg not_installed)"
      fi
      return 0
      ;;
    logs)
      if [ -n "$state" ]; then dk logs --tail 300 "$NAME"; else say warn "$(msg not_installed)"; fi
      return 0
      ;;
    uninstall)
      ask "$(msg uninstall_q)" 0 || return 0
      dk rm -f "$NAME" >/dev/null 2>&1
      if ask "$(msg uninstall_models_q)" 0; then dk volume rm "$NAME" >/dev/null 2>&1; fi
      dk image rm "$IMAGE" >/dev/null 2>&1
      rm -rf "$APPDIR"
      say ok "$(msg uninstalled)"
      return 0
      ;;
  esac

  local attach=0 out port='' bind='' recreate=0 new_id pulled
  if [ "$status" = running ]; then
    attach=1
    say ok "$(msg already)"
  else
    # nothing to ask: the image decides the packs unless FREEFIELD_PACKS says otherwise, and the studio asks for a
    # Hugging Face token when a model needs one (Models panel), as on RunPod and Vast.ai
    if [ -n "$state" ]; then
      ENVS=$(box_env)
    elif [ -n "${HF_TOKEN:-}" ]; then
      env_set HF_TOKEN "$(printf '%s' "$HF_TOKEN" | tr -d '[:space:]')"
    fi
    if [ -n "${FREEFIELD_PACKS:-}" ] && [ "$FREEFIELD_PACKS" != "$(env_get FREEFIELD_PACKS)" ]; then
      env_set FREEFIELD_PACKS "$FREEFIELD_PACKS"
      recreate=1
    fi

    echo
    say step "$(msg pulling)"
    if dk pull "$IMAGE"; then pulled=1; else pulled=0; fi
    new_id=$(dk image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null | grep -m 1 '^sha256:' || true)
    if [ -z "$new_id" ]; then say bad "$(msg pull_none)"; return 1; fi
    if [ "$pulled" = 0 ]; then say warn "$(msg pull_failed)"; fi

    if [ -n "$state" ] && [ "$image_id" != "$new_id" ]; then say step "$(msg updating)"; else say step "$(msg starting)"; fi
    if [ -n "$state" ]; then
      IFS='|' read -r bind port <<<"$(box_port)"
      port=${port:-3000}
      [ "$image_id" != "$new_id" ] && recreate=1
      if [ "$recreate" = 1 ]; then
        dk rm -f "$NAME" >/dev/null 2>&1
        if ! out=$(new_box "$port" "$bind"); then show_run_error "$out"; return 1; fi
        if [ "$image_id" != "$new_id" ]; then dk image rm "$image_id" >/dev/null 2>&1; fi   # kept if anything else uses it
      else
        if ! out=$(dk start "$NAME" 2>&1); then show_run_error "$out"; return 1; fi
      fi
    else
      port=$(find_port)
      bind=127.0.0.1
      if ! out=$(new_box "$port" "$bind"); then show_run_error "$out"; return 1; fi
    fi
  fi

  IFS='|' read -r bind port <<<"$(box_port)"
  port=${port:-3000}
  local started since
  started=$(dk container inspect "$NAME" --format '{{.State.StartedAt}}' 2>/dev/null | head -n 1)
  since=$started
  if [ ${#started} -ge 19 ]; then since="${started:0:19}Z"; fi
  wait_ready "$since" "$attach" || return 1
  [ -n "$KEY" ] || return 1

  local url="http://127.0.0.1:$port/?key=$KEY"
  echo
  say ok "$(msg ready "$url")"
  if open_url "$url"; then say plain "$(msg opening)"; else say plain "$(msg open_by_hand)"; fi
  if [ "$DOWNLOADING" = 1 ]; then say plain "$(msg bg_download)"; fi

  save_copy
  wait_enter || return 0
  say step "$(msg stopping)"
  dk stop -t 30 "$NAME" >/dev/null 2>&1
  say ok "$(msg stopped)"
}

main "$@"

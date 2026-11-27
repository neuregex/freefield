// start.sh, the Linux launcher, against a fake docker, nvidia-smi and friends: what it says and which docker commands
// it runs. Each run gets its own session (setsid), so there is no terminal to wait in, as in a pipe.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "start.sh");
const TOOLS = ["bash", "awk", "sed", "grep", "tr", "head", "tail", "cut", "seq", "sleep", "mkdir", "rm", "mv", "chmod",
  "cat", "cp", "env"];
const SETSID = ["/usr/bin/setsid", "/bin/setsid"].find((p) => existsSync(p));
const canRun = SETSID !== undefined;

// The fake docker keeps its state in files under $MOCK: the container (status, image, env, port), the image that a
// pull gives, the log, and every call it got.
const DOCKER = `#!/bin/bash
M=$MOCK
echo "$*" >> "$M/calls"
c="$M/box"
case "$1" in
  info)
    if [ -f "$M/info_error" ]; then cat "$M/info_error" >&2; exit 1; fi
    if [ -f "$M/info" ]; then cat "$M/info"; exit 0; fi
    echo "linux|27.3.1|67430019072|/var/lib/docker|Ubuntu 24.04.3 LTS"; exit 0 ;;
  container)
    [ -d "$c" ] || { echo "Error: No such container: freefield" >&2; exit 1; }
    f="$5"
    case "$f" in
      *'.State.Status}}|{{.Image'*) echo "$(cat "$c/status")|$(cat "$c/image")" ;;
      *'.Config.Env'*) cat "$c/env" ;;
      *PortBindings*) cat "$c/port" ;;
      *ExitCode*) echo "$(cat "$c/status")|$(cat "$c/code" 2>/dev/null || echo 0)|$(cat "$c/oom" 2>/dev/null || echo false)" ;;
      *StartedAt*) echo "2026-11-27T21:00:00.123456789Z" ;;
    esac
    exit 0 ;;
  pull)
    if [ -f "$M/pull_fail" ]; then echo "error pulling" >&2; exit 1; fi
    cp "$M/next_image" "$M/image"; echo "latest: Pulling from neuregex/freefield"; exit 0 ;;
  image)
    if [ "$2" = inspect ]; then [ -f "$M/image" ] && cat "$M/image" && exit 0; exit 1; fi
    exit 0 ;;
  run)
    if [ -f "$M/run_fail" ]; then cat "$M/run_fail" >&2; exit 125; fi
    mkdir -p "$c"; : > "$c/env"
    shift
    while [ $# -gt 1 ]; do
      case "$1" in
        -p) echo "$2" > "$M/run_map"; ip=127.0.0.1; p=\${2%%:3000}; case "$p" in *:*) ip=\${p%%:*}; p=\${p#*:} ;; *) ip=0.0.0.0 ;; esac
            echo "$ip|$p" > "$c/port"; shift ;;
        -e) echo "$2=\${!2}" >> "$c/env"; shift ;;
        --name|-v|--gpus) shift ;;
      esac
      shift
    done
    cat "$M/image" > "$c/image"
    if [ -f "$M/exit_after_run" ]; then echo exited > "$c/status"; echo 137 > "$c/code"; echo true > "$c/oom"
    else echo running > "$c/status"; fi
    echo 0123456789ab; exit 0 ;;
  start) echo running > "$c/status"; exit 0 ;;
  stop) echo exited > "$c/status"; exit 0 ;;
  rm) rm -rf "$c"; exit 0 ;;
  logs) cat "$M/logs" 2>/dev/null; exit 0 ;;
  exec) echo "1000000000 /workspace/freefield/models/.incoming"; exit 0 ;;
  volume) exit 0 ;;
esac
exit 0
`;

const NVIDIA_SMI = `#!/bin/bash
case "$*" in
  *name,memory.total*) cat "$MOCK/gpu" ;;
  *compute_cap*) cat "$MOCK/cc" ;;
  *) echo "| NVIDIA-SMI 580.95   Driver Version: 580.95   CUDA Version: $(cat "$MOCK/cuda") |" ;;
esac
`;

const READY_LOG = [
  "packs image-flux3, upscale: 40 files, 2 to download (22.9 GB); 500 GB free in /workspace/freefield",
  "  ↓ flux-3-klein.safetensors  11.5 GB",
  "  ↓ qwen3-4b.safetensors  8.0 GB",
  "models ready in 95 s",
  "",
  "========================================================================",
  "Freefield is ready on this computer.",
  "  Open:      http://127.0.0.1:3000/?key=Zq0vSECRET",
  "  Passcode:  Zq0vSECRET   (kept in /workspace/freefield/passcode; FREEFIELD_PASSCODE sets your own)",
  "  Your own studio instead, in its .env: COMFY_BASE_URL=<port 8000 of this machine> and FREEFIELD_TOKEN=tok123",
  "========================================================================",
].join("\n");

type Setup = {
  gpu?: string | null; cc?: string; cuda?: string; docker?: boolean; infoError?: string; box?: {
    status: string; image: string; env?: string; port?: string;
  }; nextImage?: string; logs?: string; runFail?: string; exitAfterRun?: boolean; hdd?: boolean;
  desktop?: boolean; // Docker Desktop: its docker reaches the GPU, and there is no toolkit in this Linux
};

function run(setup: Setup, args: string[] = [], extraEnv: Record<string, string> = {}) {
  const root = mkdtempSync(join(tmpdir(), "ff-start-sh-"));
  const mock = join(root, "mock");
  const bin = join(root, "bin");
  mkdirSync(mock);
  mkdirSync(bin);
  for (const t of TOOLS) {
    const src = ["/usr/bin", "/bin"].map((d) => join(d, t)).find((p) => existsSync(p));
    if (src) symlinkSync(src, join(bin, t));
  }
  const put = (name: string, body: string) => {
    writeFileSync(join(bin, name), body);
    chmodSync(join(bin, name), 0o755);
  };
  if (setup.gpu !== null) {
    put("nvidia-smi", NVIDIA_SMI);
    writeFileSync(join(mock, "gpu"), (setup.gpu ?? "NVIDIA GeForce RTX 3090 Ti, 24564") + "\n");
    writeFileSync(join(mock, "cc"), (setup.cc ?? "8.6") + "\n");
    writeFileSync(join(mock, "cuda"), setup.cuda ?? "13.0");
  }
  if (setup.docker !== false) {
    put("docker", DOCKER);
    if (!setup.desktop) put("nvidia-ctk", "#!/bin/bash\nexit 0\n");
  }
  if (setup.desktop) writeFileSync(join(mock, "info"), "linux|28.5.1|33608093696|/var/lib/docker|Docker Desktop\n");
  put("xdg-open", `#!/bin/bash\necho "$1" > "$MOCK/opened"\n`);
  put("explorer.exe", `#!/bin/bash\necho "$1" > "$MOCK/opened_windows"\n`);
  put("curl", `#!/bin/bash\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && { echo "# neuregex/freefield launcher" > "$2"; }; shift; done\n`);
  put("findmnt", "#!/bin/bash\necho /dev/sda1\n");
  put("lsblk", `#!/bin/bash\n${setup.hdd ? "echo 1" : "echo 0"}\n`);
  if (setup.infoError) writeFileSync(join(mock, "info_error"), setup.infoError);
  writeFileSync(join(mock, "next_image"), setup.nextImage ?? "sha256:new");
  if (setup.box) {
    const c = join(mock, "box");
    mkdirSync(c);
    writeFileSync(join(c, "status"), setup.box.status);
    writeFileSync(join(c, "image"), setup.box.image);
    writeFileSync(join(c, "env"), setup.box.env ?? "");
    writeFileSync(join(c, "port"), setup.box.port ?? "127.0.0.1|3000");
    writeFileSync(join(mock, "image"), setup.box.image);
  }
  writeFileSync(join(mock, "logs"), setup.logs ?? READY_LOG);
  if (setup.runFail) writeFileSync(join(mock, "run_fail"), setup.runFail);
  if (setup.exitAfterRun) writeFileSync(join(mock, "exit_after_run"), "");
  const data = join(root, "data");
  const r = spawnSync(SETSID!, ["-w", "bash", SCRIPT, ...args], {
    env: { PATH: bin, HOME: root, XDG_DATA_HOME: data, MOCK: mock, DISPLAY: ":0", ...extraEnv },
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 20000,
  });
  const read = (f: string) => (existsSync(join(mock, f)) ? readFileSync(join(mock, f), "utf8") : "");
  return {
    code: r.status, out: (r.stdout ?? "") + (r.stderr ?? ""), calls: read("calls"), opened: read("opened").trim(),
    openedWindows: read("opened_windows").trim(),
    map: read("run_map").trim(), boxEnv: read("box/env"), data, mock,
  };
}

test("no NVIDIA GPU: points to RunPod and Vast.ai and stops", { skip: !canRun }, () => {
  const r = run({ gpu: null });
  assert.equal(r.code, 1);
  assert.match(r.out, /No NVIDIA GPU found/);
  assert.match(r.out, /one-click-on-runpod-or-vastai/);
  assert.equal(r.calls, "", "docker is never called");
});

test("a driver older than CUDA 13 and a card older than Turing are refused", { skip: !canRun }, () => {
  const old = run({ cuda: "12.4" });
  assert.equal(old.code, 1);
  assert.match(old.out, /goes up to CUDA 12\.4, and Freefield needs CUDA 13 \(driver 580 or newer\)/);
  const pascal = run({ gpu: "NVIDIA GeForce GTX 1080 Ti, 11264", cc: "6.1" });
  assert.equal(pascal.code, 1);
  assert.match(pascal.out, /GTX 1080 Ti is older than what CUDA 13 supports/);
});

test("no Docker: says what to install, with the toolkit, and never runs sudo", { skip: !canRun }, () => {
  const r = run({ docker: false });
  assert.equal(r.code, 1);
  assert.match(r.out, /Docker is not installed/);
  assert.match(r.out, /Install Docker Engine .* and the NVIDIA Container Toolkit/);
});

test("a user outside the docker group gets the usermod line; a stopped daemon, systemctl", { skip: !canRun }, () => {
  const perm = run({ infoError: "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock" });
  assert.equal(perm.code, 1);
  assert.match(perm.out, /sudo usermod -aG docker \$USER/);
  const down = run({ infoError: "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" });
  assert.match(down.out, /sudo systemctl start docker/);
});

test("first start: pull, run on 127.0.0.1 with the token in the environment, open the studio with its passcode", { skip: !canRun }, () => {
  const r = run({}, [], { HF_TOKEN: " hf_abc123 " });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /GPU: NVIDIA GeForce RTX 3090 Ti, 24 GB of VRAM, CUDA 13\.0/);
  assert.match(r.out, /Downloading the models \(22\.9 GB, only this once\)/);
  assert.match(r.out, /\[ok\] flux-3-klein\.safetensors {2}11\.5 GB/);
  assert.match(r.out, /Models ready \(1 min 35 s\)/);
  assert.match(r.out, /Freefield is ready: http:\/\/127\.0\.0\.1:3\d{3}\/\?key=Zq0vSECRET/);
  assert.match(r.opened, /^http:\/\/127\.0\.0\.1:3\d{3}\/\?key=Zq0vSECRET$/);
  assert.match(r.map, /^127\.0\.0\.1:3\d{3}:3000$/);
  assert.match(r.calls, /^run -d --name freefield --gpus all -p 127\.0\.0\.1:3\d{3}:3000 -v freefield:\/workspace -e HF_TOKEN ghcr\.io\/neuregex\/freefield:latest$/m);
  assert.doesNotMatch(r.calls, /hf_abc123/, "the token never goes on the command line");
  assert.match(r.boxEnv, /^HF_TOKEN=hf_abc123$/m, "it reaches the container, trimmed");
  assert.match(r.out, /Freefield keeps running\. Stop it later with: bash .*freefield\/start\.sh stop/);
  assert.doesNotMatch(r.calls, /^stop/m, "without a terminal to wait in, it is left running");
  assert.ok(existsSync(join(r.data, "freefield", "start.sh")), "it keeps a copy for stop, logs and uninstall");
});

test("already running: no pull and no run, only the link again", { skip: !canRun }, () => {
  const r = run({ box: { status: "running", image: "sha256:old", port: "127.0.0.1|3004" } });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Freefield is already running/);
  assert.doesNotMatch(r.out, /Downloading the models/, "what the log said before is not told again");
  assert.match(r.out, /Freefield is ready: http:\/\/127\.0\.0\.1:3004\/\?key=Zq0vSECRET/);
  assert.doesNotMatch(r.calls, /^(pull|run)/m);
});

test("a new image: the container is made again with its env and port, and the old image goes", { skip: !canRun }, () => {
  const r = run({
    box: { status: "exited", image: "sha256:old", env: "FREEFIELD_PACKS=all-lite\nHF_TOKEN=hf_keep", port: "127.0.0.1|3005" },
    nextImage: "sha256:new",
  });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /There is a new version of Freefield/);
  assert.match(r.calls, /^rm -f freefield$/m);
  assert.match(r.calls, /^run .* -p 127\.0\.0\.1:3005:3000 .*-e FREEFIELD_PACKS -e HF_TOKEN /m);
  assert.match(r.boxEnv, /^FREEFIELD_PACKS=all-lite$/m);
  assert.match(r.calls, /^image rm sha256:old$/m);
});

test("same image and nothing to change: docker start, not a new container", { skip: !canRun }, () => {
  const r = run({ box: { status: "exited", image: "sha256:same", port: "127.0.0.1|3000" }, nextImage: "sha256:same" });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Starting Freefield/);
  assert.match(r.calls, /^start freefield$/m);
  assert.doesNotMatch(r.calls, /^run /m);
});

test("docker run cannot reach the GPU: the toolkit's two commands", { skip: !canRun }, () => {
  const r = run({ runFail: 'docker: Error response from daemon: could not select device driver "" with capabilities: [[gpu]].' });
  assert.equal(r.code, 1);
  assert.match(r.out, /Freefield did not start/);
  assert.match(r.out, /sudo nvidia-ctk runtime configure --runtime=docker/);
});

test("it dies while loading: the end of the log, the memory hint, and a saved log without the passcode", { skip: !canRun }, () => {
  const r = run({ exitAfterRun: true, logs: "packs image-flux3: 40 files, 0 to download (0.0 GB); 500 GB free\nKilled\n  Open: http://127.0.0.1:3000/?key=LEAKED" });
  assert.equal(r.code, 1);
  assert.match(r.out, /Freefield stopped \(exit code 137\)/);
  assert.match(r.out, /It ran out of memory/);
  const log = readFileSync(join(r.data, "freefield", "freefield-log.txt"), "utf8");
  assert.doesNotMatch(log, /LEAKED/);
  assert.match(log, /\?key=<passcode>/);
});

test("stop stops; uninstall without a terminal answers no and removes nothing", { skip: !canRun }, () => {
  const stop = run({ box: { status: "running", image: "sha256:x" } }, ["stop"]);
  assert.equal(stop.code, 0);
  assert.match(stop.out, /Stopped\. The models and the history stay/);
  assert.match(stop.calls, /^stop -t 30 freefield$/m);
  const un = run({ box: { status: "running", image: "sha256:x" } }, ["uninstall"]);
  assert.equal(un.code, 0);
  assert.doesNotMatch(un.calls, /^(rm|volume|image rm)/m);
});

test("Docker's data on a hard disk is flagged", { skip: !canRun }, () => {
  const r = run({ hdd: true });
  assert.match(r.out, /which is on a hard disk/);
});

test("WSL 2 with Docker Desktop: no toolkit or disk warning, Windows' browser, and Windows' hints", { skip: !canRun }, () => {
  const wsl = { WSL_DISTRO_NAME: "Ubuntu" };
  const r = run({ desktop: true, hdd: true }, [], wsl);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Docker 28\.5\.1, 31\.3 GB of RAM/);
  assert.doesNotMatch(r.out, /Container Toolkit|hard disk/);
  assert.match(r.openedWindows, /^http:\/\/127\.0\.0\.1:3\d{3}\/\?key=Zq0vSECRET$/);
  assert.equal(r.opened, "", "not a browser inside WSL");
  const gpu = run({ desktop: true, runFail: 'docker: Error response from daemon: could not select device driver "" with capabilities: [[gpu]].' }, [], wsl);
  assert.match(gpu.out, /Docker Desktop could not use the GPU\. Update the NVIDIA driver on Windows/);
  assert.doesNotMatch(gpu.out, /nvidia-ctk/);
  const oom = run({ desktop: true, exitAfterRun: true, logs: "Killed" }, [], wsl);
  assert.match(oom.out, /Docker Desktop gives it 31\.3 GB of RAM\. .*%UserProfile%\\\.wslconfig/);
  const engine = run({ hdd: true }, [], wsl);
  assert.doesNotMatch(engine.out, /hard disk/, "WSL's virtual disk says nothing about the drive under it");
  assert.equal(engine.openedWindows.length > 0, true, "the link still opens in Windows");
});

#!/usr/bin/env python3
"""Lab queue: runs lab jobs that show up as files, one at a time, with your own Modal login.

    python tools/lab_queue.py                 # watch lab/queue/ until Ctrl+C
    python tools/lab_queue.py --once          # run what is queued now, then exit
    python tools/lab_queue.py --max-jobs 12 --max-cases 60

Whoever wants a run (you, or an assistant working in this folder) writes lab/queue/<name>.job.json:

    {"only": "tpl-face-swap,tplx-face-swap-*", "shards": 1, "note": "why this run"}

The watcher runs exactly `modal run lab/lab_modal.py --only <only> [--shards N]` from the repo root, prints
the output and saves it to lab/queue/<name>.log, then writes lab/queue/<name>.done.json (exit code, run id,
"N/M ok", times) and renames the job to <name>.job.done.json. Nothing else can be asked for: no deploy, no other
script, no extra arguments. "only" may hold case ids and fnmatch patterns from lab/cases.json and nothing else.

Limits: at most --max-cases cases matched per job (default 60) and --max-jobs jobs per calendar day (default 12).
A file lab/queue/STOP pauses it (jobs wait until the file is gone); a job over a limit is refused with a
<name>.refused.json that says why.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "lab" / "queue"
NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ONLY = re.compile(r"^[a-z0-9*?,\-]{1,2000}$")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def case_ids() -> list[str]:
    return [c["id"] for c in json.loads((ROOT / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]]


def check_job(name: str, job: dict, max_cases: int) -> tuple[list[str] | None, str]:
    """The case ids a job selects, or None and the reason it is refused."""
    if not NAME.match(name):
        return None, "job name must be letters, digits, - and _"
    if set(job) - {"only", "shards", "note"}:
        return None, f"unknown keys: {sorted(set(job) - {'only', 'shards', 'note'})}"
    only = job.get("only")
    if not isinstance(only, str) or not ONLY.match(only):
        return None, "only must be case ids or patterns: a-z 0-9 - * ? and commas"
    shards = job.get("shards", 1)
    if not isinstance(shards, int) or not 1 <= shards <= 4:
        return None, "shards must be 1 to 4"
    ids = case_ids()
    wanted = [w for w in only.split(",") if w]
    unknown = [w for w in wanted if not any(fnmatch(i, w) for i in ids)]
    if unknown:
        return None, f"no case matches: {', '.join(unknown)}"
    picked = sorted({i for w in wanted for i in ids if fnmatch(i, w)})
    if len(picked) > max_cases:
        return None, f"{len(picked)} cases is over the limit of {max_cases}"
    return picked, ""


def jobs_today() -> int:
    today = dt.date.today().isoformat()
    n = 0
    for p in QUEUE.glob("*.done.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("started", "").startswith(today):
                n += 1
        except (OSError, ValueError):
            pass
    return n


def modal_cmd() -> list[str]:
    exe = os.environ.get("LAB_QUEUE_MODAL") or shutil.which("modal")
    return [exe] if exe else [sys.executable, "-m", "modal"]


def run_job(name: str, job: dict, picked: list[str]) -> dict:
    args = modal_cmd() + ["run", "lab/lab_modal.py", "--only", job["only"]]
    if job.get("shards", 1) > 1:
        args += ["--shards", str(job["shards"])]
    log_path = QUEUE / f"{name}.log"
    started, t0 = now(), time.time()
    print(f"\n[{started}] {name}: {len(picked)} cases · {' '.join(args[1:])}", flush=True)
    run_id, ok_line, rc = None, None, None
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"# {started} {' '.join(args)}\n# note: {job.get('note', '')}\n")
        proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
            m = re.search(r"lab[\\/]results[\\/](\d{8}-\d{6}-[a-z0-9]+)", line)
            if m:
                run_id = m.group(1)
            m = re.match(r"^\s*(\d+/\d+ ok)\s*$", line)
            if m:
                ok_line = m.group(1)
        rc = proc.wait()
    return {"name": name, "job": job, "cases": picked, "returncode": rc, "run_id": run_id, "result": ok_line,
            "started": started, "finished": now(), "seconds": round(time.time() - t0, 1), "log": log_path.name}


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def pass_once(max_jobs: int, max_cases: int) -> int:
    """Run every queued job (oldest first). Returns how many ran."""
    ran = 0
    for path in sorted(QUEUE.glob("*.job.json"), key=lambda p: p.stat().st_mtime):
        if (QUEUE / "STOP").exists():
            print(f"[{now()}] STOP is there: {path.name} waits", flush=True)
            break
        name = path.name[: -len(".job.json")]
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            write_json(QUEUE / f"{name}.refused.json", {"name": name, "reason": f"not readable JSON: {e}", "at": now()})
            path.rename(path.with_name(f"{name}.job.refused"))
            continue
        picked, why = check_job(name, job, max_cases)
        if picked is not None and jobs_today() >= max_jobs:
            picked, why = None, f"already {max_jobs} jobs today (--max-jobs)"
        if picked is None:
            print(f"[{now()}] {name} refused: {why}", flush=True)
            write_json(QUEUE / f"{name}.refused.json", {"name": name, "job": job, "reason": why, "at": now()})
            path.rename(path.with_name(f"{name}.job.refused"))
            continue
        running = path.with_name(f"{name}.job.running")
        path.rename(running)
        done = run_job(name, job, picked)
        write_json(QUEUE / f"{name}.done.json", done)
        running.rename(path.with_name(f"{name}.job.done"))
        print(f"[{now()}] {name} finished: exit {done['returncode']}, {done['result']}, run {done['run_id']}", flush=True)
        ran += 1
    return ran


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="run what is queued, then exit")
    ap.add_argument("--max-jobs", type=int, default=12, help="jobs per calendar day (default 12)")
    ap.add_argument("--max-cases", type=int, default=60, help="cases a job may select (default 60)")
    ap.add_argument("--every", type=float, default=15.0, help="seconds between looks at the queue")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")   # Windows consoles that cannot print ✓
    except AttributeError:
        pass
    QUEUE.mkdir(parents=True, exist_ok=True)
    # a job left running by a closed window is put back in the queue
    for p in QUEUE.glob("*.job.running"):
        p.rename(p.with_name(p.name[: -len(".running")] + ".json"))
    if a.once:
        pass_once(a.max_jobs, a.max_cases)
        return 0
    print(f"[{now()}] watching {QUEUE} (Ctrl+C to stop; create lab/queue/STOP to pause)", flush=True)
    try:
        while True:
            pass_once(a.max_jobs, a.max_cases)
            time.sleep(a.every)
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

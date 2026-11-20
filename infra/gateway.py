"""The pass: the only door into the backend container.

    client (SDK) ──▶ gateway :8000 ──▶ comfy-api-proxy :8189 ──▶ ComfyUI :8188

- Every request needs `Authorization: Bearer $FREEFIELD_TOKEN` (the Comfy SDK sends its
  apiKey that way). The header is stripped before forwarding; the proxy has no auth.
- POST /freefield/prepare {"app", "models"} is the pantry manager: when the requested
  app needs a different set of models than the one that ran last, it asks ComfyUI to
  unload everything (POST /free) so nothing from the previous app stays in VRAM.
- GET /freefield/status shows the current app and ComfyUI's device stats.
- GET /health is open, for Modal's startup probe.
- On a machine that downloads its own models (a pod, your own GPU: FREEFIELD_MODELS is set), the studio's Models
  panel: GET /freefield/downloads (what each pack lacks and why, the download running now), POST /freefield/downloads
  {"packs"} (download them, after the one running), PUT and DELETE /freefield/hf-token {"token"} (keep or forget a
  Hugging Face token, in FREEFIELD_HF_TOKEN_FILE) and GET /freefield/licenses[?repos=a,b] (which licenses this token
  can already read). Never on Modal: its volume is filled by `modal run infra/modal_app.py::download`.
- The proxy writes absolute links (a job's `urls.self`, `.events`, `.cancel`, an output's
  `url`) from the host *it* sees, http://127.0.0.1:8189; the SDK follows those links
  verbatim, so from outside they went nowhere ("fetch failed", 23 oct). JSON answers are
  rewritten to the address the client reached the gateway on.

Run: python gateway.py  (env: FREEFIELD_TOKEN, COMFYUI_URL, PROXY_URL, GATEWAY_PORT)
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
PROXY_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:8189")
TOKEN = os.environ.get("FREEFIELD_TOKEN", "")
ALLOW_OPEN = os.environ.get("FREEFIELD_ALLOW_OPEN") == "1"
MODELS_DIR = os.environ.get("FREEFIELD_MODELS", "").strip()
COMFY_DIR = os.environ.get("FREEFIELD_COMFY_DIR", "/comfyui")
ROOT = Path(__file__).resolve().parent.parent
HOP_HEADERS = {"host", "authorization", "content-length", "transfer-encoding", "connection", "keep-alive"}

log = logging.getLogger("gateway")


class Pantry:
    """Remembers which models are on the GPU and clears it when an app needs others."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.models: str | None = None
        self.app: str | None = None
        self.lock = asyncio.Lock()
        self.frees = 0

    async def prepare(self, app: str, models: str) -> dict:
        async with self.lock:
            freed = False
            previous = self.app
            if self.models is not None and models != self.models:
                async with self.session.post(f"{COMFYUI_URL}/free", json={"unload_models": True, "free_memory": True}) as r:
                    r.raise_for_status()
                freed = True
                self.frees += 1
            self.models, self.app = models, app
            return {"freed": freed, "previous": previous, "current": app}


def authorized(request: web.Request) -> bool:
    if ALLOW_OPEN:
        return True
    header = request.headers.get("Authorization", "")
    return bool(TOKEN) and hmac.compare_digest(header, f"Bearer {TOKEN}")


@web.middleware
async def auth_mw(request: web.Request, handler):
    if request.path == "/health" or authorized(request):
        return await handler(request)
    return web.json_response({"error": "missing or wrong token"}, status=401)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def prepare(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body.get("models"), str) or not isinstance(body.get("app"), str):
        return web.json_response({"error": "expected {app, models}"}, status=400)
    result = await request.app["pantry"].prepare(body["app"], body["models"])
    log.info("prepare %s → %s", body["app"], result)
    return web.json_response(result)


async def models(request: web.Request) -> web.Response:
    """The model files ComfyUI can see, by folder ({"diffusion_models": ["a.safetensors", ...], ...}): the studio marks
    the apps whose files are missing (a pod that downloaded only some packs). Read from ComfyUI's own /models lists."""
    pantry: Pantry = request.app["pantry"]
    out: dict[str, list[str]] = {}
    try:
        async with pantry.session.get(f"{COMFYUI_URL}/models") as r:
            folders = await r.json()
        for folder in folders:
            async with pantry.session.get(f"{COMFYUI_URL}/models/{folder}") as r:
                if r.status == 200:
                    out[folder] = await r.json()
    except Exception as e:  # ComfyUI may still be starting
        return web.json_response({"error": str(e)}, status=503)
    return web.json_response({"folders": out})


def tree_bytes(path: Path) -> int:
    """Bytes under path (a download in .incoming), 0 when it is not there."""
    total, stack = 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
        except OSError:
            pass
    return total


class Downloads:
    """What the studio's Models panel shows and does on a machine that downloads its own models: what each pack still
    lacks and why (tools/local_backend.py download writes <models>/.downloads.json as it goes), the download running
    now, starting more (one at a time: a request while one runs waits for it), and the Hugging Face token."""

    def __init__(self, models: Path):
        import hf   # infra/hf.py, next to this file
        self.hf = hf
        self.models = models
        self.status_file = models / ".downloads.json"
        self.packs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "packs").glob("*.json"))
                      if p.name not in ("index.json", "core.json")}
        self.probe = {}       # a file of each gated repo, to ask Hugging Face whether a token can read the repo
        self.licenses = {}    # gated repo → its license's name
        for p in self.packs.values():
            for m in p["models"]:
                if m.get("gated"):
                    self.probe.setdefault(m["repo"], m["file"])
                    self.licenses.setdefault(m["repo"], m.get("license"))
        self.proc: asyncio.subprocess.Process | None = None
        self.proc_packs: list[str] = []   # what the download this gateway started is fetching
        self.queued: list[str] = []
        self.waiter: asyncio.Task | None = None

    def _status(self) -> dict:
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _alive(job: dict) -> bool:
        """Is the process of this download still the one that wrote it? A pid can come back after a restart."""
        pid = job.get("pid")
        try:
            os.kill(int(pid), 0)
        except (OSError, TypeError, ValueError):
            return False
        started = job.get("pid_start")
        if started:
            try:
                stat = Path(f"/proc/{int(pid)}/stat").read_text()
                return stat[stat.rindex(")") + 2:].split()[19] == started
            except (OSError, ValueError, IndexError):
                pass
        return True

    def busy(self) -> bool:
        if self.proc and self.proc.returncode is None:
            return True
        job = self._status().get("job") or {}
        return job.get("state") == "running" and self._alive(job)   # the pod's own first download

    def has(self, m: dict) -> bool:
        return (self.models / m["dir"] / m["name"]).exists()

    def view(self) -> dict:
        st = self._status()
        job = st.get("job")
        if job and job.get("state") == "running":
            if not self._alive(job):
                job = {**job, "state": "stopped"}
            elif job.get("current"):   # the file on its way counts as far as it got
                part = tree_bytes(self.models / ".incoming") / 1e9
                job = {**job, "done_gb": round(min(job.get("gb", 0), job.get("done_gb", 0) + min(part, job["current"]["gb"])), 2)}
        failed = {k: v for k, v in (st.get("failed") or {}).items() if not (self.models / k).exists()}
        packs = {}
        for name, p in self.packs.items():
            missing = [m for m in p["models"] if not self.has(m)]
            packs[name] = {"gb": p["download_gb"], "files": len(p["models"]), "missing": len(missing),
                           "missing_gb": round(sum(m["gb"] for m in missing), 2),
                           "gated": sorted({m["repo"] for m in missing if m.get("gated")})}
        tok, source = self.hf.token()
        return {"enabled": True, "packs": packs, "failed": failed, "job": job, "queued": self.queued,
                "free_gb": round(shutil.disk_usage(self.models).free / 1e9, 1), "licenses": self.licenses,
                "token": {"source": source or None, "problem": None if source == "studio" else self.hf.env_problem(),
                          "can_save": bool(self.hf.token_file())}}

    async def start(self, names: list[str]) -> tuple[int, dict]:
        unknown = [n for n in names if n not in self.packs]
        if not names or unknown:
            return 400, {"error": f"unknown pack {', '.join(unknown) or '(none)'}; packs: {', '.join(self.packs)}"}
        todo = {(m["repo"], m["file"]): m for n in names for m in self.packs[n]["models"] if not self.has(m)}
        if not todo:
            return 200, {"nothing": True}   # every file is here already
        need = sum(m["gb"] for m in todo.values())
        free = shutil.disk_usage(self.models).free / 1e9
        if need > free - 2:
            return 400, {"error": f"not enough disk: {need:.1f} GB to download, {free:.1f} GB free here, and 2 GB must stay "
                                  "free (a bigger volume, or another pack)"}
        if self.busy():
            # a second press of the same button: what it asks for is already on its way, nothing to queue
            job = self._status().get("job") or {}
            coming = set(job.get("files") or []) if job.get("state") == "running" else set()
            mine = self.proc and self.proc.returncode is None and set(names) <= set(self.proc_packs)
            if mine or {f"{m['dir']}/{m['name']}" for m in todo.values()} <= coming:
                return 202, {"running": job.get("packs") or self.proc_packs}
            self.queued = list(dict.fromkeys(self.queued + names))
            if not self.waiter or self.waiter.done():
                self.waiter = asyncio.get_running_loop().create_task(self._after_current())
            return 202, {"queued": self.queued}
        await self._spawn(names)
        return 202, {"started": names}

    async def _spawn(self, names: list[str]) -> None:
        # its lines go to the same log as everything else (RunPod's and Vast's Logs, docker logs)
        self.proc_packs = list(names)
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "tools" / "local_backend.py"), "download", COMFY_DIR, "--models", str(self.models),
            *names, cwd=str(ROOT))
        asyncio.get_running_loop().create_task(self._reap(self.proc))

    async def _reap(self, proc: asyncio.subprocess.Process) -> None:
        await proc.wait()
        if self.queued and (not self.waiter or self.waiter.done()):
            self.waiter = asyncio.get_running_loop().create_task(self._after_current())

    async def _after_current(self) -> None:
        while self.busy():
            await asyncio.sleep(2)
        names, self.queued = self.queued, []
        if names:
            await self._spawn(names)

    async def save_token(self, value: str) -> tuple[int, dict]:
        value = value.strip()
        if not self.hf.token_file():
            return 400, {"error": "this backend keeps no token (FREEFIELD_HF_TOKEN_FILE is not set)"}
        if not self.hf.looks_like_token(value):
            return 400, {"error": "that does not look like a Hugging Face token: it starts with hf_ and is about 37 "
                                  "characters long", "code": "shape"}
        verdict, user = await asyncio.to_thread(self.hf.whoami, value)
        if verdict == "bad":
            return 400, {"error": f"Hugging Face did not accept this token: copy it again from {self.hf.TOKENS_PAGE}",
                         "code": "bad"}
        if verdict != "ok":
            return 502, {"error": "could not reach Hugging Face to check the token: try again in a moment", "code": "unknown"}
        self.hf.save(value)
        log.info("Hugging Face token saved (account %s)", user)
        return 200, {"user": user, "source": "studio"}

    async def check(self, repos: list[str]) -> dict:
        repos = [r for r in dict.fromkeys(repos) if r in self.probe]
        tok, source = self.hf.token()
        if not tok:
            return {"token": "none", "source": None, "user": None, "repos": {r: "token" for r in repos}}
        verdict, user = await asyncio.to_thread(self.hf.whoami, tok)
        if verdict == "bad":
            return {"token": "bad", "source": source, "user": None, "repos": {r: "token" for r in repos}}
        found = await asyncio.gather(*(asyncio.to_thread(self.hf.access, r, self.probe[r], tok) for r in repos))
        return {"token": "ok" if verdict == "ok" else "unknown", "source": source, "user": user or None,
                "repos": dict(zip(repos, found))}


async def downloads_view(request: web.Request) -> web.Response:
    return web.json_response(request.app["downloads"].view())


async def downloads_start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        body = None
    names = body.get("packs") if isinstance(body, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return web.json_response({"error": 'expected {"packs": ["name", ...]}'}, status=400)
    code, out = await request.app["downloads"].start(names)
    return web.json_response(out, status=code)


async def token_save(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        body = None
    value = body.get("token") if isinstance(body, dict) else None
    if not isinstance(value, str):
        return web.json_response({"error": 'expected {"token": "hf_..."}'}, status=400)
    code, out = await request.app["downloads"].save_token(value)
    return web.json_response(out, status=code)


async def token_forget(request: web.Request) -> web.Response:
    d: Downloads = request.app["downloads"]
    forgot = d.hf.forget()
    return web.json_response({"forgot": forgot, "source": d.hf.token()[1] or None})


async def licenses(request: web.Request) -> web.Response:
    d: Downloads = request.app["downloads"]
    asked = [r for r in request.query.get("repos", "").split(",") if r]
    if not asked:   # the repos whose files are waiting
        asked = sorted({v["repo"] for v in d.view()["failed"].values() if v.get("gated")})
    return web.json_response(await d.check(asked))


async def status(request: web.Request) -> web.Response:
    pantry: Pantry = request.app["pantry"]
    stats = None
    try:
        async with pantry.session.get(f"{COMFYUI_URL}/system_stats") as r:
            stats = await r.json()
    except Exception as e:  # ComfyUI may still be starting
        stats = {"error": str(e)}
    return web.json_response({"app": pantry.app, "models": pantry.models, "frees": pantry.frees, "comfyui": stats})


LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")


def is_private(name: str) -> bool:
    """A private (RFC 1918) or loopback IP address. 172.16.0.0/12 is 172.16 to 172.31 only: the old prefix
    test "172.2" also took public addresses such as 172.217.x (Google) for private ones."""
    try:
        ip = ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def external_base(request: web.Request) -> str:
    """Where the client reached us. Modal terminates TLS and talks plain http to the container
    without an X-Forwarded-Proto header (first deploy, 23 oct: links came out as http://…modal.run,
    the SDK saw another origin and sent no token, 401), so a public host is https unless a proxy
    says otherwise; only a local or private address keeps the scheme it was reached on."""
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    host = request.host
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    private = name in LOCAL_HOSTS or is_private(name)
    scheme = forwarded or (request.scheme if private else "https")
    return f"{scheme}://{host}"


def relink(body: bytes, request: web.Request) -> bytes:
    """The proxy's own address in a JSON answer becomes the gateway's external one."""
    return body.replace(PROXY_URL.encode(), external_base(request).encode())


async def forward(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["session"]
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}

    async def body():
        async for chunk in request.content.iter_chunked(1 << 16):
            yield chunk

    data = body() if request.can_read_body else None
    async with session.request(request.method, f"{PROXY_URL}{request.rel_url}", headers=headers, data=data,
                               allow_redirects=False) as upstream:
        passthrough = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS | {"content-encoding"}}
        if upstream.content_type == "application/json":   # job and asset answers carry links: fix them up whole
            raw = relink(await upstream.read(), request)
            passthrough.pop("Content-Length", None)
            return web.Response(status=upstream.status, body=raw, headers=passthrough)
        resp = web.StreamResponse(status=upstream.status)
        for k, v in passthrough.items():
            resp.headers[k] = v
        await resp.prepare(request)
        async for chunk in upstream.content.iter_any():   # streams SSE events and big files as they come
            await resp.write(chunk)
        await resp.write_eof()
        return resp


async def on_startup(app: web.Application) -> None:
    app["session"] = ClientSession(timeout=ClientTimeout(total=None, sock_connect=30), auto_decompress=False)
    app["pantry"] = Pantry(app["session"])


async def on_cleanup(app: web.Application) -> None:
    await app["session"].close()


def make_app() -> web.Application:
    if not TOKEN and not ALLOW_OPEN:
        raise SystemExit("FREEFIELD_TOKEN is not set; refusing to start an open gateway")
    app = web.Application(middlewares=[auth_mw], client_max_size=1024 ** 3)
    app.router.add_get("/health", health)
    app.router.add_post("/freefield/prepare", prepare)
    app.router.add_get("/freefield/status", status)
    app.router.add_get("/freefield/models", models)
    if MODELS_DIR:
        app["downloads"] = Downloads(Path(MODELS_DIR))
        app.router.add_get("/freefield/downloads", downloads_view)
        app.router.add_post("/freefield/downloads", downloads_start)
        app.router.add_put("/freefield/hf-token", token_save)
        app.router.add_delete("/freefield/hf-token", token_forget)
        app.router.add_get("/freefield/licenses", licenses)
    app.router.add_route("*", "/{tail:.*}", forward)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


async def wait_for(url: str, timeout_s: float = 600) -> None:
    """Block until url answers 200, so Modal only routes traffic once ComfyUI is up."""
    deadline = time.time() + timeout_s
    async with ClientSession() as s:
        while time.time() < deadline:
            try:
                async with s.get(url) as r:
                    if r.status == 200:
                        return
            except Exception:
                pass
            await asyncio.sleep(1)
    raise TimeoutError(f"{url} did not come up in {timeout_s:.0f}s")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    web.run_app(make_app(), host="0.0.0.0", port=int(os.environ.get("GATEWAY_PORT", "8000")))

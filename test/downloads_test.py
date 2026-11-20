"""The gateway's Models panel routes against a fake Hugging Face: the token is checked before it is kept, licenses are
told apart from bad tokens, failures of files that are back no longer count, a download waits for the one running.

    pip install aiohttp && python test/downloads_test.py
"""
import asyncio, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="ff-dl-"))
models = tmp / "models"
models.mkdir()
os.environ.update({"FREEFIELD_TOKEN": "t0k", "FREEFIELD_MODELS": str(models), "FREEFIELD_HF_TOKEN_FILE": str(tmp / "hf_token"),
                   "HF_ENDPOINT": "http://127.0.0.1:18301", "PROXY_URL": "http://127.0.0.1:18389"})
os.environ.pop("HF_TOKEN", None)
os.environ["HF_HOME"] = str(tmp / "hf-home")   # no `hf auth login` token of whoever runs this
sys.path.insert(0, str(ROOT / "infra"))
from aiohttp import web, ClientSession
import gateway  # infra/gateway.py

GOOD, NEW = "hf_" + "g" * 34, "hf_" + "n" * 34   # NEW: an account that accepted no license yet
FLUX = "black-forest-labs/flux-3-image-klein-comfy"


async def fake_hf():
    async def whoami(request):
        auth = request.headers.get("Authorization", "")
        if auth in (f"Bearer {GOOD}", f"Bearer {NEW}"):
            return web.json_response({"name": "sammir" if GOOD in auth else "newcomer"})
        return web.json_response({"error": "Invalid credentials"}, status=401)

    async def resolve(request):
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {GOOD}":
            return web.Response(status=302, headers={"Location": "https://cdn.example/x"})
        return web.Response(status=403 if auth == f"Bearer {NEW}" else 401)
    app = web.Application()
    app.router.add_get("/api/whoami-v2", whoami)
    app.router.add_route("HEAD", "/{org}/{repo}/resolve/main/{file:.*}", resolve)
    return app


async def main():
    hf_runner = web.AppRunner(await fake_hf()); await hf_runner.setup(); await web.TCPSite(hf_runner, "127.0.0.1", 18301).start()
    gw = web.AppRunner(gateway.make_app()); await gw.setup(); await web.TCPSite(gw, "127.0.0.1", 18300).start()
    base, h = "http://127.0.0.1:18300", {"Authorization": "Bearer t0k"}
    async with ClientSession() as s:
        async with s.get(f"{base}/freefield/downloads") as r:
            assert r.status == 401, "the Models routes need the gateway token like everything else"
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert r.status == 200 and v["enabled"] and v["job"] is None and v["failed"] == {}, v
        assert v["token"] == {"source": None, "problem": None, "can_save": True}, v["token"]
        assert v["packs"]["image-flux3"]["gated"] == [FLUX] and v["packs"]["image-flux3"]["missing"] == 5, v["packs"]["image-flux3"]
        assert "core" not in v["packs"] and v["licenses"][FLUX] == "FLUX Kommunity License"
        print("✓ view: packs, what they lack, no token yet")

        # what the downloader writes when there is no token; a file that came back later no longer counts
        k_vae, k_mp = "vae/flux2-vae.safetensors", "detection/mediapipe_face_fp32.safetensors"
        (models / ".downloads.json").write_text(json.dumps({"failed": {
            k_vae: {"repo": FLUX, "file": k_vae, "gated": True, "reason": "token_missing", "at": "2026-11-19T00:00:00Z"},
            k_mp: {"repo": "Comfy-Org/mediapipe", "file": k_mp, "gated": False, "reason": "failed", "at": "2026-11-19T00:00:00Z"}},
            "job": {"state": "done", "pid": 1, "packs": ["image-flux3"], "files": [k_vae, k_mp], "gb": 0.35, "done_gb": 0.35}}))
        (models / "detection").mkdir()
        (models / k_mp).write_bytes(b"x")
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert list(v["failed"]) == [k_vae], v["failed"]
        print("✓ failures of files that are there again are dropped")

        async with s.get(f"{base}/freefield/licenses", headers=h) as r:
            lic = await r.json()
        assert lic == {"token": "none", "source": None, "user": None, "repos": {FLUX: "token"}}, lic

        for bad, code in (("not-a-token", 400), ("hf_" + "b" * 34, 400)):
            async with s.put(f"{base}/freefield/hf-token", headers=h, json={"token": bad}) as r:
                out = await r.json()
            assert r.status == code and out["code"] in ("shape", "bad"), (bad, r.status, out)
        assert not (tmp / "hf_token").exists(), "a token Hugging Face refuses is not kept"
        print("✓ a malformed or refused token is not kept")

        async with s.put(f"{base}/freefield/hf-token", headers=h, json={"token": f"  {NEW}\n"}) as r:
            out = await r.json()
        assert r.status == 200 and out == {"user": "newcomer", "source": "studio"}, out
        assert (tmp / "hf_token").read_text().strip() == NEW and (tmp / "hf_token").stat().st_mode & 0o777 == 0o600
        async with s.get(f"{base}/freefield/licenses", headers=h) as r:
            lic = await r.json()
        assert lic["token"] == "ok" and lic["user"] == "newcomer" and lic["repos"] == {FLUX: "license"}, lic
        print("✓ a new account's token is kept (mode 600) and its license is told apart")

        async with s.put(f"{base}/freefield/hf-token", headers=h, json={"token": GOOD}) as r:
            assert (await r.json())["user"] == "sammir"
        async with s.get(f"{base}/freefield/licenses?repos={FLUX},not/gated", headers=h) as r:
            lic = await r.json()
        assert lic["repos"] == {FLUX: "ok"} and lic["source"] == "studio", lic
        os.environ["HF_TOKEN"] = "{{ RUNPOD_SECRET_hf_token }}"
        async with s.delete(f"{base}/freefield/hf-token", headers=h) as r:
            out = await r.json()
        assert out == {"forgot": True, "source": None}, out
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert v["token"]["source"] is None and "placeholder" in v["token"]["problem"], v["token"]
        os.environ.pop("HF_TOKEN")
        print("✓ forget goes back to HF_TOKEN, and a RunPod placeholder is not a token")

        async with s.post(f"{base}/freefield/downloads", headers=h, json={"packs": ["nope"]}) as r:
            assert r.status == 400 and "unknown pack" in (await r.json())["error"]
        async with s.post(f"{base}/freefield/downloads", headers=h, json={"packs": ["video-h3", "video-ltx25", "video-wan",
                                                                                   "video-wan-camera", "audio"]}) as r:
            out = await r.json()
        free = __import__("shutil").disk_usage(models).free / 1e9
        assert (r.status == 400 and "not enough disk" in out["error"]) or free > 240, (r.status, out)
        # a download running (this process stands in for it): a new one waits its turn
        job = {"state": "running", "pid": os.getpid(), "packs": ["upscale"], "files": [], "gb": 5.0, "done_gb": 1.0,
               "current": None, "started": "2026-11-19T00:00:00Z"}
        (models / ".downloads.json").write_text(json.dumps({"failed": {}, "job": job}))
        async with s.post(f"{base}/freefield/downloads", headers=h, json={"packs": ["image"]}) as r:
            out = await r.json()
        assert r.status == 202 and out == {"queued": ["image"]}, out
        # the same files again while they are on their way: nothing more to queue
        image_files = [f"{m['dir']}/{m['name']}" for m in json.loads((ROOT / "packs" / "image.json").read_text())["models"]]
        (models / ".downloads.json").write_text(json.dumps({"failed": {}, "job": {**job, "packs": ["image"], "files": image_files}}))
        async with s.post(f"{base}/freefield/downloads", headers=h, json={"packs": ["image"]}) as r:
            out = await r.json()
        assert r.status == 202 and out == {"running": ["image"]}, out
        # a pack whose files are all here downloads nothing
        upscale = json.loads((ROOT / "packs" / "upscale.json").read_text())["models"]
        for m in upscale:
            (models / m["dir"]).mkdir(parents=True, exist_ok=True); (models / m["dir"] / m["name"]).write_bytes(b"x")
        async with s.post(f"{base}/freefield/downloads", headers=h, json={"packs": ["upscale"]}) as r:
            out = await r.json()
        assert r.status == 200 and out == {"nothing": True}, out
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert v["job"]["state"] == "running" and v["queued"] == ["image"], v["job"]
        gw.app["downloads"].waiter.cancel()   # this test starts no real download
        (models / ".downloads.json").write_text(json.dumps({"failed": {}, "job": {**job, "pid": 2 ** 22 + 7}}))
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert v["job"]["state"] == "stopped", "a download whose process is gone says it stopped"
        (models / ".downloads.json").write_text(json.dumps({"failed": {}, "job": {**job, "pid_start": "1"}}))
        async with s.get(f"{base}/freefield/downloads", headers=h) as r:
            v = await r.json()
        assert v["job"]["state"] == "stopped" or not Path("/proc").exists(), "a pid that came back after a restart is not that download"
        print("✓ unknown packs and a full disk are refused; a second download waits for the first")
    await gw.cleanup(); await hf_runner.cleanup()
    print("downloads ok")

asyncio.run(main())

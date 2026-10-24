"""The gateway against a fake proxy: JSON links come back on the gateway's own address, streams pass through.

    pip install aiohttp && python test/gateway_test.py
"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra"))
os.environ["FREEFIELD_TOKEN"] = "t0k"
os.environ["PROXY_URL"] = "http://127.0.0.1:18189"
from aiohttp import web, ClientSession
import gateway  # infra/gateway.py

async def fake_proxy_app():
    async def job(request):
        base = f"{request.scheme}://{request.host}"
        return web.json_response({"id": "j1", "status": "succeeded",
                                  "urls": {"self": f"{base}/api/v2/jobs/j1", "events": f"{base}/api/v2/jobs/j1/events"},
                                  "outputs": [{"id": "o1", "url": f"{base}/api/v2/jobs/j1/outputs/o1"}]})
    async def events(request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        await resp.write(b"data: {\"url\": \"http://127.0.0.1:18189/x\"}\n\n")
        await resp.write_eof(); return resp
    app = web.Application(); app.router.add_get("/api/v2/jobs/j1", job); app.router.add_get("/api/v2/jobs/j1/events", events)
    return app

async def main():
    proxy = web.AppRunner(await fake_proxy_app()); await proxy.setup(); await web.TCPSite(proxy, "127.0.0.1", 18189).start()
    gw = web.AppRunner(gateway.make_app()); await gw.setup(); await web.TCPSite(gw, "127.0.0.1", 18000).start()
    async with ClientSession() as s:
        h = {"Authorization": "Bearer t0k"}
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1", headers=h) as r:
            body = await r.json(); assert r.status == 200, r.status
        assert body["urls"]["self"] == "http://127.0.0.1:18000/api/v2/jobs/j1", body["urls"]
        assert body["outputs"][0]["url"] == "http://127.0.0.1:18000/api/v2/jobs/j1/outputs/o1"
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1", headers={**h, "X-Forwarded-Proto": "https", "Host": "gw.example.test"}) as r:
            body = await r.json()
        assert body["urls"]["self"] == "https://gw.example.test/api/v2/jobs/j1", body["urls"]
        # a public host with no forwarded header (Modal) is https; a local one keeps http
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1", headers={**h, "Host": "x--serve.us-east.modal.run"}) as r:
            body = await r.json()
        assert body["urls"]["self"] == "https://x--serve.us-east.modal.run/api/v2/jobs/j1", body["urls"]
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1", headers={**h, "Host": "192.168.1.20:8000"}) as r:
            body = await r.json()
        assert body["urls"]["self"] == "http://192.168.1.20:8000/api/v2/jobs/j1", body["urls"]
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1/events", headers=h) as r:
            text = await r.text(); assert r.headers["Content-Type"].startswith("text/event-stream")
        assert "http://127.0.0.1:18189/x" in text, "streams are passed through untouched"
        async with s.get("http://127.0.0.1:18000/api/v2/jobs/j1") as r:
            assert r.status == 401, r.status
    print("gateway relink ok")
    await gw.cleanup(); await proxy.cleanup()

asyncio.run(main())

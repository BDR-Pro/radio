import json, socket, threading, time, urllib.request

import pytest
import uvicorn
import websockets
import asyncio

from sdr_kid.server import create_app, BUS


@pytest.fixture
def live_server():
    app = create_app()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    for _ in range(50):
        time.sleep(0.05)
        if srv.started: break
    yield f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}"
    srv.should_exit = True


def test_landing_page(live_server):
    http, _ = live_server
    body = urllib.request.urlopen(f"{http}/").read().decode()
    assert "SDR" in body and "Live spectrum" in body


def test_live_page(live_server):
    http, _ = live_server
    body = urllib.request.urlopen(f"{http}/live").read().decode()
    assert "waterfall" in body and "WebSocket" in body


def test_ws_spectrum_broadcasts(live_server):
    _, ws_url = live_server

    async def go():
        async with websockets.connect(f"{ws_url}/ws/spectrum") as ws:
            await asyncio.sleep(0.05)
            BUS.publish([100_000_000, 101_000_000], [-30.0, -10.0])
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(raw)
    frame = asyncio.run(go())
    assert frame["powers"] == [-30.0, -10.0]
    assert frame["freqs"] == [100_000_000, 101_000_000]

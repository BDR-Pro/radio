from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


MAP_META: Dict[str, Dict[str, str]] = {
    "planes.html": {
        "title": "Airplanes overhead",
        "emoji": "✈️",
        "blurb": "Live ADS-B positions from OpenSky. Click a dot to see the callsign, altitude and speed.",
        "accent": "#00c8ff",
    },
    "ships.html": {
        "title": "Ships nearby",
        "emoji": "🚢",
        "blurb": "AIS transmissions decoded from your dongle via rtl_ais. Only shows vessels within radio range.",
        "accent": "#7fffd4",
    },
    "iss.html": {
        "title": "International Space Station",
        "emoji": "🛰️",
        "blurb": "Where the ISS is right now, and how far it is from you. Point your antenna up when it's overhead!",
        "accent": "#ffcc00",
    },
    "noaa.html": {
        "title": "NOAA weather image",
        "emoji": "🌩️",
        "blurb": "The most recent APT picture your dongle decoded from a NOAA satellite pass.",
        "accent": "#a1ff8e",
    },
    "live.html": {
        "title": "Live spectrum",
        "emoji": "📈",
        "blurb": "Realtime spectrum + waterfall streamed from your dongle over WebSocket.",
        "accent": "#ff85d1",
    },
}


# --- shared spectrum broadcast state -------------------------------------------


class SpectrumBus:
    """Thread-safe fan-out of the latest spectrum frames to WebSocket clients."""

    def __init__(self, history: int = 200):
        self._lock = threading.Lock()
        self._history: Deque[dict] = deque(maxlen=history)
        self._subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, freqs_hz: List[int], powers_db: List[float]) -> None:
        frame = {"ts": time.time(),
                 "freqs": [int(f) for f in freqs_hz],
                 "powers": [float(p) for p in powers_db]}
        with self._lock:
            self._history.append(frame)
            subs = list(self._subscribers)
            loop = self._loop
        if loop is None:
            return
        for q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, frame)
            except Exception:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        with self._lock:
            self._subscribers.append(q)
            for frame in list(self._history)[-20:]:
                try: q.put_nowait(frame)
                except Exception: break
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


BUS = SpectrumBus()


LIVE_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDR Kid · live spectrum</title>
<style>
  body{margin:0;background:#0b1020;color:#e7ecff;font-family:system-ui,sans-serif}
  header{padding:14px 20px;background:#182349;display:flex;gap:16px;align-items:center;
         justify-content:space-between}
  header a{color:#6ee7ff;text-decoration:none}
  h1{margin:0;font-size:18px}
  .meta{color:#98a3c9;font-size:13px}
  #wrap{padding:16px 20px;display:grid;gap:16px}
  canvas{width:100%;background:#050818;border-radius:12px;display:block}
  .peak{color:#ffd166;font-weight:600}
  .status{font-family:monospace}
  footer{color:#98a3c9;font-size:12px;padding:12px 20px;text-align:center}
</style></head>
<body>
<header>
  <div><a href="/">&larr; SDR Kid</a> · <h1 style="display:inline">Live spectrum</h1></div>
  <div class="meta">frames <span id="n">0</span> · peak <span class="peak" id="peak">—</span></div>
</header>
<div id="wrap">
  <canvas id="waterfall" width="1024" height="360"></canvas>
  <canvas id="bars"      width="1024" height="120"></canvas>
</div>
<footer>WebSocket stream from <code>/ws/spectrum</code>. Start the RF explorer in the terminal to feed this page.</footer>
<script>
const wf   = document.getElementById('waterfall').getContext('2d');
const bars = document.getElementById('bars').getContext('2d');
const N    = document.getElementById('n');
const PEAK = document.getElementById('peak');
let frames = 0;
function colorFor(n){
  const stops=[[0,[10,20,60]],[0.25,[30,80,200]],[0.5,[0,200,200]],[0.75,[255,220,60]],[1,[255,60,60]]];
  for(let i=1;i<stops.length;i++){
    if(n<=stops[i][0]){const t=(n-stops[i-1][0])/(stops[i][0]-stops[i-1][0]);
      const a=stops[i-1][1],b=stops[i][1];
      return `rgb(${a[0]+(b[0]-a[0])*t|0},${a[1]+(b[1]-a[1])*t|0},${a[2]+(b[2]-a[2])*t|0})`;}
  } return 'white';
}
function drawFrame(frame){
  const {freqs, powers} = frame;
  if(!powers.length) return;
  const w = 1024, h = 360;
  // scroll waterfall down by 1 px
  const img = wf.getImageData(0,0,w,h-1);
  wf.putImageData(img,0,1);
  const lo = Math.min(...powers), hi = Math.max(...powers), span = Math.max(hi-lo,1);
  for(let x=0;x<w;x++){
    const i = Math.floor(x*powers.length/w);
    const n = (powers[i]-lo)/span;
    wf.fillStyle = colorFor(n);
    wf.fillRect(x,0,1,1);
  }
  // bars
  bars.clearRect(0,0,w,120);
  for(let x=0;x<w;x++){
    const i=Math.floor(x*powers.length/w);
    const n=(powers[i]-lo)/span;
    bars.fillStyle=colorFor(n);
    bars.fillRect(x,120-n*118,1,n*118);
  }
  const peakIdx=powers.reduce((a,_,i,arr)=>arr[i]>arr[a]?i:a,0);
  PEAK.textContent = `${(freqs[peakIdx]/1e6).toFixed(3)} MHz  ${powers[peakIdx].toFixed(1)} dB`;
  N.textContent = ++frames;
}
const ws = new WebSocket(`ws://${location.host}/ws/spectrum`);
ws.onmessage = ev => drawFrame(JSON.parse(ev.data));
ws.onopen  = ()=> PEAK.textContent = 'connected';
ws.onclose = ()=> PEAK.textContent = 'disconnected';
</script>
</body></html>"""


INDEX_CSS = """
:root{
  --bg:#0b1020; --panel:#111a34; --panel2:#182349; --ink:#e7ecff;
  --muted:#98a3c9; --accent:#6ee7ff; --accent2:#ff85d1;
}
*{box-sizing:border-box}
body{
  margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
  color:var(--ink); background:radial-gradient(1200px 600px at 20% -10%, #1e2f66 0%, transparent 60%),
                   radial-gradient(900px 500px at 100% 100%, #35155a 0%, transparent 55%), var(--bg);
  min-height:100vh;
}
header{
  padding:48px 24px 24px; text-align:center;
}
h1{
  font-size:clamp(28px, 4vw, 44px); margin:0 0 8px;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  -webkit-background-clip:text; background-clip:text; color:transparent; letter-spacing:-.02em;
}
.subtitle{color:var(--muted); margin:0 0 8px}
.pill{
  display:inline-block; padding:4px 10px; border-radius:999px;
  background:rgba(110,231,255,.12); color:var(--accent);
  font-size:12px; letter-spacing:.06em; text-transform:uppercase;
}
main{
  max-width:1100px; margin:0 auto; padding:24px;
  display:grid; gap:18px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}
.card{
  background:linear-gradient(180deg, var(--panel), var(--panel2));
  border:1px solid rgba(255,255,255,.06);
  border-radius:16px; padding:20px; text-decoration:none; color:inherit;
  transition:transform .15s ease, border-color .15s ease, box-shadow .15s ease;
  display:flex; flex-direction:column; gap:10px; position:relative; overflow:hidden;
}
.card:hover{ transform:translateY(-3px); border-color:rgba(110,231,255,.4);
             box-shadow:0 12px 40px rgba(0,0,0,.4);}
.card .emoji{font-size:34px; line-height:1}
.card h2{margin:0; font-size:20px}
.card p{margin:0; color:var(--muted); font-size:14px}
.card .stripe{ position:absolute; inset:0 0 auto 0; height:4px;
               background:linear-gradient(90deg,var(--card-accent, var(--accent)), transparent);}
.empty{
  border:1px dashed rgba(255,255,255,.12); padding:32px; border-radius:16px; text-align:center;
  color:var(--muted); grid-column:1/-1;
}
footer{
  text-align:center; color:var(--muted); font-size:13px; padding:32px 16px 48px;
}
kbd{background:#1b2653; border:1px solid rgba(255,255,255,.1); padding:1px 6px;
    border-radius:6px; font-size:12px}
a{color:var(--accent)}
@media (prefers-color-scheme: light){
  :root{--bg:#f5f7ff; --panel:#ffffff; --panel2:#eef2ff; --ink:#111834;
        --muted:#5c6a8f; --accent:#2563eb; --accent2:#c026d3}
}
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>SDR Kid · dashboard</title>
<style>%(css)s</style>
</head>
<body>
<header>
  <span class="pill">%(status)s</span>
  <h1>SDR&nbsp;Kid</h1>
  <p class="subtitle">%(subtitle)s</p>
</header>
<main>%(cards)s</main>
<footer>
  <p>press <kbd>Ctrl</kbd>+<kbd>C</kbd> in the terminal to stop a mode ·
     page auto-refreshes every 15&nbsp;s</p>
</footer>
</body>
</html>"""


def _render_index() -> str:
    pages = sorted(p.name for p in STATIC_DIR.glob("*.html"))
    if not pages:
        cards = (
            '<div class="empty">'
            "<h2>No maps yet</h2>"
            "<p>Head to the terminal and pick <b>Track airplanes</b>, "
            "<b>Track ships</b>, or <b>ISS</b> to generate a map.</p>"
            "</div>"
        )
        status = "waiting for a mode…"
        subtitle = "your terminal has the controls · this page shows what you see"
    else:
        parts = []
        for name in pages:
            meta = MAP_META.get(name, {
                "title": name, "emoji": "📡",
                "blurb": "Generated by an SDR Kid mode.",
                "accent": "#6ee7ff",
            })
            parts.append(
                f'<a class="card" href="/view/{name}" '
                f'style="--card-accent:{meta["accent"]}">'
                f'<span class="stripe"></span>'
                f'<div class="emoji">{meta["emoji"]}</div>'
                f'<h2>{meta["title"]}</h2>'
                f'<p>{meta["blurb"]}</p>'
                f'</a>'
            )
        cards = "\n".join(parts)
        status = f"{len(pages)} live map{'s' if len(pages) != 1 else ''}"
        subtitle = "live maps generated by your radio · click any card"
    return INDEX_HTML % {"css": INDEX_CSS, "status": status,
                         "subtitle": subtitle, "cards": cards}


def create_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        BUS.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="SDR Kid map server", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        # ensure live.html shows up on the dashboard as a virtual card
        (STATIC_DIR / "live.html").write_text(LIVE_PAGE)
        return HTMLResponse(_render_index())

    @app.get("/live", response_class=HTMLResponse)
    def live() -> HTMLResponse:
        return HTMLResponse(LIVE_PAGE)

    @app.websocket("/ws/spectrum")
    async def ws_spectrum(ws: WebSocket) -> None:
        await ws.accept()
        q = BUS.subscribe()
        try:
            while True:
                frame = await q.get()
                await ws.send_text(json.dumps(frame))
        except WebSocketDisconnect:
            pass
        finally:
            BUS.unsubscribe(q)

    @app.get("/view/{name}", response_class=HTMLResponse)
    def view(name: str) -> HTMLResponse:
        path = STATIC_DIR / name
        if not path.exists() or path.suffix != ".html":
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        # wrap folium page in a back-link header
        inner = path.read_text()
        back = (
            '<div style="position:fixed;top:12px;left:12px;z-index:9999;'
            'background:#0b1020cc;backdrop-filter:blur(6px);color:#e7ecff;'
            'padding:6px 12px;border-radius:8px;font:14px sans-serif;">'
            f'<a style="color:#6ee7ff;text-decoration:none" href="/">&larr; SDR Kid</a>'
            f' &nbsp;·&nbsp; <b>{MAP_META.get(name,{}).get("title", name)}</b>'
            '</div>'
        )
        if "<body" in inner:
            inner = inner.replace("<body", back + "<body", 1) if False else inner
            inner = inner.replace("</body>", back + "</body>", 1)
        else:
            inner = back + inner
        return HTMLResponse(inner)

    @app.get("/image/{name}")
    def image(name: str) -> FileResponse:
        return FileResponse(str(STATIC_DIR / name))

    return app


class MapServer:
    """Background FastAPI/uvicorn server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.app = create_app()
        self._server: Optional[object] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._thread is not None:
            return
        import uvicorn

        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="warning"
        )
        self._server = uvicorn.Server(config)

        def run() -> None:
            self._server.run()  # type: ignore[union-attr]

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True  # type: ignore[attr-defined]


_singleton: Optional[MapServer] = None


def get_server() -> MapServer:
    global _singleton
    if _singleton is None:
        _singleton = MapServer()
        _singleton.start()
    return _singleton


def write_static(name: str, content: str) -> Path:
    path = STATIC_DIR / name
    path.write_text(content)
    return path

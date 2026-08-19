from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


def create_app() -> FastAPI:
    app = FastAPI(title="SDR Kid map server", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        pages = sorted(p.name for p in STATIC_DIR.glob("*.html"))
        if not pages:
            return HTMLResponse(
                "<h1>SDR Kid</h1><p>No maps yet — pick a mode in the CLI!</p>"
            )
        links = "".join(
            f'<li><a href="/view/{p}">{p}</a></li>' for p in pages
        )
        return HTMLResponse(
            f"<h1>SDR Kid maps</h1><ul>{links}</ul>"
        )

    @app.get("/view/{name}", response_class=HTMLResponse)
    def view(name: str) -> HTMLResponse:
        path = STATIC_DIR / name
        if not path.exists() or path.suffix != ".html":
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        return HTMLResponse(path.read_text())

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
        self._server: Optional["object"] = None
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

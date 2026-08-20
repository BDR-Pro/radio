"""Local ADS-B plane tracker — connects to dump1090's SBS port and shows
planes YOUR antenna is hearing at 1090 MHz.

dump1090 exposes:
  * 30003 — SBS BaseStation (comma-separated, human-friendly)   ← we read this
  * 30005 — Beast binary
  * 30002 — raw AVR
  * 8080  — its own web map

Run dump1090 with `--net` in a second terminal (once its `.exe` is on PATH).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid import logbook, progress as achievements
from sdr_kid.deps import DUMP1090, current_os, which as _which
from sdr_kid.server import get_server, write_static


DUMP1090_HOST = "127.0.0.1"
DUMP1090_SBS_PORT = 30003


@dataclass
class Plane:
    icao: str
    callsign: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_ft: Optional[float] = None
    speed_kt: Optional[float] = None
    track: Optional[float] = None
    squawk: str = ""
    msg_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class SbsClient:
    """Non-blocking TCP client for dump1090's SBS/BaseStation port."""

    def __init__(self, host: str = DUMP1090_HOST, port: int = DUMP1090_SBS_PORT):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.buf = b""
        self.planes: Dict[str, Plane] = {}
        self.msg_count = 0
        self.connected = False

    def connect(self) -> Optional[str]:
        try:
            s = socket.create_connection((self.host, self.port), timeout=3)
            s.setblocking(False)
            self.sock = s
            self.connected = True
            return None
        except Exception as exc:
            return f"can't connect to dump1090 at {self.host}:{self.port} — {exc}"

    def poll(self) -> None:
        if self.sock is None:
            return
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return
        except Exception:
            self.connected = False
            return
        if not data:
            self.connected = False
            return
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            self._absorb(line.decode(errors="ignore"))

    def _absorb(self, raw: str) -> None:
        parts = raw.rstrip("\r").split(",")
        if len(parts) < 22 or parts[0] != "MSG":
            return
        try:
            msg_type = int(parts[1])
        except ValueError:
            return
        icao = parts[4].strip().lower()
        if not icao:
            return
        self.msg_count += 1
        p = self.planes.setdefault(icao, Plane(icao=icao))
        p.msg_count += 1
        p.last_seen = time.time()

        def _f(idx: int) -> Optional[float]:
            v = parts[idx].strip() if idx < len(parts) else ""
            try:
                return float(v) if v else None
            except ValueError:
                return None

        # BaseStation msg types 1-8, each fills a different subset of fields.
        if msg_type == 1:                       # ES Identification
            cs = parts[10].strip()
            if cs:
                p.callsign = cs
        elif msg_type == 2:                     # ES Surface position
            p.alt_ft   = _f(11) or p.alt_ft
            p.speed_kt = _f(12) or p.speed_kt
            p.track    = _f(13) or p.track
            p.lat      = _f(14) or p.lat
            p.lon      = _f(15) or p.lon
        elif msg_type == 3:                     # ES Airborne position
            p.alt_ft   = _f(11) or p.alt_ft
            p.lat      = _f(14) or p.lat
            p.lon      = _f(15) or p.lon
        elif msg_type == 4:                     # ES Airborne velocity
            p.speed_kt = _f(12) or p.speed_kt
            p.track    = _f(13) or p.track
        elif msg_type == 5:                     # Surveillance alt
            p.alt_ft = _f(11) or p.alt_ft
        elif msg_type == 6:                     # Surveillance id / squawk
            sq = parts[17].strip() if len(parts) > 17 else ""
            if sq:
                p.squawk = sq
        # types 7, 8 are air-air and other — ignore

    def close(self) -> None:
        if self.sock is not None:
            try: self.sock.close()
            except Exception: pass
            self.sock = None


def _fresh(planes: Dict[str, Plane], max_age_s: float = 60.0) -> List[Plane]:
    now = time.time()
    return [p for p in planes.values() if now - p.last_seen < max_age_s]


def _table(client: SbsClient) -> Table:
    fresh = _fresh(client.planes)
    with_pos = [p for p in fresh if p.lat is not None]
    table = Table(
        title=(f":airplane: [bold]{len(fresh)}[/] planes in the last minute  "
               f"([bold]{len(with_pos)}[/] with position) "
               f"• {client.msg_count:,} ADS-B messages total"),
        border_style="cyan", header_style="bold cyan",
    )
    for col in ("callsign", "ICAO", "alt (ft)", "kn", "track", "sq", "msgs", "lat", "lon"):
        table.add_column(col, no_wrap=True)
    for p in sorted(fresh, key=lambda x: -x.last_seen)[:25]:
        table.add_row(
            (p.callsign or "—").strip(),
            p.icao,
            f"{int(p.alt_ft):,}" if p.alt_ft is not None else "—",
            f"{p.speed_kt:.0f}"  if p.speed_kt is not None else "—",
            f"{p.track:.0f}°"    if p.track is not None else "—",
            p.squawk or "—",
            str(p.msg_count),
            f"{p.lat:.3f}" if p.lat is not None else "—",
            f"{p.lon:.3f}" if p.lon is not None else "—",
        )
    return table


def _build_map(planes: List[Plane]) -> Optional[str]:
    import folium

    with_pos = [p for p in planes if p.lat is not None and p.lon is not None]
    if not with_pos:
        return None
    cy = sum(p.lat for p in with_pos) / len(with_pos)
    cx = sum(p.lon for p in with_pos) / len(with_pos)
    m = folium.Map(location=[cy, cx], zoom_start=8, tiles="CartoDB positron")
    for p in with_pos:
        popup = (
            f"<b>{p.callsign or p.icao}</b><br>"
            f"altitude: {int(p.alt_ft) if p.alt_ft else '—'} ft<br>"
            f"speed: {int(p.speed_kt) if p.speed_kt else '—'} kn<br>"
            f"heading: {int(p.track) if p.track else '—'}°<br>"
            f"messages received: {p.msg_count}"
        )
        folium.CircleMarker(
            [p.lat, p.lon], radius=5,
            color="#00cc66", fill=True, fill_opacity=0.9,
            popup=folium.Popup(popup, max_width=260),
            tooltip=p.callsign or p.icao,
        ).add_to(m)
    return m.get_root().render()


def _spawn_dump1090() -> tuple[Optional[subprocess.Popen], Optional[str], Optional[str]]:
    exe = _which("dump1090") or _which("dump1090-fa")
    if not exe:
        return None, None, None
    log = tempfile.NamedTemporaryFile("w+", suffix=".dump1090.log", delete=False).name
    creation = 0
    if sys.platform == "win32":
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [exe, "--net", "--gain", "40"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
        creationflags=creation,
    )
    return proc, exe, log


def _kill(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try: proc.kill()
        except Exception: pass


def run(console: Console) -> None:
    dump_proc, dump_exe, dump_log = _spawn_dump1090()
    if dump_proc is not None:
        console.print(Panel(
            f"[green]Started {dump_exe} for you.[/] Owns the dongle at 1090 MHz\n"
            f"and exposes SBS on {DUMP1090_HOST}:{DUMP1090_SBS_PORT}.\n"
            "[dim]Give it 2 seconds to spin up…[/]",
            title="[green]:airplane: airplane tracker — one-click[/]",
            border_style="green",
        ))
        time.sleep(2.0)
    else:
        console.print(Panel(
            "You need [bold]dump1090[/] running. Install it (see --doctor), or\n"
            "run it manually in another terminal:\n"
            "    [cyan]dump1090 --net --gain 40[/]                # Linux/macOS\n"
            "    [cyan]dump1090.exe --net --gain 40[/]            # Windows\n\n"
            "dump1090 owns the dongle at 1090 MHz. SDR Kid just reads its output.\n\n"
        "[dim]Ctrl+C to stop.[/]",
        title="[green]:airplane: airplane tracker — your antenna[/]",
        border_style="green",
    ))

    client = SbsClient()
    err = client.connect()
    if err:
        os_name = current_os()
        install = DUMP1090.install.get(os_name, "")
        console.print(Panel(
            f"[red]{err}[/]\n\n"
            f"[bold]How to install dump1090 on {os_name}:[/]\n{install}\n\n"
            "Once it's running, come back to this menu and pick "
            "[bold]Track airplanes (your antenna)[/] again.",
            title="[red]dump1090 not reachable[/]", border_style="red",
        ))
        _kill(dump_proc)
        return

    server = get_server()
    opened = False
    last_map = 0.0
    connected_at = time.time()
    try:
        with Live(_table(client), console=console, refresh_per_second=2) as live:
            while client.connected:
                client.poll()
                now = time.time()
                # If we've been connected 15s with zero messages, help.
                if client.msg_count == 0 and now - connected_at > 15:
                    live.update(Panel(
                        "[yellow]Connected to dump1090 but no ADS-B messages yet.[/]\n\n"
                        "Common reasons:\n"
                        "  • Your antenna is a stubby whip indoors — 1090 MHz needs "
                        "line-of-sight to planes. Try a window or the roof.\n"
                        "  • No planes overhead right now. Check "
                        "[cyan]https://flightradar24.com[/] to see if any are nearby.\n"
                        "  • dump1090 was started without --net. It needs to expose "
                        "port 30003. Restart it like:\n"
                        "        [cyan]dump1090.exe --net --gain -10[/]      (Windows)\n"
                        "        [cyan]dump1090 --net --gain -10[/]           (Linux/macOS)\n"
                        "  • Gain too low. Try [cyan]--gain 40[/] instead of auto.",
                        title="[yellow]:mag: still listening…[/]",
                        border_style="yellow",
                    ))
                if now - last_map > 5:
                    fresh = _fresh(client.planes)
                    sightings = [
                        logbook.Sighting(icao=p.icao, callsign=p.callsign,
                                         alt_m=(p.alt_ft * 0.3048) if p.alt_ft else None,
                                         speed_kt=p.speed_kt)
                        for p in fresh
                    ]
                    if sightings:
                        new_count = logbook.record_batch(sightings)
                        hits = logbook.watchlist_hits(sightings)
                        if new_count:
                            achievements.celebrate(console,
                                achievements.record("plane_seen", amount=new_count))
                        if hits:
                            alert = "\n".join(
                                f":rotating_light: [bold red]{pat}[/] — "
                                f"{s.callsign or s.icao}{' — ' + note if note else ''}"
                                for pat, note, s in hits
                            )
                            console.print(Panel(alert, border_style="red",
                                                title="[red]watchlist hit[/]"))
                            achievements.celebrate(console,
                                achievements.record("watchlist_hit", amount=len(hits)))
                    html = _build_map(fresh)
                    if html:
                        write_static("planes.html", html)
                        if not opened:
                            try: webbrowser.open(f"{server.url}/view/planes.html")
                            except Exception: pass
                            opened = True
                    last_map = now
                live.update(_table(client))
                time.sleep(0.2)
        console.print(Panel("[yellow]dump1090 closed the connection.[/]",
                            border_style="yellow"))
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")
    finally:
        client.close()
        _kill(dump_proc)

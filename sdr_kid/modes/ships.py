from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid import progress as achievements
from sdr_kid.deps import current_os, which as _which
from sdr_kid.server import get_server, write_static


DEFAULT_UDP_PORT = 10110  # rtl_ais default (also common NMEA port)


@dataclass
class Ship:
    mmsi: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed: Optional[float] = None
    course: Optional[float] = None
    heading: Optional[float] = None
    name: str = ""
    callsign: str = ""
    ship_type: Optional[int] = None
    destination: str = ""
    last_seen: float = field(default_factory=time.time)


class AISListener:
    """Listens on UDP for NMEA AIS from rtl_ais / aisdispatcher.

    rtl_ais typical invocation:
        rtl_ais -h 127.0.0.1 -P 10110
    """

    def __init__(self, port: int = DEFAULT_UDP_PORT):
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.ships: Dict[int, Ship] = {}
        self.rx_count = 0
        self.last_rx_at: Optional[float] = None
        # buffer for multi-part sentences keyed by their sequence id
        self._pending: Dict[str, list] = {}
        try:
            from pyais import decode  # noqa: F401
            self._decoder_ok = True
        except Exception:
            self._decoder_ok = False

    def start(self) -> Optional[str]:
        if not self._decoder_ok:
            return "pyais is not installed (pip install pyais)"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", self.port))
            s.setblocking(False)
        except Exception as exc:
            return f"could not bind UDP :{self.port} — {exc}"
        self.sock = s
        return None

    def poll(self) -> None:
        if self.sock is None:
            return
        from pyais import decode
        # buffer for multi-fragment sentences keyed by (channel, seq)
        while True:
            try:
                data, _ = self.sock.recvfrom(4096)
            except BlockingIOError:
                return
            self.last_rx_at = time.time()
            for line in data.splitlines():
                line = line.strip()
                if not line.startswith(b"!"):
                    continue
                fields = line.split(b",")
                if len(fields) < 7:
                    continue
                try:
                    total = int(fields[1])
                    frag = int(fields[2])
                    seq  = fields[3].decode(errors="ignore") or "_"
                except ValueError:
                    continue
                if total == 1:
                    frames = [line]
                else:
                    key = f"{seq}:{total}"
                    buf = self._pending.setdefault(key, [None] * total)
                    if 1 <= frag <= total:
                        buf[frag - 1] = line
                    if any(x is None for x in buf):
                        continue
                    frames = buf
                    self._pending.pop(key, None)
                try:
                    msg = decode(*frames)
                except Exception:
                    continue
                self.rx_count += 1
                self._absorb(msg)

    def _absorb(self, msg) -> None:
        mmsi = getattr(msg, "mmsi", None)
        if mmsi is None:
            return
        s = self.ships.setdefault(int(mmsi), Ship(mmsi=int(mmsi)))
        s.last_seen = time.time()
        for attr, target in (
            ("lat", "lat"), ("lon", "lon"), ("speed", "speed"),
            ("course", "course"), ("heading", "heading"),
            ("shipname", "name"), ("callsign", "callsign"),
            ("ship_type", "ship_type"), ("destination", "destination"),
        ):
            v = getattr(msg, attr, None)
            if v in (None, "", 0) and target in ("name", "callsign", "destination"):
                continue
            if v is not None:
                setattr(s, target, v.strip() if isinstance(v, str) else v)

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def _table(listener: AISListener) -> Table:
    now = time.time()
    fresh = [s for s in listener.ships.values() if now - s.last_seen < 300 and s.lat is not None]
    table = Table(
        title=f":ship: [bold]{len(fresh)} ships heard[/]  •  {listener.rx_count} AIS messages received",
        border_style="blue",
        header_style="bold blue",
    )
    table.add_column("name", style="bold white")
    table.add_column("MMSI", style="dim")
    table.add_column("kn", justify="right")
    table.add_column("lat", justify="right", style="dim")
    table.add_column("lon", justify="right", style="dim")
    table.add_column("dest")
    for s in sorted(fresh, key=lambda x: -x.last_seen)[:25]:
        table.add_row(
            (s.name or "—")[:22],
            str(s.mmsi),
            f"{s.speed:.1f}" if s.speed is not None else "—",
            f"{s.lat:.3f}" if s.lat is not None else "—",
            f"{s.lon:.3f}" if s.lon is not None else "—",
            (s.destination or "—")[:16],
        )
    return table


def _build_map(listener: AISListener) -> Optional[str]:
    import folium

    now = time.time()
    ships = [s for s in listener.ships.values()
             if s.lat is not None and s.lon is not None and now - s.last_seen < 600]
    if not ships:
        return None
    cy = sum(s.lat for s in ships) / len(ships)
    cx = sum(s.lon for s in ships) / len(ships)
    m = folium.Map(location=[cy, cx], zoom_start=8, tiles="CartoDB dark_matter")
    for s in ships:
        popup = (
            f"<b>{s.name or 'unknown'}</b><br>"
            f"MMSI: {s.mmsi}<br>"
            f"callsign: {s.callsign or '—'}<br>"
            f"speed: {s.speed if s.speed is not None else '—'} kn<br>"
            f"course: {s.course if s.course is not None else '—'}°<br>"
            f"dest: {s.destination or '—'}"
        )
        folium.CircleMarker(
            [s.lat, s.lon],
            radius=5,
            color="#00c8ff",
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(popup, max_width=260),
            tooltip=s.name or str(s.mmsi),
        ).add_to(m)
    return m.get_root().render()


HOW_TO_INSTALL_UNIX = (
    "SDR Kid is listening on [bold]UDP :{port}[/]. Nothing has arrived yet.\n\n"
    "In another terminal, run:\n"
    "  [cyan]rtl_ais -h 127.0.0.1 -P {port}[/]\n\n"
    "Install rtl-ais:\n"
    "  [cyan]sudo apt install rtl-ais[/]     # Ubuntu / Debian / Raspberry Pi\n"
    "  [cyan]brew install rtl-ais[/]         # macOS\n\n"
    "AIS runs on 161.975 MHz and 162.025 MHz — you need to be within about 40 km\n"
    "of a coast, or ~10 km of a river, for a normal whip antenna to hear ships."
)

HOW_TO_INSTALL_WINDOWS = (
    "SDR Kid is listening on [bold]UDP :{port}[/]. Nothing has arrived yet.\n\n"
    "In a [bold]second[/] PowerShell window, run:\n"
    "  [cyan].\\AIS-catcher.exe -u 127.0.0.1 {port}[/]\n\n"
    "If that says '[dim]Address already in use[/]' — kill any older AIS-catcher.exe\n"
    "in Task Manager first.\n\n"
    "If it says '[dim]No supported devices found[/]' — another program still owns\n"
    "the dongle; unplug and replug it.\n\n"
    "If Windows Defender pops a dialog when AIS-catcher.exe starts, click\n"
    "[bold]Allow access[/] for Private networks.\n\n"
    "Install AIS-catcher: unzip the release from\n"
    "  https://github.com/jvde-github/AIS-catcher/releases\n"
    "and add its folder to PATH (or use the one-click installer in the README).\n\n"
    "AIS runs on 161.975 MHz and 162.025 MHz — you need to be within about 40 km\n"
    "of a coast, or ~10 km of a river, for a whip antenna to hear ships."
)


def _how_to_install() -> str:
    if current_os() == "windows":
        return HOW_TO_INSTALL_WINDOWS
    return HOW_TO_INSTALL_UNIX


def _spawn_ais_decoder(port: int) -> tuple[Optional[subprocess.Popen], Optional[str], Optional[str]]:
    """Launch AIS-catcher (Windows preferred) or rtl_ais as a subprocess.

    Returns (process, exe_name, log_path). All are None if no decoder is on PATH.
    """
    if _which("AIS-catcher"):
        exe = _which("AIS-catcher")
        cmd = [exe, "-u", "127.0.0.1", str(port), "-q"]
    elif _which("rtl_ais"):
        exe = _which("rtl_ais")
        cmd = [exe, "-h", "127.0.0.1", "-P", str(port)]
    else:
        return None, None, None
    log = tempfile.NamedTemporaryFile("w+", suffix=".ais.log", delete=False).name
    creation = 0
    if sys.platform == "win32":
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        cmd, stdout=open(log, "w"), stderr=subprocess.STDOUT,
        creationflags=creation,
    )
    return proc, cmd[0], log


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
    port = DEFAULT_UDP_PORT

    listener = AISListener(port=port)
    err = listener.start()
    if err:
        console.print(Panel(f"[red]{err}[/]", title="[red]can't listen[/]"))
        return

    server = get_server()
    proc, exe_name, log_path = _spawn_ais_decoder(port)
    if proc is not None:
        console.print(Panel(
            f"[green]Started {exe_name} for you.[/] "
            f"Decoding 161.975 / 162.025 MHz and firing NMEA at UDP :{port}.\n\n"
            f"[dim]log: {log_path}[/]\n"
            "[dim]This mode owns the dongle while it's open. Ctrl+C to stop.[/]",
            title="[blue]:ship: ship tracker — one-click[/]",
            border_style="blue",
        ))
    else:
        console.print(Panel(
            _how_to_install().format(port=port),
            title="[yellow]no AIS decoder on PATH[/]", border_style="yellow",
        ))

    opened = False
    last_map = 0.0
    started = time.time()
    _celebrated: Dict[str, bool] = {}
    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                listener.poll()
                now = time.time()

                # If we spawned a decoder and it died, surface why.
                if proc is not None and proc.poll() is not None:
                    live.stop()
                    tail = ""
                    if log_path:
                        try:
                            tail = open(log_path).read().strip()[-800:]
                        except Exception:
                            pass
                    console.print(Panel(
                        f"[red]{exe_name} exited with code {proc.returncode}[/]\n\n"
                        f"[dim]{tail or '(no output)'}[/]\n\n"
                        "[yellow]Common causes:[/]\n"
                        "  • Another program owns the dongle (SDR#, dump1090, rtl_fm)\n"
                        "  • Windows Defender blocked the first launch — allow it\n"
                        "  • Dongle unplugged mid-run",
                        title="[red]AIS decoder crashed[/]", border_style="red",
                    ))
                    break

                if listener.rx_count == 0 and now - started > 8:
                    live.update(Panel(
                        f"[yellow]Decoder is running but no AIS heard yet.[/]\n\n"
                        "AIS transmissions are line-of-sight and only carry ~40 km with\n"
                        "a normal whip antenna. If you're inland, this is expected.\n\n"
                        "Try:\n"
                        "  • move the antenna to a window facing water\n"
                        "  • wait a minute — vessels transmit every 2–10 s but signals fade\n"
                        "  • aim any Yagi towards the nearest port\n\n"
                        "[dim]Ctrl+C to stop.[/]",
                        title="[yellow]:ship: listening…[/]", border_style="yellow",
                    ))
                elif listener.rx_count == 0:
                    live.update(Panel("[cyan]starting up…[/]", border_style="cyan"))
                else:
                    if listener.ships and not _celebrated.get("ship_seen"):
                        achievements.celebrate(console,
                            achievements.record("ship_seen", amount=len(listener.ships)))
                        _celebrated["ship_seen"] = True
                    live.update(_table(listener))
                    if now - last_map > 10:
                        html = _build_map(listener)
                        if html:
                            write_static("ships.html", html)
                            if not opened:
                                try: webbrowser.open(f"{server.url}/view/ships.html")
                                except Exception: pass
                                opened = True
                        last_map = now
                time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")
    finally:
        _kill(proc)
        listener.close()

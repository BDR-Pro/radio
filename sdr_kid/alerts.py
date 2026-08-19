"""Background pass-alert service.

Watches a small set of satellites (ISS + NOAA APT birds) and fires a
notification a few minutes before each visible pass at the user's location.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from rich.console import Console
from rich.panel import Panel


CATALOG = {
    "ISS":        25544,
    "NOAA 15":    25338,
    "NOAA 18":    28654,
    "NOAA 19":    33591,
}


TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"
CACHE = Path.home() / ".sdr_kid_tles.json"


@dataclass
class Pass:
    sat: str
    rise_utc: datetime
    set_utc: datetime
    peak_elev_deg: float


def _load_tles(names: List[str]) -> Dict[str, tuple]:
    """{name: (line1, line2)}; caches on disk for 6 h."""
    cache: dict = {}
    if CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < 6 * 3600:
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}
    out: Dict[str, tuple] = {}
    missing = [n for n in names if n not in cache]
    if missing:
        with httpx.Client(timeout=15) as client:
            for name in missing:
                try:
                    r = client.get(TLE_URL.format(catnr=CATALOG[name]))
                    r.raise_for_status()
                    lines = r.text.strip().splitlines()
                    cache[name] = [lines[1].strip(), lines[2].strip()]
                except Exception:
                    continue
        CACHE.write_text(json.dumps(cache))
    for name in names:
        if name in cache:
            out[name] = tuple(cache[name])
    return out


def next_passes(lat: float, lon: float, hours: int = 6,
                sats: Optional[List[str]] = None,
                min_elev: float = 20.0) -> List[Pass]:
    from skyfield.api import EarthSatellite, load, wgs84

    sats = sats or list(CATALOG.keys())
    tles = _load_tles(sats)
    ts = load.timescale()
    ground = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = ts.utc(datetime.now(timezone.utc) + timedelta(hours=hours))
    out: List[Pass] = []
    for name, (l1, l2) in tles.items():
        sat = EarthSatellite(l1, l2, name, ts)
        try:
            times, events = sat.find_events(ground, t0, t1, altitude_degrees=min_elev)
        except Exception:
            continue
        rise: Optional[datetime] = None
        peak = 0.0
        for t, ev in zip(times, events):
            dt = t.utc_datetime()
            if ev == 0:
                rise = dt
                peak = 0.0
            elif ev == 1:
                diff = sat - ground
                alt, _, _ = diff.at(t).altaz()
                peak = alt.degrees
            elif ev == 2 and rise is not None:
                out.append(Pass(sat=name, rise_utc=rise, set_utc=dt, peak_elev_deg=peak))
                rise = None
    out.sort(key=lambda p: p.rise_utc)
    return out


def format_alert(p: Pass) -> str:
    local = p.rise_utc.astimezone()
    duration = int((p.set_utc - p.rise_utc).total_seconds() // 60)
    return (
        f"{p.sat} rises at {local.strftime('%H:%M')}, "
        f"lasts ~{duration} min, peak {p.peak_elev_deg:.0f}° elevation."
    )


def _system_notify(title: str, body: str) -> None:
    try:
        from plyer import notification  # type: ignore
        notification.notify(title=title, message=body, timeout=15)
        return
    except Exception:
        pass
    # graceful fallback: only try if the tool exists
    import shutil, subprocess
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", title, body], check=False, timeout=3)
        except Exception:
            pass


class AlertService:
    """Background thread that fires a notification `lead_minutes` before each pass."""

    def __init__(self, lat: float, lon: float, console: Optional[Console] = None,
                 lead_minutes: int = 5, min_elev: float = 20.0):
        self.lat = lat
        self.lon = lon
        self.console = console
        self.lead = timedelta(minutes=lead_minutes)
        self.min_elev = min_elev
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._notified: set = set()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="sdr-alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                passes = next_passes(self.lat, self.lon, hours=6, min_elev=self.min_elev)
            except Exception:
                passes = []
            now = datetime.now(timezone.utc)
            for p in passes:
                delta = p.rise_utc - now
                key = f"{p.sat}:{p.rise_utc.isoformat()}"
                if key in self._notified:
                    continue
                if timedelta(0) < delta <= self.lead:
                    self._fire(p)
                    self._notified.add(key)
            # sleep 60s, wake early if asked
            self._stop.wait(60)

    def _fire(self, p: Pass) -> None:
        title = f"SDR Kid — {p.sat} overhead soon"
        body = format_alert(p)
        _system_notify(title, body)
        if self.console is not None:
            self.console.print(Panel(
                f"[bold yellow]:satellite_antenna:  {body}[/]\n"
                "[dim]point your antenna at the sky![/]",
                title="[yellow]overhead alert[/]",
                border_style="yellow",
            ))

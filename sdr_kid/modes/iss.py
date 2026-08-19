from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import httpx
import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid.modes._audio import AudioChain
from sdr_kid.server import get_server, write_static


ISS_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
ISS_LIVE_URL = "http://api.open-notify.org/iss-now.json"

ISS_VOICE_FREQ_HZ = 145_800_000  # 145.800 MHz FM voice / SSTV downlink


@dataclass
class Pass:
    rise_utc: datetime
    set_utc: datetime
    peak_elev_deg: float

    @property
    def duration(self) -> timedelta:
        return self.set_utc - self.rise_utc


def _load_tle() -> tuple[str, str]:
    cache = Path.home() / ".sdr_kid_iss.tle"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 3600 * 6:
        lines = cache.read_text().splitlines()
        if len(lines) >= 3:
            return lines[1].strip(), lines[2].strip()
    with httpx.Client(timeout=15) as client:
        r = client.get(ISS_TLE_URL)
        r.raise_for_status()
        text = r.text
    cache.write_text(text)
    lines = text.strip().splitlines()
    return lines[1].strip(), lines[2].strip()


def _next_passes(lat: float, lon: float, hours: int = 24) -> List[Pass]:
    from skyfield.api import EarthSatellite, load, wgs84

    tle1, tle2 = _load_tle()
    ts = load.timescale()
    sat = EarthSatellite(tle1, tle2, "ISS", ts)
    ground = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = ts.utc(datetime.now(timezone.utc) + timedelta(hours=hours))
    times, events = sat.find_events(ground, t0, t1, altitude_degrees=10.0)
    passes: List[Pass] = []
    rise: Optional[datetime] = None
    peak_elev = 0.0
    for t, ev in zip(times, events):
        dt = t.utc_datetime()
        if ev == 0:
            rise = dt
            peak_elev = 0.0
        elif ev == 1:
            diff = sat - ground
            alt, _, _ = diff.at(t).altaz()
            peak_elev = alt.degrees
        elif ev == 2 and rise is not None:
            passes.append(Pass(rise_utc=rise, set_utc=dt, peak_elev_deg=peak_elev))
            rise = None
    return passes


def _live_position() -> Optional[tuple[float, float]]:
    try:
        with httpx.Client(timeout=8) as client:
            r = client.get(ISS_LIVE_URL)
            r.raise_for_status()
            data = r.json()
        return float(data["iss_position"]["latitude"]), float(data["iss_position"]["longitude"])
    except Exception:
        return None


def _build_map(iss_lat: float, iss_lon: float, home_lat: float, home_lon: float) -> str:
    import folium

    m = folium.Map(location=[iss_lat, iss_lon], zoom_start=3, tiles="CartoDB dark_matter")
    folium.Marker(
        [home_lat, home_lon],
        tooltip="you",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)
    folium.Marker(
        [iss_lat, iss_lon],
        tooltip="ISS (right now)",
        icon=folium.Icon(color="orange", icon="star"),
    ).add_to(m)
    folium.PolyLine(
        [[home_lat, home_lon], [iss_lat, iss_lon]],
        color="#ffcc00",
        weight=2,
        opacity=0.6,
        dash_array="5,5",
    ).add_to(m)
    return m.get_root().render()


def _pass_table(passes: List[Pass]) -> Table:
    table = Table(
        title=":satellite: [bold]next ISS passes over your sky[/]",
        border_style="yellow",
        header_style="bold yellow",
    )
    table.add_column("when (local)")
    table.add_column("duration", justify="right")
    table.add_column("peak elevation", justify="right")
    table.add_column("visible")
    for p in passes[:10]:
        local = p.rise_utc.astimezone()
        vis = "yes" if p.peak_elev_deg >= 25 else "low"
        table.add_row(
            local.strftime("%a %H:%M"),
            f"{int(p.duration.total_seconds() // 60)}m",
            f"{p.peak_elev_deg:.0f}°",
            vis,
        )
    return table


def _ask_home() -> Optional[tuple[float, float]]:
    presets = {
        "Riyadh":  (24.7136, 46.6753),
        "London":  (51.5074, -0.1278),
        "New York":(40.7128, -74.0060),
        "Tokyo":   (35.6762, 139.6503),
    }
    ans = questionary.select(
        "Where are you standing?",
        choices=list(presets.keys()) + ["Custom coordinates", "Cancel"],
    ).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom coordinates":
        lat = questionary.text("Latitude:").ask()
        lon = questionary.text("Longitude:").ask()
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None
    return presets[ans]


def _ask_action() -> str:
    return questionary.select(
        "What do you want to do?",
        choices=[
            "See where the ISS is right now",
            "List upcoming passes (next 24h)",
            "Tune the radio to 145.800 MHz (astronaut voice / SSTV)",
            "Cancel",
        ],
    ).ask() or "Cancel"


def run(console: Console) -> None:
    home = _ask_home()
    if home is None:
        return
    lat, lon = home

    action = _ask_action()
    if action == "Cancel":
        return

    server = get_server()

    if action.startswith("List upcoming passes"):
        try:
            passes = _next_passes(lat, lon)
        except Exception as exc:
            console.print(Panel(f"[red]could not compute passes: {exc}[/]"))
            return
        console.print(_pass_table(passes))
        console.print(
            "[dim]tip: point your antenna up as the ISS rises. VHF signals like "
            "line-of-sight — a rooftop with sky is best.[/]"
        )
        return

    if action.startswith("Tune the radio"):
        chain = AudioChain(freq_hz=ISS_VOICE_FREQ_HZ, mode="fm", sample_rate=12_000, squelch=30)
        problem = chain.check()
        if problem:
            console.print(Panel(f"[red]{problem}[/]"))
            return
        console.print(
            Panel(
                "Tuned to [bold]145.800 MHz FM[/] — the ISS voice / SSTV downlink.\n"
                "You'll hear silence except when the station is above the horizon "
                "AND the crew has the radio on. Try during a scheduled SSTV event!\n\n"
                "[dim]Ctrl+C to stop listening.[/]",
                title="[yellow]:satellite: listening for the ISS[/]",
                border_style="yellow",
            )
        )
        chain.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            chain.stop()
        return

    opened = False
    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                pos = _live_position()
                if pos is None:
                    live.update(Panel("[red]couldn't reach the ISS position API[/]"))
                else:
                    ilat, ilon = pos
                    html = _build_map(ilat, ilon, lat, lon)
                    write_static("iss.html", html)
                    table = Table.grid(padding=(0, 2))
                    table.add_row("[yellow]ISS latitude[/]",  f"{ilat:.3f}")
                    table.add_row("[yellow]ISS longitude[/]", f"{ilon:.3f}")
                    table.add_row("[yellow]your latitude[/]",  f"{lat:.3f}")
                    table.add_row("[yellow]your longitude[/]", f"{lon:.3f}")
                    table.add_row("[yellow]voice freq[/]",     "145.800 MHz FM")
                    table.add_row("[yellow]map[/]",            f"{server.url}/view/iss.html")
                    live.update(
                        Panel.fit(
                            table,
                            title="[yellow]:satellite: ISS live[/]",
                            border_style="yellow",
                            subtitle="[dim]updates every 5s • Ctrl+C to stop[/]",
                        )
                    )
                    if not opened:
                        try:
                            webbrowser.open(f"{server.url}/view/iss.html")
                        except Exception:
                            pass
                        opened = True
                time.sleep(5)
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")

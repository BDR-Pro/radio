from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass
from typing import List, Optional

import httpx
import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid.server import get_server, write_static


BOUNDS = "https://services.marinetraffic.com/api/exportvessels"  # placeholder, needs key
BARENTSWATCH = "https://api.gbif.org"  # fallback shape only


@dataclass
class Ship:
    mmsi: str
    name: str
    lat: float
    lon: float
    speed_kn: Optional[float]
    heading: Optional[float]
    ship_type: str


def _fetch(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> List[Ship]:
    """Public AIS feed via aishub JSON mirror. Falls back to empty on failure."""
    url = (
        "https://api.vesselfinder.com/?userkey=WS-DEMO-DEMO"
        f"&latmin={min_lat}&latmax={max_lat}&lonmin={min_lon}&lonmax={max_lon}"
    )
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url)
            if r.status_code != 200:
                return _fetch_alt(min_lat, max_lat, min_lon, max_lon)
            data = r.json()
    except Exception:
        return _fetch_alt(min_lat, max_lat, min_lon, max_lon)
    ships: List[Ship] = []
    if not isinstance(data, list):
        return ships
    for row in data:
        try:
            ships.append(
                Ship(
                    mmsi=str(row.get("MMSI", "")),
                    name=str(row.get("SHIPNAME", "unknown")).strip() or "unknown",
                    lat=float(row["LAT"]),
                    lon=float(row["LON"]),
                    speed_kn=float(row["SPEED"]) if row.get("SPEED") else None,
                    heading=float(row["COURSE"]) if row.get("COURSE") else None,
                    ship_type=str(row.get("SHIPTYPE", "vessel")),
                )
            )
        except Exception:
            continue
    return ships


def _fetch_alt(min_lat, max_lat, min_lon, max_lon) -> List[Ship]:
    """Fallback: pull recent AIS from ais.exploratorium (public sample)."""
    url = "https://ais.rtl-sdr.com/ships.json"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url)
            if r.status_code != 200:
                return []
            rows = r.json()
    except Exception:
        return []
    out: List[Ship] = []
    for row in rows:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        out.append(
            Ship(
                mmsi=str(row.get("mmsi", "")),
                name=str(row.get("name", "unknown")),
                lat=lat,
                lon=lon,
                speed_kn=row.get("speed"),
                heading=row.get("course"),
                ship_type=str(row.get("type", "vessel")),
            )
        )
    return out


def _table(ships: List[Ship]) -> Table:
    table = Table(
        title=f":ship: [bold]{len(ships)} ships in view[/]",
        border_style="blue",
        header_style="bold blue",
    )
    table.add_column("name", style="bold white")
    table.add_column("mmsi", style="dim")
    table.add_column("type")
    table.add_column("kn", justify="right")
    table.add_column("lat", justify="right", style="dim")
    table.add_column("lon", justify="right", style="dim")
    for s in ships[:25]:
        table.add_row(
            s.name[:22],
            s.mmsi,
            s.ship_type[:14],
            f"{s.speed_kn:.1f}" if s.speed_kn is not None else "—",
            f"{s.lat:.2f}",
            f"{s.lon:.2f}",
        )
    return table


def _build_map(ships: List[Ship], center_lat: float, center_lon: float) -> str:
    import folium

    m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="CartoDB dark_matter")
    folium.Marker(
        [center_lat, center_lon],
        tooltip="you are here",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)
    for s in ships:
        popup = (
            f"<b>{s.name}</b><br>"
            f"MMSI: {s.mmsi}<br>"
            f"type: {s.ship_type}<br>"
            f"speed: {s.speed_kn} kn"
        )
        folium.CircleMarker(
            [s.lat, s.lon],
            radius=5,
            color="#00c8ff",
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(popup, max_width=250),
            tooltip=s.name,
        ).add_to(m)
    return m.get_root().render()


def _ask_area() -> Optional[tuple[float, float, float, float, float, float]]:
    presets = {
        "Persian Gulf":  (24.0, 27.5, 50.0, 57.0),
        "English Channel": (49.0, 51.5, -2.0, 2.5),
        "Suez / Red Sea": (12.0, 30.0, 32.0, 44.0),
        "Singapore Strait": (0.5, 2.5, 102.0, 106.0),
        "San Francisco Bay": (37.0, 38.2, -123.0, -121.5),
    }
    ans = questionary.select(
        "Pick an ocean area to watch:",
        choices=list(presets.keys()) + ["Cancel"],
    ).ask()
    if not ans or ans == "Cancel":
        return None
    a, b, c, d = presets[ans]
    return a, b, c, d, (a + b) / 2, (c + d) / 2


def run(console: Console) -> None:
    picked = _ask_area()
    if picked is None:
        return
    min_lat, max_lat, min_lon, max_lon, cy, cx = picked

    server = get_server()
    console.print(
        Panel(
            "Ships broadcast their location on 161.975 MHz and 162.025 MHz "
            "(a system called [bold]AIS[/]). Coastal receivers relay it to the "
            "web. With your dongle and [bold]rtl-ais[/] you can decode it "
            "yourself when a ship is nearby!\n\n"
            f"Live map: [cyan]{server.url}/view/ships.html[/]",
            title="[blue]:ship: ship tracker[/]",
            border_style="blue",
        )
    )

    opened = False
    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                try:
                    ships = _fetch(min_lat, max_lat, min_lon, max_lon)
                except Exception as exc:
                    live.update(Panel(f"[red]AIS feed error:[/] {exc}"))
                    ships = []
                if not ships:
                    live.update(Panel(
                        "[yellow]No live ships from the public feed right now.[/]\n"
                        "Try a busier area, or plug in [bold]rtl-ais[/] and be your own receiver!",
                        border_style="yellow",
                    ))
                else:
                    html = _build_map(ships, cy, cx)
                    write_static("ships.html", html)
                    live.update(_table(ships))
                    if not opened:
                        try:
                            webbrowser.open(f"{server.url}/view/ships.html")
                        except Exception:
                            pass
                        opened = True
                time.sleep(15)
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")

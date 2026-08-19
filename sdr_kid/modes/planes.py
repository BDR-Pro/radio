from __future__ import annotations

import math
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


OPENSKY = "https://opensky-network.org/api/states/all"


@dataclass
class Plane:
    icao: str
    callsign: str
    country: str
    lat: float
    lon: float
    alt_m: Optional[float]
    speed_ms: Optional[float]
    heading: Optional[float]

    @property
    def alt_ft(self) -> str:
        if self.alt_m is None:
            return "—"
        return f"{int(self.alt_m * 3.281):,}"

    @property
    def speed_kt(self) -> str:
        if self.speed_ms is None:
            return "—"
        return f"{int(self.speed_ms * 1.944)}"


def _fetch(lat: float, lon: float, radius_km: float) -> List[Plane]:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.05))
    params = {
        "lamin": lat - dlat,
        "lamax": lat + dlat,
        "lomin": lon - dlon,
        "lomax": lon + dlon,
    }
    with httpx.Client(timeout=15) as client:
        r = client.get(OPENSKY, params=params)
        r.raise_for_status()
        data = r.json()
    out: List[Plane] = []
    for s in data.get("states") or []:
        if s[5] is None or s[6] is None:
            continue
        out.append(
            Plane(
                icao=(s[0] or "").strip(),
                callsign=(s[1] or "").strip() or "n/a",
                country=(s[2] or "").strip(),
                lon=float(s[5]),
                lat=float(s[6]),
                alt_m=s[7],
                speed_ms=s[9],
                heading=s[10],
            )
        )
    return out


def _table(planes: List[Plane]) -> Table:
    table = Table(
        title=f":airplane: [bold]{len(planes)} aircraft in view[/]",
        border_style="cyan",
        header_style="bold cyan",
    )
    table.add_column("callsign", style="bold white")
    table.add_column("country", style="dim")
    table.add_column("alt (ft)", justify="right")
    table.add_column("speed (kt)", justify="right")
    table.add_column("lat", justify="right", style="dim")
    table.add_column("lon", justify="right", style="dim")
    for p in sorted(planes, key=lambda x: -(x.alt_m or 0))[:25]:
        table.add_row(
            p.callsign,
            p.country[:14],
            p.alt_ft,
            p.speed_kt,
            f"{p.lat:.2f}",
            f"{p.lon:.2f}",
        )
    return table


def _build_map(planes: List[Plane], center_lat: float, center_lon: float) -> str:
    import folium

    m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="CartoDB positron")
    folium.Marker(
        [center_lat, center_lon],
        tooltip="you are here",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)
    for p in planes:
        popup = (
            f"<b>{p.callsign}</b><br>"
            f"country: {p.country}<br>"
            f"altitude: {p.alt_ft} ft<br>"
            f"speed: {p.speed_kt} kt"
        )
        folium.CircleMarker(
            [p.lat, p.lon],
            radius=5,
            color="#0066cc",
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(popup, max_width=250),
            tooltip=p.callsign,
        ).add_to(m)
    return m.get_root().render()


def _ask_location() -> Optional[tuple[float, float, float]]:
    presets = {
        "Riyadh (SA)":       (24.7136, 46.6753),
        "Jeddah (SA)":       (21.4858, 39.1925),
        "London (UK)":       (51.5074, -0.1278),
        "New York (US)":     (40.7128, -74.0060),
        "Tokyo (JP)":        (35.6762, 139.6503),
    }
    label = questionary.select(
        "Where should I scan for planes?",
        choices=list(presets.keys()) + ["Custom coordinates", "Cancel"],
    ).ask()
    if not label or label == "Cancel":
        return None
    if label == "Custom coordinates":
        lat = questionary.text("Latitude:").ask()
        lon = questionary.text("Longitude:").ask()
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
    else:
        lat_f, lon_f = presets[label]
    radius = questionary.text("Radius in km (default 200):", default="200").ask()
    try:
        r = float(radius or "200")
    except ValueError:
        r = 200.0
    return lat_f, lon_f, r


def run(console: Console) -> None:
    picked = _ask_location()
    if picked is None:
        return
    lat, lon, radius = picked

    server = get_server()
    console.print(
        Panel(
            "Data comes from the [bold]OpenSky Network[/] (real ADS-B receivers "
            "around the world). If you install [bold]dump1090[/] and point your "
            "antenna at the sky (1090 MHz), you'll be one of those receivers!\n\n"
            f"Live map: [cyan]{server.url}/view/planes.html[/]",
            title="[cyan]:airplane: airplane tracker[/]",
            border_style="cyan",
        )
    )

    opened = False
    try:
        with Live(console=console, refresh_per_second=1, screen=False) as live:
            while True:
                try:
                    planes = _fetch(lat, lon, radius)
                except Exception as exc:
                    live.update(Panel(f"[red]OpenSky error:[/] {exc}"))
                else:
                    html = _build_map(planes, lat, lon)
                    write_static("planes.html", html)
                    live.update(_table(planes))
                    if not opened:
                        try:
                            webbrowser.open(f"{server.url}/view/planes.html")
                        except Exception:
                            pass
                        opened = True
                time.sleep(10)
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")

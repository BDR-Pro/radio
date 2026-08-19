from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid.alerts import AlertService, format_alert, next_passes


HOME_FILE = Path.home() / ".sdr_kid_home.json"


def _remember_home(lat: float, lon: float) -> None:
    import json
    HOME_FILE.write_text(json.dumps({"lat": lat, "lon": lon}))


def _recall_home() -> Optional[tuple]:
    import json
    if not HOME_FILE.exists():
        return None
    try:
        d = json.loads(HOME_FILE.read_text())
        return float(d["lat"]), float(d["lon"])
    except Exception:
        return None


def _ask_home(console: Console) -> Optional[tuple]:
    remembered = _recall_home()
    presets = {
        "Riyadh":   (24.7136, 46.6753),
        "London":   (51.5074, -0.1278),
        "New York": (40.7128, -74.0060),
        "Tokyo":    (35.6762, 139.6503),
    }
    if remembered:
        keep = questionary.select(
            f"use your saved location ({remembered[0]:.2f}, {remembered[1]:.2f})?",
            choices=["yes", "pick another", "cancel"],
        ).ask()
        if keep == "yes":
            return remembered
        if keep in (None, "cancel"):
            return None
    ans = questionary.select(
        "where are you standing?",
        choices=list(presets.keys()) + ["custom coordinates", "cancel"],
    ).ask()
    if not ans or ans == "cancel":
        return None
    if ans == "custom coordinates":
        lat = questionary.text("latitude:").ask()
        lon = questionary.text("longitude:").ask()
        try:
            home = (float(lat), float(lon))
        except (TypeError, ValueError):
            return None
    else:
        home = presets[ans]
    _remember_home(*home)
    return home


def _upcoming_table(passes) -> Table:
    t = Table(
        title=":satellite: upcoming passes (next 6 hours)",
        border_style="yellow", header_style="bold yellow",
    )
    t.add_column("satellite", style="bold white")
    t.add_column("when (local)")
    t.add_column("dur (min)", justify="right")
    t.add_column("peak elev", justify="right")
    if not passes:
        t.add_row("—", "no visible passes above 20° in the next 6h", "—", "—")
    for p in passes[:12]:
        local = p.rise_utc.astimezone()
        dur = int((p.set_utc - p.rise_utc).total_seconds() // 60)
        t.add_row(p.sat, local.strftime("%a %H:%M"), str(dur), f"{p.peak_elev_deg:.0f}°")
    return t


def run(console: Console) -> None:
    home = _ask_home(console)
    if home is None:
        return
    lat, lon = home

    lead = questionary.text("how many minutes' warning?", default="5").ask()
    try:
        lead_min = max(1, int(lead or "5"))
    except ValueError:
        lead_min = 5

    console.print(Panel(
        f"Alerts armed for [bold]{lat:.3f}, {lon:.3f}[/] — you'll be warned "
        f"{lead_min} min before any ISS / NOAA pass above 20°.\n"
        "This keeps running in the background even after you leave this screen "
        "(until you quit SDR Kid). [dim]Ctrl+C to return to the menu.[/]",
        title="[yellow]:bell: overhead alerts[/]",
        border_style="yellow",
    ))

    svc = AlertService(lat, lon, console=console, lead_minutes=lead_min)
    svc.start()

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                passes = next_passes(lat, lon, hours=6)
                live.update(_upcoming_table(passes))
                time.sleep(60)
    except KeyboardInterrupt:
        console.print("[dim]back to menu (alerts keep running in the background).[/]")

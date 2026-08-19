from __future__ import annotations

import time

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid.alerts import AlertService, next_passes
from sdr_kid.location import ask as ask_home


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
    home = ask_home(console)
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

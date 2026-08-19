from __future__ import annotations

from datetime import datetime

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sdr_kid import logbook, progress


def _stats_panel() -> Panel:
    s = logbook.stats()
    body = (
        f"[bold cyan]{s['aircraft']:,}[/] unique aircraft ever seen\n"
        f"[bold cyan]{s['sightings']:,}[/] total sightings\n"
        f"[bold cyan]{int(s['max_alt_m']*3.281):,} ft[/] highest altitude ever logged"
    )
    return Panel(body, title="[cyan]:notebook: your logbook[/]", border_style="cyan")


def _recent_table() -> Table:
    table = Table(
        title="most recently seen aircraft",
        border_style="cyan",
        header_style="bold cyan",
    )
    for col in ("callsign", "icao", "country", "hits", "max ft", "max kt", "last seen"):
        table.add_column(col)
    for r in logbook.top(20):
        table.add_row(
            (r["callsign"] or "").strip() or "—",
            r["icao"],
            (r["country"] or "").strip() or "—",
            str(r["hits"]),
            f"{int((r['max_alt_m'] or 0)*3.281):,}",
            f"{r['max_kt']:.0f}" if r["max_kt"] else "—",
            datetime.fromtimestamp(r["last_seen"]).strftime("%Y-%m-%d %H:%M"),
        )
    return table


def _watchlist_table() -> Table:
    table = Table(
        title=":eyes: watchlist",
        border_style="red",
        header_style="bold red",
    )
    table.add_column("pattern")
    table.add_column("note", style="dim")
    table.add_column("added", style="dim")
    for r in logbook.watchlist_all():
        table.add_row(
            r["pattern"],
            r["note"] or "",
            datetime.fromtimestamp(r["added_at"]).strftime("%Y-%m-%d %H:%M"),
        )
    return table


def run(console: Console) -> None:
    while True:
        console.print(_stats_panel())
        console.print(_recent_table())
        console.print(_watchlist_table())
        console.print(progress.summary_table())
        action = questionary.select(
            "logbook action:",
            choices=[
                "Add a callsign / ICAO to the watchlist",
                "Remove one from the watchlist",
                "Back",
            ],
        ).ask()
        if action is None or action == "Back":
            return
        if action.startswith("Add"):
            pattern = questionary.text("callsign fragment or ICAO hex to watch:").ask()
            note = questionary.text("note (optional):").ask() or ""
            if pattern:
                logbook.watchlist_add(pattern, note)
        elif action.startswith("Remove"):
            entries = logbook.watchlist_all()
            if not entries:
                console.print("[dim]watchlist is empty[/]")
                continue
            pick = questionary.select(
                "remove which?",
                choices=[e["pattern"] for e in entries] + ["Cancel"],
            ).ask()
            if pick and pick != "Cancel":
                logbook.watchlist_remove(pick)

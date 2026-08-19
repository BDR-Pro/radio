from __future__ import annotations

import sys

import questionary
from rich.console import Console
from rich.panel import Panel

from sdr_kid.banner import render_banner
from sdr_kid.dongle import probe, show_dongle_card, wait_for_dongle
from sdr_kid.modes import (
    alerts_ui, atc, explore, fm, iq, iss, logbook_ui, noaa, planes, ships,
)
from sdr_kid.progress import summary_table


MENU = [
    ("Listen to FM radio (music)",          fm.run),
    ("Track airplanes on a map",            planes.run),
    ("Listen to Air Traffic Control",       atc.run),
    ("Look at the ISS (space station)",     iss.run),
    ("Track ships on the ocean",            ships.run),
    ("Explore the RF spectrum",             explore.run),
    ("Catch a NOAA weather-satellite image", noaa.run),
    ("Overhead alerts (ISS / NOAA)",        alerts_ui.run),
    ("Airplane logbook + watchlist",        logbook_ui.run),
    ("Record & replay raw radio (IQ)",      iq.run),
    ("Show my quests",                      lambda c: c.print(summary_table())),
    ("Quit",                                None),
]


HELP = (
    "[bold cyan]How this works[/]\n\n"
    "Your USB dongle is a tiny [italic]software defined radio[/]. Instead of "
    "having one knob for FM and one for AM, it hands the [bold]raw radio waves[/] "
    "to your computer. Python then decides what to do with them — turn them into "
    "music, decode a plane's position, or paint a spectrum picture.\n\n"
    "Each menu item is a small Python program that talks to the dongle in a "
    "different way. Read the source in [magenta]sdr_kid/modes/[/] to see how!\n\n"
    "Everything you do earns [yellow]quests[/] — pick [bold]Show my quests[/] "
    "to see how far you've come."
)


def _menu(console: Console) -> None:
    while True:
        choice = questionary.select(
            "What do you want to do?",
            choices=[label for label, _ in MENU] + ["Help"],
            pointer=">>",
        ).ask()
        if choice is None or choice == "Quit":
            console.print("[bold cyan]73! (that's radio-speak for 'best wishes').[/]")
            return
        if choice == "Help":
            console.print(Panel(HELP, border_style="cyan", title="[cyan]what is this?[/]"))
            continue
        for label, fn in MENU:
            if label == choice and fn is not None:
                try:
                    fn(console)
                except KeyboardInterrupt:
                    console.print("[dim]stopped.[/]")
                except Exception as exc:
                    console.print(Panel(f"[red]oops:[/] {exc}", border_style="red"))
                break


def main() -> int:
    console = Console()
    render_banner(console)

    if "--skip-dongle" in sys.argv:
        console.print("[yellow]--skip-dongle: not checking the dongle.[/]")
    else:
        info = probe()
        if not info.present:
            # Second try: hardware may be plugged in but not yet enumerated.
            info = wait_for_dongle(console, timeout=15.0)
        if info.present:
            show_dongle_card(console, info)
        else:
            reason_lower = (info.reason or "").lower()
            probably_busy = any(k in reason_lower for k in (
                "busy", "in use", "resource", "usb_open error", "-3", "-6",
            ))
            hint = (
                "[dim]Looks like another program is already using the dongle "
                "(AIS-catcher, rtl_ais, dump1090, SDR#…).[/]\n"
                "[dim]That's fine — pick [bold]Track ships[/] and SDR Kid will read "
                "from its UDP feed instead.[/]\n"
                if probably_busy else
                "[dim]No dongle found yet. Online-only modes (planes / ships map / "
                "ISS map / logbook / quests) still work.[/]\n"
                "[dim]Radio modes (FM, ATC, RF explorer, NOAA APT, IQ record) will "
                "error out until the dongle is available.[/]\n"
            )
            console.print(
                Panel(
                    f"[yellow]dongle probe:[/] {info.reason}\n\n{hint}"
                    "[dim]Tip: pass [bold]--skip-dongle[/] on the command line to "
                    "silence this next time.[/]",
                    border_style="yellow",
                    title="[yellow]continuing without direct dongle access[/]",
                )
            )

    _menu(console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

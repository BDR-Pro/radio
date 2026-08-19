from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, List, Tuple

from sdr_kid import __version__


# (label, "sdr_kid.modes.name", "run", one-line-hint)
# NOTE: we intentionally store dotted-string references instead of importing
# each mode at module load. Loading e.g. sdr_kid.modes.planes pulls in httpx
# and folium; if any of those explode, we still want `--help`, `--list` and
# `--version` to work.
MENU: List[Tuple[str, str, str, str]] = [
    ("Listen to FM radio (music)",              "sdr_kid.modes.fm",           "run", "wide-band FM broadcast — 88–108 MHz"),
    ("Track airplanes — my antenna (dump1090)", "sdr_kid.modes.planes_local", "run", "real ADS-B decoded by YOUR dongle at 1090 MHz"),
    ("Track airplanes — the world (OpenSky)",   "sdr_kid.modes.planes",       "run", "planes from every receiver on Earth, via OpenSky's free web API"),
    ("Listen to Air Traffic Control",           "sdr_kid.modes.atc",          "run", "AM aviation voice, 118–137 MHz"),
    ("Look at the ISS (space station)",         "sdr_kid.modes.iss",          "run", "predict passes, see live position, tune 145.800 MHz"),
    ("Track ships on the ocean",                "sdr_kid.modes.ships",        "run", "AIS 161.975 / 162.025 MHz via rtl_ais or AIS-catcher"),
    ("Explore the RF spectrum",                 "sdr_kid.modes.explore",      "run", "sweep any band, see a waterfall in your terminal AND browser"),
    ("Catch a NOAA weather-satellite image",    "sdr_kid.modes.noaa",         "run", "record 137 MHz during an overhead pass, decode into a real image"),
    ("Overhead alerts (ISS / NOAA)",            "sdr_kid.modes.alerts_ui",    "run", "system notification 5 min before the next visible pass"),
    ("Airplane logbook + watchlist",            "sdr_kid.modes.logbook_ui",   "run", "every plane you've heard, ever — with a callsign watchlist"),
    ("Record & replay raw radio (IQ)",          "sdr_kid.modes.iq",           "run", "save raw samples to disk, replay them like a tape"),
    ("Show my quests",                          "sdr_kid.progress",           "_show_quests_from_menu",
                                                                                     "tick off milestones — first plane, caught the ISS, decoded a satellite…"),
    ("Health check (is everything installed?)", "sdr_kid.doctor",             "_from_menu",
                                                                                     "runs every check — Python packages, tools, dongle, ports, disk"),
    ("Quit",                                    "",                           "",    ""),
]


HELP_INTRO = """[bold cyan]what is this?[/]

Your USB dongle is a [italic]software defined radio[/] (SDR). Instead of
one knob for FM and one for AM, it hands the raw radio waves — a stream of
numbers — to your computer. Python then decides what to do with them:
turn them into music, decode a plane's position, or paint a spectrum
picture.

Each menu item below is a small Python program that talks to the dongle
in a different way. Read the source in [magenta]sdr_kid/modes/[/] — every
file is under 300 lines and shows you exactly how radio + Python fit
together. That's the whole trick. There is no magic.

Every mode you complete unlocks a [yellow]quest[/]. Pick [bold]Show my quests[/]
to see how far you've come.
"""


def _load(mod_name: str, attr: str) -> Callable:
    return getattr(importlib.import_module(mod_name), attr)


def _print_menu_table(console) -> None:
    from rich.table import Table
    t = Table(
        title=":radio: what SDR Kid can do",
        border_style="cyan", header_style="bold cyan",
    )
    t.add_column("#", style="dim", justify="right")
    t.add_column("mode",         style="bold white")
    t.add_column("what it does", style="dim")
    for i, (label, mod, _, hint) in enumerate(MENU, start=1):
        if not mod:
            continue
        t.add_row(str(i), label, hint)
    console.print(t)


def _cli_help(console) -> None:
    from rich.panel import Panel
    from sdr_kid.banner import render_banner
    render_banner(console)
    console.print(Panel(HELP_INTRO, border_style="cyan", title="[cyan]SDR Kid help[/]"))
    _print_menu_table(console)
    console.print(Panel(
        "[bold]Usage[/]\n"
        "  python -m sdr_kid                 — launch the interactive menu\n"
        "  python -m sdr_kid --skip-dongle   — skip the dongle probe (for online-only modes,\n"
        "                                       or when dump1090 / AIS-catcher owns the dongle)\n"
        "  python -m sdr_kid --list          — print this help + mode table and exit\n"
        "  python -m sdr_kid --version       — print version and exit\n\n"
        "[bold]Companion tools that plug in over UDP/TCP[/]\n"
        "  dump1090 --net              → SDR Kid's 'my antenna' plane tracker (port 30003)\n"
        "  rtl_ais -h 127.0.0.1 -P 10110  → SDR Kid's ship tracker (port 10110)\n"
        "  AIS-catcher -u 127.0.0.1 10110 → same, Windows-friendly\n\n"
        "[bold]Files SDR Kid keeps[/]\n"
        "  ~/.sdr_kid_progress.json  — your quest progress\n"
        "  ~/.sdr_kid_logbook.sqlite — every plane you've ever seen\n"
        "  ~/.sdr_kid_home.json      — the coordinates you told us\n"
        "  ~/.sdr_kid_tles.json      — cached satellite orbits (refreshed every 6h)\n"
        "  ~/sdr_kid_recordings/     — raw IQ files\n\n"
        "[dim]This is your project. Read the code. Break it. Fix it. Make it yours.[/]",
        border_style="magenta", title="[magenta]command-line reference[/]",
    ))


def _menu(console) -> None:
    import questionary
    from rich.panel import Panel

    labels = [label for label, _, _, _ in MENU]
    while True:
        choice = questionary.select(
            "What do you want to do?",
            choices=labels + ["Help"],
            pointer=">>",
        ).ask()
        if choice is None or choice == "Quit":
            console.print("[bold cyan]73! (that's radio-speak for 'best wishes').[/]")
            return
        if choice == "Help":
            console.print(Panel(HELP_INTRO, border_style="cyan", title="[cyan]what is this?[/]"))
            _print_menu_table(console)
            continue
        for label, mod, attr, _hint in MENU:
            if label != choice or not mod:
                continue
            try:
                fn = _load(mod, attr)
                fn(console)
            except KeyboardInterrupt:
                console.print("[dim]stopped.[/]")
            except ModuleNotFoundError as exc:
                console.print(Panel(
                    f"[red]{exc}[/]\n\n"
                    "[dim]That's a missing Python package. Try:\n"
                    "    pip install -r requirements.txt[/]",
                    border_style="red", title="[red]missing library[/]",
                ))
            except Exception as exc:
                console.print(Panel(f"[red]oops:[/] {exc}", border_style="red"))
            break


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="sdr-kid",
        description=(
            "SDR Kid — a Software Defined Radio playground.\n"
            "Turn a $25 USB dongle into a plane tracker, weather-satellite "
            "receiver, radio scanner and spectrum analyzer."
        ),
        epilog=(
            "Run without arguments to open the interactive menu.\n"
            "Pass --list for a printed mode reference, --help for this text."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--skip-dongle", action="store_true",
                   help="don't probe the RTL-SDR at startup (use for online-only "
                        "modes, or when dump1090 / AIS-catcher already owns it)")
    p.add_argument("--list", action="store_true",
                   help="print a table of every mode SDR Kid ships with, then exit")
    p.add_argument("--doctor", action="store_true",
                   help="run a health check — Python packages, external tools, "
                        "dongle, ports, disk — and print exactly what's missing")
    p.add_argument("--test-audio", action="store_true",
                   help="play a 1-second beep through SoX to prove your speakers "
                        "and driver are wired up (independent of the dongle)")
    p.add_argument("--version", action="version", version=f"sdr-kid {__version__}")
    return p.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    from rich.console import Console
    console = Console()

    if args.list:
        _cli_help(console)
        return 0

    if args.doctor:
        from sdr_kid.doctor import render, run_all
        console.print("[cyan]running health check…[/]")
        results = run_all()
        render(console, results)
        return 0 if not any(r.status == "fail" for r in results) else 1

    if args.test_audio:
        import subprocess
        from sdr_kid.deps import SOX, which
        if which("sox") is None:
            from rich.panel import Panel
            from sdr_kid.deps import require
            console.print(Panel(require(SOX), border_style="red",
                                title="[red]SoX missing[/]"))
            return 1
        cmd = [which("sox"), "-n"]
        if sys.platform == "win32":
            cmd += ["-t", "waveaudio", "default"]
        elif sys.platform == "darwin":
            cmd += ["-t", "coreaudio", "default"]
        else:
            cmd += ["-d"]
        cmd += ["synth", "1", "sine", "440"]
        console.print(f"[dim]running: {' '.join(cmd)}[/]")
        console.print("[cyan]:speaker: playing a 1-second 440 Hz tone…[/]")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception as exc:
            console.print(f"[red]sox crashed: {exc}[/]")
            return 1
        if r.returncode != 0:
            from rich.panel import Panel
            console.print(Panel(
                (r.stderr or r.stdout or "unknown error").strip() +
                "\n\n[dim]If SoX says 'no default audio device configured', your SoX "
                "build is too old. Reinstall from sourceforge.net/projects/sox.[/]",
                title="[red]SoX rejected the request[/]", border_style="red"))
            return 1
        console.print("[green]:thumbsup: SoX + your speakers work. FM and ATC will play.[/]")
        return 0

    from rich.panel import Panel
    from sdr_kid.banner import render_banner
    from sdr_kid.dongle import probe, show_dongle_card, wait_for_dongle

    render_banner(console)

    if args.skip_dongle:
        console.print("[yellow]--skip-dongle: not checking the dongle.[/]")
    else:
        info = probe()
        if not info.present:
            info = wait_for_dongle(console, timeout=8.0)
        if info.present:
            show_dongle_card(console, info)
        else:
            reason = (info.reason or "").lower()
            probably_busy = any(k in reason for k in (
                "busy", "in use", "resource", "usb_open error", "-3", "-6",
            ))
            hint = (
                "[dim]Looks like another program owns the dongle "
                "(AIS-catcher, rtl_ais, dump1090, SDR#…).[/]\n"
                "[dim]That's fine — pick a mode that reads from its UDP/TCP feed.[/]"
                if probably_busy else
                "[dim]No dongle found yet. Online-only modes (planes/world, ISS map, "
                "logbook, quests) still work.[/]"
            )
            console.print(Panel(
                f"[yellow]dongle probe:[/] {info.reason}\n\n{hint}\n\n"
                "[dim]Tip: pass [bold]--skip-dongle[/] to silence this next time.[/]",
                border_style="yellow",
                title="[yellow]continuing without direct dongle access[/]",
            ))

    _menu(console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

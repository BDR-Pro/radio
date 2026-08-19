from __future__ import annotations

import time

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sdr_kid import progress as achievements
from sdr_kid.modes._audio import AudioChain


PRESETS = [
    ("101.5 MHz", 101_500_000),
    ("102.0 MHz", 102_000_000),
    ("104.7 MHz", 104_700_000),
    ("88.9 MHz",  88_900_000),
    ("94.7 MHz",  94_700_000),
    ("98.1 MHz",  98_100_000),
]


def _pick_freq(console: Console) -> int | None:
    choices = [f"{name}" for name, _ in PRESETS] + ["Custom frequency (MHz)", "Cancel"]
    ans = questionary.select("Pick an FM station:", choices=choices).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom frequency (MHz)":
        raw = questionary.text("Frequency in MHz (e.g. 103.3):").ask()
        if not raw:
            return None
        try:
            return int(float(raw) * 1_000_000)
        except ValueError:
            console.print("[red]Not a number.[/]")
            return None
    for name, hz in PRESETS:
        if name == ans:
            return hz
    return None


def _now_playing_panel(freq_hz: int, started: float) -> Panel:
    mhz = freq_hz / 1_000_000
    elapsed = int(time.time() - started)
    table = Table.grid(padding=(0, 2))
    table.add_row("[cyan]station[/]", f"[bold white]{mhz:.1f} MHz FM[/]")
    table.add_row("[cyan]mode[/]", "wide-band FM (music)")
    table.add_row("[cyan]listening for[/]", f"{elapsed // 60}m {elapsed % 60}s")
    tip = Text(
        "\nTip: broadcast FM sits between 87.5 and 108 MHz.\n"
        "Each station is 200 kHz wide — that's the width you 'zoom in' to.",
        style="dim italic",
    )
    return Panel.fit(
        Table.grid().add_row(table) or table,
        title="[magenta]:musical_note: now playing[/]",
        border_style="magenta",
        subtitle="[dim]Ctrl+C to stop[/]",
    )


def run(console: Console) -> None:
    freq = _pick_freq(console)
    if freq is None:
        return
    chain = AudioChain(freq_hz=freq, mode="wbfm", sample_rate=200_000)
    problem = chain.check()
    if problem:
        console.print(Panel(f"[red]{problem}[/]", title="[red]cannot play audio[/]"))
        return
    chain.start()
    console.print(f"[dim]pipeline: {chain.command_preview()}[/]")
    started = time.time()
    achievements.celebrate(console, achievements.record("fm_played"))
    try:
        with Live(_now_playing_panel(freq, started), console=console, refresh_per_second=2) as live:
            while True:
                time.sleep(0.5)
                live.update(_now_playing_panel(freq, started))
                if not chain.alive():
                    live.stop()
                    diag = chain.diagnose() or "the audio pipeline died silently."
                    console.print(Panel(
                        diag + "\n\n[dim]Try the command above by hand in PowerShell "
                        "to see the raw error.[/]",
                        title="[red]FM stopped[/]", border_style="red",
                    ))
                    break
    except KeyboardInterrupt:
        pass
    finally:
        chain.stop()
        console.print("[dim]stopped.[/]")

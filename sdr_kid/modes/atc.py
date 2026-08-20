from __future__ import annotations

import time

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid import progress as achievements
from sdr_kid.modes._audio import AudioChain


# "You'll almost certainly need to enter your LOCAL airport frequency to hear
# anything — aviation VHF is line-of-sight (~100 km max). The presets below
# are famous airports for reference, not because you'll hear them from home."
WORLD_PRESETS = [
    ("KJFK  New York JFK Tower",       119_100_000),
    ("KJFK  New York JFK Approach",    127_400_000),
    ("KLAX  Los Angeles Tower",        133_900_000),
    ("EGLL  London Heathrow Tower",    118_500_000),
    ("EHAM  Amsterdam Schiphol Tower", 118_275_000),
    ("KATL  Atlanta Tower",            119_100_000),
    ("KSFO  San Francisco Tower",      120_500_000),
    ("OERK  Riyadh King Khalid Tower", 118_700_000),
    ("OMDB  Dubai Tower",              118_750_000),
]
WORLDWIDE = [
    ("Guard (worldwide emergency) 121.500", 121_500_000),
    ("Unicom (small airports)     122.800", 122_800_000),
    ("Air-to-air chat             123.450", 123_450_000),
]


INTRO = (
    "[bold green]This uses your radio, not the internet.[/]\n\n"
    "Air Traffic Control transmits in [bold]AM[/] between 118 and 137 MHz —\n"
    "the same slice of spectrum your dongle just tuned. That's real audio\n"
    "arriving at your antenna at the speed of light.\n\n"
    "[yellow]Important:[/] aviation VHF is [bold]line-of-sight[/] — about 100 km\n"
    "max, less with obstacles. If you pick a preset for a far-away airport\n"
    "you'll hear silence. To actually hear planes:\n\n"
    "  1. Find your [bold]nearest[/] airport.\n"
    "  2. Look up its Tower / Approach / Ground frequencies at\n"
    "     [cyan]https://airnav.com/airports/[/] (US) or\n"
    "     [cyan]https://www.airfrequencies.co.uk/[/] (UK/EU) or\n"
    "     [cyan]https://liveatc.net[/] (worldwide list).\n"
    "  3. Pick [bold]Custom frequency[/] below and type it in as MHz."
)


def _pick_freq(console: Console) -> int | None:
    console.print(Panel(INTRO, title="[green]:airplane: air traffic control[/]",
                        border_style="green"))
    labels = (
        ["Custom frequency (your local airport)"] +
        [n for n, _ in WORLDWIDE] +
        [f"[preset] {n}" for n, _ in WORLD_PRESETS] +
        ["Cancel"]
    )
    ans = questionary.select("Which ATC channel?", choices=labels).ask()
    if not ans or ans == "Cancel":
        return None
    if ans.startswith("Custom"):
        raw = questionary.text(
            "Frequency in MHz (aviation is 118.000 – 137.000):"
        ).ask()
        if not raw:
            return None
        try:
            return int(float(raw) * 1_000_000)
        except ValueError:
            console.print("[red]not a number[/]")
            return None
    for name, hz in WORLDWIDE + WORLD_PRESETS:
        if name in ans:
            return hz
    return None


def _panel(freq_hz: int, label: str, started: float) -> Panel:
    mhz = freq_hz / 1_000_000
    dt = int(time.time() - started)
    table = Table.grid(padding=(0, 2))
    table.add_row("[cyan]channel[/]",   f"[bold]{label}[/]")
    table.add_row("[cyan]frequency[/]", f"{mhz:.3f} MHz [bold]AM[/]")
    table.add_row("[cyan]source[/]",    "[green]your antenna → RTL-SDR dongle → this terminal[/]")
    table.add_row("[cyan]listening[/]", f"{dt // 60}m {dt % 60}s")
    return Panel.fit(
        table,
        title="[green]:airplane: air traffic control — LIVE FROM YOUR ANTENNA[/]",
        border_style="green",
        subtitle="[dim]silence = no plane talking right now (normal). Ctrl+C to stop.[/]",
    )


def run(console: Console) -> None:
    freq = _pick_freq(console)
    if freq is None:
        return
    label = next((name for name, hz in WORLDWIDE + WORLD_PRESETS if hz == freq),
                 f"{freq/1e6:.3f} MHz")
    chain = AudioChain(freq_hz=freq, mode="am", sample_rate=12_000, squelch=100)
    problem = chain.check()
    if problem:
        console.print(Panel(f"[red]{problem}[/]", title="[red]cannot play audio[/]"))
        return
    chain.start()
    console.print(f"[dim]pipeline: {chain.command_preview()}[/]")
    started = time.time()
    achievements.celebrate(console, achievements.record("atc_played"))
    try:
        with Live(_panel(freq, label, started), console=console, refresh_per_second=2) as live:
            while True:
                time.sleep(0.5)
                live.update(_panel(freq, label, started))
                if not chain.alive():
                    live.stop()
                    diag = chain.diagnose() or "the audio pipeline died silently."
                    console.print(Panel(
                        diag + "\n\n[dim]Try the pipeline above by hand to see the raw error.[/]",
                        title="[red]ATC stopped[/]", border_style="red",
                    ))
                    break
    except KeyboardInterrupt:
        pass
    finally:
        chain.stop()
        console.print("[dim]stopped.[/]")

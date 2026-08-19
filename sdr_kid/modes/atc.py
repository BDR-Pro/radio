from __future__ import annotations

import time

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid.modes._audio import AudioChain


AIRPORTS = [
    ("KJFK  New York JFK Tower",       119_100_000),
    ("KJFK  New York JFK Approach",    127_400_000),
    ("KLAX  Los Angeles Tower",        133_900_000),
    ("EGLL  London Heathrow Tower",    118_500_000),
    ("EHAM  Amsterdam Schiphol Tower", 118_275_000),
    ("KATL  Atlanta Tower",            119_100_000),
    ("KSFO  San Francisco Tower",      120_500_000),
    ("Guard (emergency) 121.5",        121_500_000),
    ("Unicom (small airports) 122.8",  122_800_000),
]


def _pick_freq() -> int | None:
    labels = [name for name, _ in AIRPORTS] + ["Custom frequency (MHz)", "Cancel"]
    ans = questionary.select("Choose an ATC channel:", choices=labels).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom frequency (MHz)":
        raw = questionary.text("Frequency in MHz (aviation is 118-137):").ask()
        if not raw:
            return None
        try:
            return int(float(raw) * 1_000_000)
        except ValueError:
            return None
    for name, hz in AIRPORTS:
        if name == ans:
            return hz
    return None


def _panel(freq_hz: int, label: str, started: float) -> Panel:
    mhz = freq_hz / 1_000_000
    dt = int(time.time() - started)
    table = Table.grid(padding=(0, 2))
    table.add_row("[cyan]channel[/]", f"[bold]{label}[/]")
    table.add_row("[cyan]frequency[/]", f"{mhz:.3f} MHz AM")
    table.add_row("[cyan]listening[/]", f"{dt // 60}m {dt % 60}s")
    return Panel.fit(
        table,
        title="[green]:airplane: air traffic control[/]",
        border_style="green",
        subtitle="[dim]aviation uses AM, not FM. Ctrl+C to stop.[/]",
    )


def run(console: Console) -> None:
    freq = _pick_freq()
    if freq is None:
        return
    label = next((name for name, hz in AIRPORTS if hz == freq), f"{freq/1e6:.3f} MHz")
    chain = AudioChain(freq_hz=freq, mode="am", sample_rate=12_000, squelch=100)
    problem = chain.check()
    if problem:
        console.print(Panel(f"[red]{problem}[/]", title="[red]cannot play audio[/]"))
        return
    chain.start()
    started = time.time()
    try:
        with Live(_panel(freq, label, started), console=console, refresh_per_second=2) as live:
            while True:
                time.sleep(0.5)
                live.update(_panel(freq, label, started))
    except KeyboardInterrupt:
        pass
    finally:
        chain.stop()
        console.print("[dim]stopped.[/]")

from __future__ import annotations

import time
from typing import List, Optional

import numpy as np
import questionary
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


BANDS = [
    ("FM broadcast (music)",         88_000_000, 108_000_000),
    ("Aviation VHF (planes)",       118_000_000, 137_000_000),
    ("VHF ham / satellites",        144_000_000, 148_000_000),
    ("Marine VHF (ships)",          156_000_000, 162_000_000),
    ("Weather satellites (NOAA)",   137_000_000, 138_000_000),
    ("Pagers / POCSAG",             138_000_000, 144_000_000),
    ("Airband ACARS",               131_000_000, 132_000_000),
    ("PMR446 (walkie talkies EU)",  446_000_000, 446_200_000),
    ("70cm ham",                    430_000_000, 440_000_000),
    ("ADS-B (planes)",             1_090_000_000, 1_090_500_000),
]


BAR_CHARS = " ▁▂▃▄▅▆▇█"


def _pick_band() -> Optional[tuple[str, int, int]]:
    labels = [f"{n}  ({lo/1e6:.1f}-{hi/1e6:.1f} MHz)" for n, lo, hi in BANDS]
    ans = questionary.select(
        "Which slice of the radio sky?",
        choices=labels + ["Custom range", "Cancel"],
    ).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom range":
        lo = questionary.text("Low MHz:").ask()
        hi = questionary.text("High MHz:").ask()
        try:
            return (f"{lo}-{hi} MHz", int(float(lo) * 1e6), int(float(hi) * 1e6))
        except (TypeError, ValueError):
            return None
    idx = labels.index(ans)
    return BANDS[idx]


def _sample_power(sdr, center_hz: int, samples: int = 256 * 1024) -> float:
    sdr.center_freq = center_hz
    iq = sdr.read_samples(samples)
    p = float(np.mean(np.abs(iq) ** 2))
    return 10.0 * np.log10(p + 1e-12)


def _render(name: str, lo: int, hi: int, powers: List[float], freqs: List[int]) -> Panel:
    if not powers:
        return Panel(f"scanning {name}…", border_style="magenta")
    pmin, pmax = min(powers), max(powers)
    span = max(pmax - pmin, 1.0)
    width = 60
    step = max(1, len(powers) // width)
    bar_lines: List[Text] = []
    for i in range(0, len(powers), step):
        chunk = powers[i:i + step]
        norm = (sum(chunk) / len(chunk) - pmin) / span
        idx = min(len(BAR_CHARS) - 1, int(norm * (len(BAR_CHARS) - 1)))
        f_mhz = freqs[i] / 1e6
        color = "green" if norm < 0.35 else ("yellow" if norm < 0.7 else "red")
        line = Text.assemble(
            (f"{f_mhz:8.2f} MHz  ", "dim"),
            (BAR_CHARS[idx] * 40, color),
            (f"  {(sum(chunk)/len(chunk)):+6.1f} dB", "dim"),
        )
        bar_lines.append(line)
    return Panel(
        Group(*bar_lines),
        title=f"[magenta]:mag: RF explorer — {name}[/]",
        border_style="magenta",
        subtitle=f"[dim]{lo/1e6:.2f}-{hi/1e6:.2f} MHz • Ctrl+C to stop[/]",
    )


def run(console: Console) -> None:
    picked = _pick_band()
    if picked is None:
        return
    name, lo, hi = picked
    try:
        from rtlsdr import RtlSdr  # type: ignore
    except Exception as exc:
        console.print(Panel(f"[red]pyrtlsdr not usable ({exc})[/]"))
        return
    try:
        sdr = RtlSdr()
    except Exception as exc:
        console.print(Panel(f"[red]could not open dongle: {exc}[/]"))
        return
    try:
        sdr.sample_rate = 2.048e6
        sdr.gain = "auto"
        step = int(sdr.sample_rate * 0.9)
        freqs = list(range(lo + step // 2, hi, step))
        if not freqs:
            freqs = [(lo + hi) // 2]
        powers: List[float] = []
        console.print(
            Panel(
                "Green = quiet, yellow = something's talking, red = loud transmitter.\n"
                "This is a [bold]spectrum sweep[/] — the dongle hops across the band "
                "measuring how much energy is in each slice.",
                title="[magenta]:sparkles: what you're looking at[/]",
                border_style="magenta",
            )
        )
        with Live(_render(name, lo, hi, powers, freqs), console=console, refresh_per_second=4) as live:
            while True:
                powers = []
                for f in freqs:
                    powers.append(_sample_power(sdr, f))
                    live.update(_render(name, lo, hi, powers, freqs[:len(powers)]))
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sdr.close()
        except Exception:
            pass
        console.print("[dim]stopped.[/]")

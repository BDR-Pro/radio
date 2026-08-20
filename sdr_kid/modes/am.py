"""AM broadcast — medium wave + shortwave.

RTL-SDR tunes 24 MHz and up in its normal mode, so medium-wave AM (0.53–1.7 MHz)
and shortwave (3–30 MHz) live BELOW the tuner. There are two escape hatches:

  * Direct sampling (Q-branch): rtl_fm's `-D 2` flag routes the sample stream
    around the tuner. Works on RTL-SDR Blog v3 and any dongle where pin 4 of
    the RTL2832U is exposed. Sensitivity is much worse than an upconverter,
    but it costs nothing and works for strong nearby stations.
  * Upconverter (Ham-It-Up, SpyVerter, etc.): shifts 0–30 MHz up by 125 MHz,
    into the tuner's normal range. Best quality.

This mode drives rtl_fm with `-M am -D 2` by default so beginners get
something without extra hardware. If they have an upconverter, they enter
the shifted frequency instead.
"""
from __future__ import annotations

import time

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from sdr_kid import progress as achievements
from sdr_kid.modes._audio import AudioChain


# ---------------------------------------------------------------------------
# Presets — kilohertz. Sorted by band.
# ---------------------------------------------------------------------------

MEDIUM_WAVE = [   # local news / talk in most countries; strongest near sunset
    ("BBC Radio 4  UK          198 kHz LW", 198_000),
    ("Radio Monte Carlo  216 kHz LW",       216_000),
    ("WABC New York (talk)     770 kHz MW", 770_000),
    ("BBC World Service London 648 kHz MW", 648_000),
    ("KFI Los Angeles          640 kHz MW", 640_000),
]

SHORTWAVE_BROADCAST = [   # active on/near these carriers; time-of-day matters
    ("BBC World Service (SW English)     6195 kHz", 6_195_000),
    ("BBC World Service                  9410 kHz", 9_410_000),
    ("Radio Romania International       15130 kHz", 15_130_000),
    ("Voice of Turkey                    9700 kHz",  9_700_000),
    ("Radio China International         13710 kHz", 13_710_000),
    ("Radio Havana Cuba                  6000 kHz",  6_000_000),
    ("Radio New Zealand International    9700 kHz",  9_700_000),
    ("WWV time signal (Colorado)         5000 kHz",  5_000_000),
    ("WWV time signal                   10000 kHz", 10_000_000),
    ("WWV time signal                   15000 kHz", 15_000_000),
]


INTRO = """[bold green]This uses your radio, not the internet.[/]

AM broadcast lives in two bands:

  [bold]Medium Wave (MW):[/]  530 – 1700 kHz   — car AM radio, local talk
  [bold]Long  Wave (LW):[/]   150 –  280 kHz   — UK / Europe
  [bold]Short Wave (SW):[/]     3 –   30 MHz   — international broadcasters
                                                (BBC, WWV time signal, etc.)

Your RTL-SDR dongle normally tunes 24 MHz and up. To hear AM broadcast
you need ONE of these:

  1. [yellow]Direct-sampling mode[/] — works on the [bold]RTL-SDR Blog v3[/]
     out of the box. Cheaper, works for strong nearby stations, but signals
     are quieter. SDR Kid tries this by default (rtl_fm's `-D 2`).
  2. [yellow]Upconverter[/] (Ham-It-Up, SpyVerter, ~$50) — shifts 0–30 MHz
     up into the tuner's normal range. Much better sensitivity. If you
     have one, tell SDR Kid its offset (usually 125 MHz).

[bold]Best time to listen:[/]
  * MW / LW: after sunset and before sunrise (skywave propagation).
  * SW: broadcasters are strongest at specific hours per band — check
    [cyan]https://short-wave.info[/] for a live schedule."""


def _pick_setup(console: Console) -> tuple[int, int] | None:
    """Returns (freq_hz_of_signal, offset_hz_to_add). offset > 0 = upconverter."""
    console.print(Panel(INTRO, title="[green]:radio: AM broadcast[/]", border_style="green"))
    upconv = questionary.select(
        "Do you have an upconverter?",
        choices=[
            "No — try direct sampling (RTL-SDR v3 or similar)",
            "Yes — Ham-It-Up / SpyVerter (+125 MHz)",
            "Yes — custom offset",
            "Cancel",
        ],
    ).ask()
    if not upconv or upconv == "Cancel":
        return None
    if upconv.startswith("No"):
        offset = 0
    elif upconv.startswith("Yes — Ham"):
        offset = 125_000_000
    else:
        raw = questionary.text("Offset in MHz (positive number):").ask()
        try:
            offset = int(float(raw) * 1_000_000)
        except (TypeError, ValueError):
            console.print("[red]not a number[/]")
            return None

    labels = (
        [f"MW  · {n}" for n, _ in MEDIUM_WAVE] +
        [f"SW  · {n}" for n, _ in SHORTWAVE_BROADCAST] +
        ["Custom frequency (kHz)", "Cancel"]
    )
    ans = questionary.select("Pick a station:", choices=labels).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom frequency (kHz)":
        raw = questionary.text("Frequency in kHz (e.g. 640 for 640 kHz AM):").ask()
        try:
            hz = int(float(raw) * 1_000)
        except (TypeError, ValueError):
            console.print("[red]not a number[/]")
            return None
    else:
        matched = None
        for lst in (MEDIUM_WAVE, SHORTWAVE_BROADCAST):
            for name, hz_val in lst:
                if name in ans:
                    matched = hz_val
                    break
            if matched:
                break
        if matched is None:
            return None
        hz = matched
    return hz, offset


def _panel(signal_hz: int, tune_hz: int, mode_label: str, started: float) -> Panel:
    dt = int(time.time() - started)
    band = ("Long Wave"  if signal_hz < 300_000  else
            "Medium Wave" if signal_hz < 2_000_000 else
            "Short Wave"  if signal_hz < 30_000_000 else "VHF")
    table = Table.grid(padding=(0, 2))
    table.add_row("[cyan]station[/]",  f"[bold]{signal_hz/1000:,.0f} kHz {band} AM[/]")
    table.add_row("[cyan]dongle tuned to[/]", f"{tune_hz/1e6:.4f} MHz  [dim]({mode_label})[/]")
    table.add_row("[cyan]source[/]",   "[green]your antenna → RTL-SDR dongle → this terminal[/]")
    table.add_row("[cyan]listening[/]", f"{dt // 60}m {dt % 60}s")
    return Panel.fit(
        table,
        title="[magenta]:radio: AM broadcast — LIVE FROM YOUR ANTENNA[/]",
        border_style="magenta",
        subtitle="[dim]hiss = you're between stations, or the band is quiet. Ctrl+C to stop.[/]",
    )


def run(console: Console) -> None:
    picked = _pick_setup(console)
    if picked is None:
        return
    signal_hz, offset_hz = picked
    tune_hz = signal_hz + offset_hz
    mode_label = "upconverter" if offset_hz else "direct sampling"

    chain = AudioChain(
        freq_hz=tune_hz,
        mode="am",
        sample_rate=12_000,
        squelch=0,
        # rtl_fm needs -D 2 (Q-branch direct sampling) when no upconverter,
        # AudioChain doesn't know about that yet — patch in via extra args:
    )
    # Post-process the command to inject `-D 2` before the trailing `-`.
    # This is intentional: keeping _rtl_cmd() dumb keeps the shared audio
    # pipeline simple; only AM broadcast needs direct-sampling.
    if offset_hz == 0:
        original = chain._rtl_cmd
        def with_direct_sampling():
            cmd = original()
            return cmd[:-1] + ["-D", "2", "-"]
        chain._rtl_cmd = with_direct_sampling  # type: ignore

    problem = chain.check()
    if problem:
        console.print(Panel(f"[red]{problem}[/]", title="[red]cannot play audio[/]"))
        return
    chain.start()
    console.print(f"[dim]pipeline: {chain.command_preview()}[/]")
    started = time.time()
    achievements.celebrate(console, achievements.record("am_played"))
    try:
        with Live(_panel(signal_hz, tune_hz, mode_label, started),
                  console=console, refresh_per_second=2) as live:
            while True:
                time.sleep(0.5)
                live.update(_panel(signal_hz, tune_hz, mode_label, started))
                if not chain.alive():
                    live.stop()
                    diag = chain.diagnose() or "the audio pipeline died silently."
                    hint = (
                        "\n\n[dim]If rtl_fm complained about direct sampling, your dongle "
                        "may not expose the Q-branch pin. Options: buy an RTL-SDR Blog v3, "
                        "or an upconverter, or pick a VHF/UHF mode (FM, ATC, ISS) instead.[/]"
                        if offset_hz == 0 else ""
                    )
                    console.print(Panel(diag + hint,
                                        title="[red]AM stopped[/]", border_style="red"))
                    break
    except KeyboardInterrupt:
        pass
    finally:
        chain.stop()
        console.print("[dim]stopped.[/]")

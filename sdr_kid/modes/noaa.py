"""NOAA APT weather-satellite decoder.

Flow:
  1. Predict the next NOAA-15/18/19 pass overhead.
  2. Wait for rise (or record immediately if one is already up).
  3. Tune rtl_fm to the sat's downlink at wide-band FM and dump a WAV.
  4. When the pass ends, invoke `noaa-apt` on the WAV to produce a PNG.
  5. Copy the PNG into static/ so it shows up on the FastAPI dashboard.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from sdr_kid import progress as achievements
from sdr_kid.alerts import next_passes
from sdr_kid.location import ask as ask_home
from sdr_kid.server import STATIC_DIR, get_server


DOWNLINK_HZ = {
    "NOAA 15": 137_620_000,
    "NOAA 18": 137_912_500,
    "NOAA 19": 137_100_000,
}


def _check_tools() -> Optional[str]:
    from sdr_kid.deps import RTL_FM, SOX, NOAA_APT, require
    return require(RTL_FM, SOX, NOAA_APT)


def _record(freq_hz: int, seconds: int, out_wav: Path, console: Console) -> None:
    """rtl_fm -> sox pipe writing a 11025 Hz mono WAV suitable for noaa-apt."""
    console.print(f"[cyan]recording {seconds}s of {freq_hz/1e6:.4f} MHz FM → {out_wav.name}[/]")
    rtl = subprocess.Popen(
        [
            "rtl_fm",
            "-f", str(freq_hz),
            "-M", "fm",
            "-s", "60k",
            "-A", "fast",
            "-r", "11025",
            "-l", "0",
            "-E", "deemp",
            "-g", "48",
            "-",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    sox = subprocess.Popen(
        [
            "sox", "-t", "raw", "-r", "11025", "-e", "signed", "-b", "16", "-c", "1",
            "-", str(out_wav), "rate", "11025",
        ],
        stdin=rtl.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if rtl.stdout is not None:
        rtl.stdout.close()

    end = time.time() + seconds
    with Progress(
        TextColumn("[cyan]receiving…"),
        BarColumn(), TimeRemainingColumn(),
        console=console, transient=True,
    ) as prog:
        task = prog.add_task("rx", total=seconds)
        while time.time() < end:
            prog.update(task, completed=seconds - max(0, end - time.time()))
            time.sleep(0.5)
    for p in (sox, rtl):
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try: p.kill()
            except Exception: pass


def _decode(wav: Path, png: Path, console: Console) -> bool:
    console.print(f"[cyan]decoding {wav.name} → {png.name}[/]")
    try:
        r = subprocess.run(
            ["noaa-apt", "-o", str(png), str(wav)],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        console.print(f"[red]noaa-apt failed: {exc}[/]")
        return False
    if r.returncode != 0:
        console.print(Panel(r.stderr.strip() or "unknown error", title="[red]noaa-apt error[/]", border_style="red"))
        return False
    return png.exists()


def _publish_png(png: Path) -> Path:
    """Copy the image into static/ and write an HTML wrapper card for the dashboard."""
    dest = STATIC_DIR / png.name
    if png != dest:
        dest.write_bytes(png.read_bytes())
    html = STATIC_DIR / "noaa.html"
    html.write_text(f"""<!doctype html><meta charset=utf-8>
<title>NOAA APT image</title>
<style>body{{background:#0b1020;color:#e7ecff;font-family:sans-serif;margin:0;padding:24px;text-align:center}}
img{{max-width:100%;height:auto;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,.5)}}
h1{{margin:0 0 12px}}p{{color:#98a3c9}}</style>
<h1>Latest NOAA APT image</h1>
<p>received by your radio — {png.name}</p>
<img src="/image/{png.name}" alt="NOAA APT">""")
    return dest


def _pick_upcoming(passes) -> Optional[object]:
    noaa = [p for p in passes if p.sat in DOWNLINK_HZ]
    if not noaa:
        return None
    choices = []
    for p in noaa[:5]:
        local = p.rise_utc.astimezone()
        dur = int((p.set_utc - p.rise_utc).total_seconds() // 60)
        choices.append(f"{p.sat}  rises {local.strftime('%a %H:%M')}  "
                       f"peak {p.peak_elev_deg:.0f}°  ~{dur} min")
    choices.append("cancel")
    ans = questionary.select("which pass should we catch?", choices=choices).ask()
    if not ans or ans == "cancel":
        return None
    idx = choices.index(ans)
    return noaa[idx]


def _passes_table(passes) -> Table:
    t = Table(title=":satellite: upcoming NOAA passes", border_style="cyan", header_style="bold cyan")
    for col in ("satellite", "rise (local)", "duration", "peak elev"):
        t.add_column(col)
    for p in passes:
        if p.sat not in DOWNLINK_HZ:
            continue
        t.add_row(p.sat,
                  p.rise_utc.astimezone().strftime("%a %H:%M"),
                  f"{int((p.set_utc - p.rise_utc).total_seconds()//60)} min",
                  f"{p.peak_elev_deg:.0f}°")
    return t


def run(console: Console) -> None:
    problem = _check_tools()
    if problem:
        console.print(Panel(
            f"[red]{problem}[/]\n\n"
            "You need [bold]rtl_fm[/] (for tuning), [bold]sox[/] (for the WAV), and "
            "[bold]noaa-apt[/] (for turning audio into an image).",
            title="[red]missing tool[/]", border_style="red",
        ))
        return

    home = ask_home(console)
    if home is None:
        return
    lat, lon = home

    console.print("[cyan]looking up next NOAA passes…[/]")
    try:
        passes = next_passes(lat, lon, hours=12, sats=list(DOWNLINK_HZ.keys()), min_elev=15.0)
    except Exception as exc:
        console.print(Panel(f"[red]could not fetch TLEs: {exc}[/]"))
        return
    if not any(p.sat in DOWNLINK_HZ for p in passes):
        console.print(Panel(
            "No visible NOAA pass in the next 12 hours above 15°.\n"
            "Try again later, or lower the elevation cutoff.",
            title="[yellow]nothing overhead[/]", border_style="yellow",
        ))
        return
    console.print(_passes_table(passes))
    p = _pick_upcoming(passes)
    if p is None:
        return

    freq = DOWNLINK_HZ[p.sat]
    now = datetime.now(timezone.utc)
    wait_s = max(0, int((p.rise_utc - now).total_seconds()))
    duration = int((p.set_utc - p.rise_utc).total_seconds())

    if wait_s > 60:
        console.print(f"[cyan]waiting {wait_s // 60} min until {p.sat} rises…[/]")
        deadline = time.time() + wait_s
        try:
            with Live(Panel("waiting for the satellite…"), console=console, refresh_per_second=1) as live:
                while time.time() < deadline:
                    remaining = int(deadline - time.time())
                    live.update(Panel(
                        f"[bold yellow]{p.sat}[/] rises in "
                        f"[bold]{remaining // 60} min {remaining % 60:02d} s[/]\n"
                        f"peak elevation this pass: {p.peak_elev_deg:.0f}°",
                        title="[yellow]standing by[/]", border_style="yellow",
                    ))
                    time.sleep(1)
        except KeyboardInterrupt:
            console.print("[dim]cancelled.[/]")
            return

    STATIC_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    wav = STATIC_DIR / f"noaa-{p.sat.replace(' ', '')}-{stamp}.wav"
    png = STATIC_DIR / f"noaa-{p.sat.replace(' ', '')}-{stamp}.png"

    try:
        _record(freq, duration, wav, console)
    except KeyboardInterrupt:
        console.print("[dim]recording interrupted, still trying to decode what we got…[/]")

    if not wav.exists() or wav.stat().st_size < 1024:
        console.print(Panel("recording is empty — nothing to decode.", title="[red]no signal[/]", border_style="red"))
        return

    ok = _decode(wav, png, console)
    if not ok:
        return
    published = _publish_png(png)
    server = get_server()
    console.print(Panel(
        f"[green]saved:[/] {published}\n"
        f"[green]dashboard:[/] {server.url}/view/noaa.html",
        title="[green]:artificial_satellite: image ready[/]", border_style="green",
    ))
    achievements.celebrate(console, achievements.record("noaa_decoded"))

"""IQ record & replay — save raw samples to disk, feed them back later."""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

import numpy as np
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from sdr_kid import progress as achievements


IQ_DIR = Path.home() / "sdr_kid_recordings"
IQ_DIR.mkdir(exist_ok=True)

MAGIC = b"SDRK"
HEADER = struct.Struct("<4sIQQd")  # magic, version, center_hz, sample_rate, timestamp


@dataclass
class Recording:
    path: Path
    center_hz: int
    sample_rate: int
    started_at: float
    samples: int

    @property
    def duration_s(self) -> float:
        return self.samples / max(self.sample_rate, 1)


def _write_header(f, center_hz: int, sample_rate: int) -> None:
    f.write(HEADER.pack(MAGIC, 1, int(center_hz), int(sample_rate), time.time()))


def _read_header(f) -> tuple:
    magic, version, center, rate, ts = HEADER.unpack(f.read(HEADER.size))
    if magic != MAGIC:
        raise ValueError("not an SDR Kid IQ file")
    return center, rate, ts


def record(center_hz: int, sample_rate: int, seconds: int, path: Path, console: Console) -> Recording:
    from rtlsdr import RtlSdr  # type: ignore
    sdr = RtlSdr()
    sdr.sample_rate = sample_rate
    sdr.center_freq = center_hz
    sdr.gain = "auto"
    chunk = 262_144
    total_samples = int(sample_rate * seconds)
    written = 0
    with path.open("wb") as f:
        _write_header(f, center_hz, sample_rate)
        with Progress(
            TextColumn(f"[cyan]recording {center_hz/1e6:.3f} MHz to {path.name}"),
            BarColumn(), TimeElapsedColumn(),
            console=console, transient=True,
        ) as prog:
            task = prog.add_task("rx", total=total_samples)
            while written < total_samples:
                n = min(chunk, total_samples - written)
                iq = sdr.read_samples(n)
                # store as int8 I/Q interleaved (RTL native format, 2x smaller than float32)
                bytes_ = np.stack([np.real(iq), np.imag(iq)], axis=1).reshape(-1)
                bytes_ = np.clip(bytes_ * 127, -128, 127).astype(np.int8)
                f.write(bytes_.tobytes())
                written += n
                prog.update(task, completed=written)
    sdr.close()
    return Recording(path, center_hz, sample_rate, time.time(), written)


def open_recording(path: Path) -> Recording:
    with path.open("rb") as f:
        center, rate, ts = _read_header(f)
        rest = path.stat().st_size - HEADER.size
        samples = rest // 2
    return Recording(path, center, rate, ts, samples)


def iterate_samples(path: Path, chunk: int = 262_144) -> Iterator[np.ndarray]:
    with path.open("rb") as f:
        _read_header(f)
        while True:
            raw = f.read(chunk * 2)
            if not raw:
                return
            arr = np.frombuffer(raw, dtype=np.int8).astype(np.float32) / 127.0
            arr = arr.reshape(-1, 2)
            yield arr[:, 0] + 1j * arr[:, 1]


def list_recordings() -> List[Recording]:
    out: List[Recording] = []
    for p in sorted(IQ_DIR.glob("*.iq")):
        try:
            out.append(open_recording(p))
        except Exception:
            continue
    return out


def _table(recs: List[Recording]) -> Table:
    t = Table(title=":floppy_disk: saved recordings", border_style="magenta", header_style="bold magenta")
    for c in ("name", "center MHz", "sample rate", "duration", "size"):
        t.add_column(c)
    if not recs:
        t.add_row("—", "—", "—", "—", "—")
    for r in recs:
        size_mb = r.path.stat().st_size / 1e6
        t.add_row(r.path.name, f"{r.center_hz/1e6:.3f}",
                  f"{r.sample_rate/1e6:.2f} MS/s", f"{r.duration_s:.1f} s",
                  f"{size_mb:.1f} MB")
    return t


def _do_record(console: Console) -> None:
    freq_mhz = questionary.text("center frequency in MHz (e.g. 100.3):").ask()
    dur      = questionary.text("record for how many seconds?", default="10").ask()
    rate_mhz = questionary.text("sample rate in MS/s (default 2.048):", default="2.048").ask()
    try:
        center = int(float(freq_mhz) * 1e6)
        seconds = max(1, int(float(dur)))
        rate    = int(float(rate_mhz) * 1e6)
    except (TypeError, ValueError):
        console.print("[red]bad number[/]")
        return
    from datetime import datetime
    name = f"{center//1000000}MHz-{datetime.now().strftime('%Y%m%d-%H%M%S')}.iq"
    path = IQ_DIR / name
    try:
        rec = record(center, rate, seconds, path, console)
    except Exception as exc:
        console.print(Panel(f"[red]record failed: {exc}[/]"))
        return
    console.print(Panel(
        f"[green]saved:[/] {rec.path}\n"
        f"{rec.samples:,} samples • {rec.duration_s:.1f} s • "
        f"{rec.path.stat().st_size/1e6:.1f} MB",
        title="[green]:floppy_disk: recording done[/]", border_style="green",
    ))
    achievements.celebrate(console, achievements.record("iq_recorded"))


def _spectrum_of(iq: np.ndarray, bins: int = 64) -> List[float]:
    from numpy.fft import fft, fftshift
    win = np.hanning(len(iq))
    spec = np.abs(fftshift(fft(iq * win)))
    step = max(1, len(spec) // bins)
    return [float(20 * np.log10(spec[i:i + step].mean() + 1e-9)) for i in range(0, len(spec), step)][:bins]


def _do_playback(console: Console, path: Path) -> None:
    """Cheap-and-cheerful playback: show a live spectrum bar for each chunk."""
    from rich.live import Live
    from sdr_kid.modes._spectrum import color_for, normalize

    rec = open_recording(path)
    console.print(Panel(
        f"[cyan]playing back {rec.path.name}[/]\n"
        f"center {rec.center_hz/1e6:.3f} MHz  •  {rec.sample_rate/1e6:.2f} MS/s  •  "
        f"{rec.duration_s:.1f} s of audio",
        title="[magenta]:play_button: replay[/]", border_style="magenta",
    ))
    chunk = int(rec.sample_rate // 10)  # ~10 fps
    try:
        from rich.text import Text
        with Live(console=console, refresh_per_second=10) as live:
            for iq in iterate_samples(path, chunk=chunk):
                if len(iq) < 64:
                    continue
                spec = _spectrum_of(iq, bins=64)
                norms = normalize(spec)
                bar = Text()
                for n in norms:
                    bar.append("█", style=color_for(n))
                live.update(Panel(bar,
                    title=f"[magenta]{rec.center_hz/1e6:.3f} MHz replay[/]",
                    subtitle="[dim]Ctrl+C to stop[/]",
                    border_style="magenta"))
                time.sleep(1 / 20)
    except KeyboardInterrupt:
        console.print("[dim]stopped.[/]")


def run(console: Console) -> None:
    while True:
        recs = list_recordings()
        console.print(_table(recs))
        ans = questionary.select("what next?", choices=[
            "Record new IQ",
            "Play back a recording (spectrum view)",
            "Back",
        ]).ask()
        if not ans or ans == "Back":
            return
        if ans.startswith("Record"):
            _do_record(console)
        else:
            if not recs:
                console.print("[dim]no recordings yet[/]")
                continue
            pick = questionary.select("which one?", choices=[r.path.name for r in recs] + ["Cancel"]).ask()
            if not pick or pick == "Cancel":
                continue
            _do_playback(console, IQ_DIR / pick)

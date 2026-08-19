from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn


@dataclass
class DongleInfo:
    present: bool
    name: str = ""
    tuner: str = ""
    serial: str = ""
    reason: str = ""


def _detect_via_rtl_test() -> DongleInfo:
    from sdr_kid.deps import which as _which
    exe = _which("rtl_test")
    if not exe:
        return DongleInfo(False, reason="rtl_test not on PATH")
    # `-s 250000 -n 4096` reads a tiny sample (~15ms) instead of the default
    # 5-second stress test that plain `-t` runs.
    try:
        proc = subprocess.run(
            [exe, "-s", "250000", "-n", "4096"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return DongleInfo(False, reason="rtl_test timed out")
    output = (proc.stderr or "") + (proc.stdout or "")
    if "No supported devices found" in output or "usb_open error" in output:
        return DongleInfo(False, reason="no supported devices found")
    name = ""
    tuner = ""
    serial = ""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("0:") and "SN:" in line:
            parts = line.split(",")
            name = parts[1].strip() if len(parts) > 1 else "RTL-SDR"
            sn = line.split("SN:")[-1].strip()
            serial = sn
        if line.startswith("Found Rafael") or "tuner" in line.lower():
            tuner = line
    return DongleInfo(True, name=name or "RTL-SDR", tuner=tuner, serial=serial)


def _detect_via_pyrtlsdr() -> DongleInfo:
    try:
        from rtlsdr import RtlSdr  # type: ignore
    except Exception as exc:
        return DongleInfo(False, reason=f"pyrtlsdr not usable ({exc})")
    try:
        sdr = RtlSdr()
    except Exception as exc:
        return DongleInfo(False, reason=str(exc))
    try:
        info = DongleInfo(
            True,
            name="RTL-SDR",
            tuner=getattr(sdr, "get_tuner_type", lambda: "")() or "",
        )
    finally:
        try:
            sdr.close()
        except Exception:
            pass
    return info


def probe() -> DongleInfo:
    info = _detect_via_rtl_test()
    if info.present:
        return info
    return _detect_via_pyrtlsdr()


def wait_for_dongle(console: Console, timeout: float = 8.0) -> DongleInfo:
    """Poll for the dongle for up to `timeout` seconds. Silent unless it
    takes more than one probe."""
    deadline = time.time() + timeout
    first = probe()
    if first.present or timeout <= 0:
        return first
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[cyan]waiting for dongle (Ctrl+C to skip)…"),
        transient=True,
        console=console,
    ) as prog:
        prog.add_task("probing")
        while time.time() < deadline:
            time.sleep(1.0)
            info = probe()
            if info.present:
                return info
    return first  # keep original reason for the caller's error message


def show_dongle_card(console: Console, info: DongleInfo) -> None:
    body = (
        f"[bold green]{info.name}[/]\n"
        f"tuner  : {info.tuner or 'unknown'}\n"
        f"serial : {info.serial or 'n/a'}\n\n"
        "[dim]this little USB stick can hear anywhere from about 24 MHz to 1.7 GHz.[/]"
    )
    console.print(Panel(body, title="[green]:radio: dongle ready[/]", border_style="green"))

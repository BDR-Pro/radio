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
    exe = shutil.which("rtl_test")
    if not exe:
        return DongleInfo(False, reason="rtl_test not installed")
    try:
        proc = subprocess.run(
            [exe, "-t"],
            capture_output=True,
            text=True,
            timeout=6,
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


def wait_for_dongle(console: Console, timeout: float = 120.0) -> DongleInfo:
    console.print(
        Panel(
            "[bold]Plug in your SDR dongle now[/]\n\n"
            "1. Push the USB dongle into the computer.\n"
            "2. Screw the antenna onto the little gold connector.\n"
            "3. Point the antenna up — sky = better signal.\n\n"
            "[dim]We'll keep looking for the dongle for up to 2 minutes.[/]",
            title="[cyan]:satellite_antenna: Connect your radio[/]",
            border_style="cyan",
        )
    )
    deadline = time.time() + timeout
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[cyan]looking for dongle... {task.description}"),
        transient=True,
        console=console,
    ) as prog:
        task = prog.add_task("probing")
        while time.time() < deadline:
            info = probe()
            if info.present:
                prog.update(task, description="[green]found![/]")
                return info
            prog.update(task, description="not yet — plug it in and press USB firmly")
            time.sleep(1.5)
    return DongleInfo(False, reason="timed out waiting for dongle")


def show_dongle_card(console: Console, info: DongleInfo) -> None:
    body = (
        f"[bold green]{info.name}[/]\n"
        f"tuner  : {info.tuner or 'unknown'}\n"
        f"serial : {info.serial or 'n/a'}\n\n"
        "[dim]this little USB stick can hear anywhere from about 24 MHz to 1.7 GHz.[/]"
    )
    console.print(Panel(body, title="[green]:radio: dongle ready[/]", border_style="green"))

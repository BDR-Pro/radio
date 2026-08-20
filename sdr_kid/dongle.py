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


_KNOWN_TUNERS = (
    "R820T", "R820T2", "E4000", "FC0012", "FC0013",
    "FC2580", "R828D",
)


def _parse_rtl_test(output: str) -> tuple[str, str, str]:
    """Extract (name, tuner, serial) from any rtl_test dump."""
    name = tuner = serial = ""
    for line in output.splitlines():
        line = line.strip()
        # "  0:  Nooelec, NESDR SMArt v5, SN: 93163378"
        if line.startswith("0:") and "SN:" in line:
            body = line[2:].strip()          # strip "0:" prefix
            parts = [p.strip() for p in body.split(",")]
            # Model = everything BETWEEN vendor and "SN:"
            model_parts = [p for p in parts if not p.startswith("SN:")]
            name = ", ".join(model_parts) if model_parts else "RTL-SDR"
            for p in parts:
                if p.startswith("SN:"):
                    serial = p.split(":", 1)[1].strip()
        # "Found Rafael Micro R820T tuner" — the ONLY canonical tuner line
        if line.startswith("Found ") and line.endswith(" tuner"):
            tuner = line[len("Found "):-len(" tuner")]
        # Fallback: look for known tuner names anywhere in real output lines
        elif not tuner:
            for k in _KNOWN_TUNERS:
                if k in line and "-t" not in line and "benchmark" not in line.lower():
                    tuner = k
                    break
    return name, tuner, serial


def _detect_via_rtl_test() -> DongleInfo:
    from sdr_kid.deps import which as _which
    exe = _which("rtl_test")
    if not exe:
        return DongleInfo(False, reason="rtl_test not on PATH")
    # Run rtl_test with no args; kill it as soon as we see the device line.
    # The default `-t` invocation triggers a 5-second stress test we don't need.
    try:
        proc = subprocess.Popen(
            [exe],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 3.0
        chunks: list = []
        assert proc.stdout is not None
        # rtl_test prints device info within the first ~200 ms of startup.
        while time.time() < deadline:
            time.sleep(0.15)
            # non-blocking read
            proc.stdout.flush()
            data = ""
            try:
                data = proc.stdout.read(4096) or ""
            except Exception:
                data = ""
            if data:
                chunks.append(data)
            joined = "".join(chunks)
            if "Found" in joined and "tuner" in joined:
                break
            if "No supported devices" in joined:
                break
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try: proc.kill()
            except Exception: pass
        output = "".join(chunks)
    except Exception as exc:
        return DongleInfo(False, reason=f"rtl_test crashed: {exc}")

    if "No supported devices found" in output or "usb_open error" in output:
        return DongleInfo(False, reason="no supported devices found")
    if not output:
        return DongleInfo(False, reason="rtl_test returned nothing")
    name, tuner, serial = _parse_rtl_test(output)
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

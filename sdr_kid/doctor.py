"""Doctor: a full health-check of SDR Kid's environment.

Runs a series of independent probes and prints a table saying which
ones passed, which failed, and what to do about the failures. Each
probe is a plain function returning a Check, so tests can exercise them
in isolation.
"""
from __future__ import annotations

import importlib
import platform
import socket
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sdr_kid import deps


PASS = "pass"
FAIL = "fail"
SKIP = "skip"
WARN = "warn"

BADGE = {
    PASS: "[green]✔ pass[/]",
    WARN: "[yellow]! warn[/]",
    FAIL: "[red]✘ fail[/]",
    SKIP: "[dim]· skip[/]",
}


@dataclass
class Check:
    name: str
    status: str                        # PASS / FAIL / WARN / SKIP
    detail: str = ""
    fix: str = ""


# --- individual checks ------------------------------------------------------


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 10):
        return Check("Python ≥ 3.10", PASS, f"{sys.version.split()[0]} on {platform.system()}")
    return Check("Python ≥ 3.10", FAIL,
                 f"you're on {sys.version.split()[0]}",
                 "install Python 3.10 or newer from python.org")


PY_PACKAGES = [
    ("rich",         "prettify the terminal"),
    ("textual",      "run the RF spectrum waterfall"),
    ("questionary",  "the arrow-key menus"),
    ("pyfiglet",     "the ASCII banner"),
    ("fastapi",      "serve the map + live-spectrum website"),
    ("uvicorn",      "the web server itself"),
    ("folium",       "the interactive maps"),
    ("httpx",        "talk to OpenSky / open-notify"),
    ("numpy",        "spectrum math"),
    ("skyfield",     "predict satellite passes"),
    ("pyais",        "decode ship AIS sentences"),
    ("websockets",   "stream spectrum to the browser"),
]


def check_python_packages() -> List[Check]:
    results: List[Check] = []
    for pkg, why in PY_PACKAGES:
        try:
            importlib.import_module(pkg)
            results.append(Check(f"python: {pkg}", PASS, why))
        except Exception as exc:
            results.append(Check(
                f"python: {pkg}", FAIL, f"{why} — {exc.__class__.__name__}",
                "pip install -r requirements.txt",
            ))
    # pyrtlsdr is separate: presence isn't strictly required (some flows
    # use rtl_fm.exe instead), so degrade to WARN.
    try:
        importlib.import_module("rtlsdr")
        results.append(Check("python: pyrtlsdr", PASS,
                             "read raw IQ samples in Python"))
    except Exception:
        results.append(Check(
            "python: pyrtlsdr", WARN,
            "raw IQ modes (record, live waterfall) won't work",
            "pip install pyrtlsdr  (and install librtlsdr system-wide)",
        ))
    return results


def check_external_tools() -> List[Check]:
    tools = [
        (deps.RTL_TEST,  True,  "probe the dongle"),
        (deps.RTL_FM,    True,  "listen to FM / ATC / NOAA"),
        (deps.SOX,       True,  "play audio"),
        (deps.RTL_AIS,   False, "run the ship tracker"),
        (deps.DUMP1090,  False, "run the airplane tracker on your antenna"),
        (deps.NOAA_APT,  False, "decode weather-satellite images"),
    ]
    results = []
    os_name = deps.current_os()
    for tool, required, why in tools:
        if deps.which(tool.name) or deps.which(tool.name + ".exe"):
            results.append(Check(f"tool: {tool.name}", PASS, why))
        else:
            hint = tool.install.get(os_name, "").splitlines()[0] if tool.install else ""
            results.append(Check(
                f"tool: {tool.name}",
                FAIL if required else WARN,
                f"needed to {why}",
                hint,
            ))
    # Windows: AIS-catcher is a fine substitute for rtl_ais
    if os_name == "windows" and deps.which("AIS-catcher"):
        results.append(Check("tool: AIS-catcher", PASS,
                             "Windows-friendly AIS decoder is available"))
    return results


def check_dongle() -> Check:
    """Try to open the dongle briefly. WARN (not FAIL) if it's busy — that's
    normal when dump1090 or AIS-catcher is running."""
    from sdr_kid.dongle import probe
    info = probe()
    if info.present:
        return Check("dongle: RTL-SDR reachable", PASS,
                     f"{info.name or 'RTL-SDR'}  tuner={info.tuner or '?'}")
    reason = (info.reason or "").lower()
    busy = any(k in reason for k in ("busy", "in use", "usb_open error", "-3", "-6", "resource"))
    if busy:
        return Check("dongle: RTL-SDR reachable", WARN,
                     "in use by another program (dump1090 / AIS-catcher / SDR#)",
                     "that's fine — the mode reading its UDP feed will still work")
    return Check("dongle: RTL-SDR reachable", FAIL,
                 info.reason or "not detected",
                 "plug it in; on Linux run the udev/blacklist steps in README; "
                 "on Windows run Zadig and bind Bulk-In Interface 0 to WinUSB")


def check_port_free(port: int = 8000) -> Check:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError as exc:
        return Check(f"port {port}: free for web server", WARN, str(exc),
                     f"something else is on TCP {port} — kill it or SDR Kid "
                     f"will fail to start its map server")
    finally:
        s.close()
    return Check(f"port {port}: free for web server", PASS,
                 "SDR Kid can start the FastAPI map server here")


def check_tcp_reachable(name: str, host: str, port: int, why: str) -> Check:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except Exception as exc:
        return Check(f"{name}: {host}:{port} reachable", SKIP,
                     f"nothing listening (that's OK — start {name} when you want to use {why})",
                     "")
    return Check(f"{name}: {host}:{port} reachable", PASS,
                 f"live — {why} will work")


def check_udp_bindable(port: int = 10110) -> Check:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError as exc:
        return Check(f"UDP {port}: can bind", WARN,
                     f"can't bind — {exc}",
                     f"another process holds the port; ship tracker will fail")
    finally:
        s.close()
    return Check(f"UDP {port}: can bind", PASS,
                 "ship tracker will be able to listen for AIS")


def check_sqlite() -> Check:
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            path = tmp.name
        con = sqlite3.connect(path)
        con.executescript("CREATE TABLE t(x INT); INSERT INTO t VALUES(1);")
        assert con.execute("SELECT SUM(x) FROM t").fetchone()[0] == 1
        con.close()
        Path(path).unlink()
        return Check("sqlite: read/write", PASS, "logbook can persist plane sightings")
    except Exception as exc:
        return Check("sqlite: read/write", FAIL, str(exc),
                     "your Python was built without SQLite? reinstall from python.org")


def check_static_dir_writable() -> Check:
    from sdr_kid.server import STATIC_DIR
    try:
        STATIC_DIR.mkdir(exist_ok=True)
        marker = STATIC_DIR / ".doctor-write-check"
        marker.write_text("ok")
        marker.unlink()
    except Exception as exc:
        return Check("static/: writable", FAIL, str(exc),
                     f"the folder {STATIC_DIR} isn't writable by you")
    return Check("static/: writable", PASS, f"maps + NOAA images can be saved to {STATIC_DIR}")


def check_home_writable() -> Check:
    p = Path.home() / ".sdr_kid_doctor_check"
    try:
        p.write_text("ok"); p.unlink()
    except Exception as exc:
        return Check("$HOME: writable", FAIL, str(exc),
                     "SDR Kid saves quest progress, the logbook, and your location in $HOME")
    return Check("$HOME: writable", PASS, "quest / logbook / location files can be saved")


ALL_CHECKS: List[Callable] = [
    check_python,
    check_python_packages,
    check_external_tools,
    check_dongle,
    lambda: check_port_free(8000),
    lambda: check_tcp_reachable("dump1090", "127.0.0.1", 30003, "airplane tracker"),
    check_udp_bindable,
    check_sqlite,
    check_static_dir_writable,
    check_home_writable,
]


# --- runner + printer -------------------------------------------------------


def run_all() -> List[Check]:
    results: List[Check] = []
    for c in ALL_CHECKS:
        try:
            out = c()
        except Exception as exc:
            results.append(Check(getattr(c, "__name__", "check"),
                                 FAIL, f"crashed: {exc}"))
            continue
        if isinstance(out, list):
            results.extend(out)
        else:
            results.append(out)
    return results


def render(console: Console, results: List[Check]) -> None:
    counts = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    t = Table(
        title=":stethoscope: SDR Kid — health check",
        border_style="cyan", header_style="bold cyan",
        show_lines=False,
    )
    t.add_column("status")
    t.add_column("check", style="bold")
    t.add_column("detail", style="dim")
    for r in results:
        t.add_row(BADGE.get(r.status, r.status), r.name, r.detail)
    console.print(t)

    # Any FAIL rows: print the fix hints in one panel.
    fixes = [r for r in results if r.status == FAIL and r.fix]
    if fixes:
        body = "\n\n".join(
            f"[bold red]{r.name}[/]\n{r.detail}\n[green]→ {r.fix}[/]"
            for r in fixes
        )
        console.print(Panel(body, title="[red]what to fix[/]", border_style="red"))

    summary = (
        f"[green]{counts[PASS]} passed[/] · "
        f"[yellow]{counts[WARN]} warned[/] · "
        f"[red]{counts[FAIL]} failed[/] · "
        f"[dim]{counts[SKIP]} skipped[/]"
    )
    console.print(Panel(summary, border_style="cyan",
                        title=":thumbsup: green means go" if counts[FAIL] == 0
                              else ":wrench: fix the reds and re-run"))


def _from_menu(console: Console) -> None:
    """Menu entrypoint (declared in sdr_kid.app.MENU)."""
    render(console, run_all())


def main() -> int:
    console = Console()
    console.print("[cyan]running health check…[/]")
    started = time.time()
    results = run_all()
    render(console, results)
    console.print(f"[dim]({time.time() - started:.1f}s)[/]")
    return 0 if not any(r.status == FAIL for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

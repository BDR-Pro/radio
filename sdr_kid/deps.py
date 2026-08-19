"""OS-aware external-tool detection + install hints.

Every mode that shells out to a binary (rtl_fm, sox, noaa-apt, rtl_ais…)
should route its "is this installed?" check through this module so the
error message is tailored to the user's platform.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


def current_os() -> str:
    """Return one of 'windows', 'macos', 'linux', 'other'."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def which(name: str) -> Optional[str]:
    """shutil.which with a Windows `.exe` fallback."""
    p = shutil.which(name)
    if p:
        return p
    if current_os() == "windows" and not name.endswith(".exe"):
        return shutil.which(name + ".exe")
    return None


@dataclass
class Tool:
    """Description of an external binary we might need."""
    name: str
    what_for: str
    # per-OS install snippets — plain shell lines, no fancy formatting
    install: Dict[str, str]

    def check(self) -> Optional["MissingTool"]:
        if which(self.name) is not None:
            return None
        return MissingTool(tool=self, os=current_os())


@dataclass
class MissingTool:
    tool: Tool
    os: str

    def message(self) -> str:
        hint = self.tool.install.get(self.os) or self.tool.install.get("other") \
               or "install it from the tool's official site"
        return (
            f"[bold red]{self.tool.name}[/] not found on PATH — "
            f"needed to {self.tool.what_for}.\n\n"
            f"[bold]How to install (on {self.os}):[/]\n{hint}"
        )


# ---------------------------------------------------------------------------
# Concrete tool definitions used across SDR Kid.
# ---------------------------------------------------------------------------

RTL_FM = Tool(
    name="rtl_fm",
    what_for="tune the dongle and demodulate FM / AM audio",
    install={
        "linux":   "sudo apt install rtl-sdr           # or: sudo dnf install rtl-sdr",
        "macos":   "brew install rtl-sdr",
        "windows": ("1. Download the zip from https://ftp.osmocom.org/binaries/windows/rtl-sdr/\n"
                    "2. Unzip to e.g.  C:\\rtl-sdr\\\n"
                    "3. Add that folder to your PATH  (System → Environment Variables → Path → New)\n"
                    "4. Restart PowerShell and run:  rtl_test.exe -t   to confirm"),
    },
)

RTL_TEST = Tool(
    name="rtl_test",
    what_for="probe whether the RTL-SDR dongle is plugged in and healthy",
    install=RTL_FM.install,  # ships in the same package
)

SOX = Tool(
    name="sox",
    what_for="convert / play audio samples coming out of rtl_fm",
    install={
        "linux":   "sudo apt install sox",
        "macos":   "brew install sox",
        "windows": ("1. Grab the Windows installer from https://sourceforge.net/projects/sox/\n"
                    "2. Install it (default path is  C:\\Program Files (x86)\\sox-14-4-2\\ )\n"
                    "3. Add that folder to your PATH\n"
                    "4. Restart PowerShell and run:  sox --version"),
    },
)

APLAY = Tool(
    name="aplay",
    what_for="play audio via ALSA (Linux only)",
    install={"linux": "sudo apt install alsa-utils"},
)

RTL_AIS = Tool(
    name="rtl_ais",
    what_for="decode AIS ship transmissions into NMEA sentences",
    install={
        "linux":   ("sudo apt install rtl-ais       # if unavailable:\n"
                    "git clone https://github.com/dgiardini/rtl-ais && cd rtl-ais && make && sudo make install"),
        "macos":   "brew install rtl-ais",
        "windows": ("Two options:\n"
                    "  A) AIS-catcher (recommended)\n"
                    "     – https://github.com/jvde-github/AIS-catcher/releases\n"
                    "     – unzip and run:  .\\AIS-catcher.exe -u 127.0.0.1 10110\n"
                    "  B) rtl-ais Windows build\n"
                    "     – https://github.com/dgiardini/rtl-ais/releases (rtl-ais-win.zip)\n"
                    "     – unzip and run:  .\\rtl_ais.exe -h 127.0.0.1 -P 10110"),
    },
)

NOAA_APT = Tool(
    name="noaa-apt",
    what_for="turn NOAA satellite audio into an image",
    install={
        "linux":   ("Download the .deb from https://noaa-apt.mbernardi.com.ar/download.html\n"
                    "  sudo dpkg -i noaa-apt_*.deb"),
        "macos":   ("brew install noaa-apt              # or Rust:  cargo install noaa-apt"),
        "windows": ("1. Download noaa-apt_*_windows_gnu.zip from\n"
                    "   https://noaa-apt.mbernardi.com.ar/download.html\n"
                    "2. Unzip and add the folder to your PATH."),
    },
)

DUMP1090 = Tool(
    name="dump1090",
    what_for="decode ADS-B airplane transmissions locally",
    install={
        "linux":   "sudo apt install dump1090-mutability",
        "macos":   "brew install dump1090",
        "windows": ("Grab dump1090 from https://github.com/flightaware/dump1090/releases\n"
                    "(FlightAware builds Windows binaries)."),
    },
)


def require(*tools: Tool) -> Optional[str]:
    """Check a set of tools; return a Rich-friendly message if any are missing."""
    missing: List[MissingTool] = [m for m in (t.check() for t in tools) if m is not None]
    if not missing:
        return None
    parts = [m.message() for m in missing]
    if len(parts) == 1:
        return parts[0]
    return "\n\n---\n\n".join(parts)


def audio_player() -> Optional[Tool]:
    """Return the best available audio-player Tool, or None if the choice
    should just be resolved at command build time (both `sox` and `play`
    can render audio, we prefer `play` when present)."""
    for t in (SOX, APLAY):
        if t.check() is None:
            return t
    return None

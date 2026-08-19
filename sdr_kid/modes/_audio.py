from __future__ import annotations

import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

import tempfile
import time

from sdr_kid.deps import APLAY, RTL_FM, SOX, require, which


@dataclass
class AudioChain:
    """Encapsulates an rtl_fm -> player pipeline.

    Player selection (in order of preference):
      1. `play`   – the SoX shell wrapper (usually Linux/macOS)
      2. `sox - -d` – SoX itself, cross-platform (Windows: waveaudio,
                     macOS: coreaudio, Linux: alsa)
      3. `aplay`  – Linux/ALSA fallback
    """

    freq_hz: int
    mode: str = "wbfm"      # wbfm, nfm, am, usb, lsb
    sample_rate: int = 32000
    squelch: int = 0
    gain: str = "auto"

    _rtl: Optional[subprocess.Popen] = None
    _play: Optional[subprocess.Popen] = None
    _rtl_log: Optional[str] = None
    _play_log: Optional[str] = None

    def check(self) -> Optional[str]:
        msg = require(RTL_FM)
        if msg is not None:
            return msg
        # any of `play`, `sox`, `aplay` is enough for output
        if which("play") is None and SOX.check() is not None and APLAY.check() is not None:
            return require(SOX)  # SoX is the cross-platform recommendation
        return None

    def _rtl_cmd(self) -> List[str]:
        cmd = [
            which("rtl_fm") or "rtl_fm",
            "-M", self.mode,
            "-f", str(self.freq_hz),
            "-s", str(self.sample_rate),
            "-r", "48000",
        ]
        if self.gain and self.gain != "auto":
            cmd += ["-g", self.gain]
        if self.squelch:
            cmd += ["-l", str(self.squelch)]
        cmd += ["-"]
        return cmd

    def _player_cmd(self) -> List[str]:
        if which("play"):
            return [
                which("play"), "-q",
                "-r", "48000", "-t", "raw",
                "-e", "signed", "-b", "16", "-c", "1",
                "-",
            ]
        if which("sox"):
            return [
                which("sox"), "-q",
                "-r", "48000", "-t", "raw",
                "-e", "signed", "-b", "16", "-c", "1",
                "-",              # input from stdin
                "-d",             # output to default audio device
            ]
        return [
            which("aplay") or "aplay", "-q",
            "-r", "48000", "-f", "S16_LE", "-t", "raw", "-c", "1",
            "-",
        ]

    def start(self) -> None:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # Capture stderr to temp files so we can dump it when the pipe dies.
        self._rtl_log = tempfile.NamedTemporaryFile(
            "w+", suffix=".rtl_fm.log", delete=False).name
        self._play_log = tempfile.NamedTemporaryFile(
            "w+", suffix=".player.log", delete=False).name
        self._rtl = subprocess.Popen(
            self._rtl_cmd(),
            stdout=subprocess.PIPE,
            stderr=open(self._rtl_log, "w"),
            creationflags=creationflags,
        )
        self._play = subprocess.Popen(
            self._player_cmd(),
            stdin=self._rtl.stdout,
            stdout=subprocess.DEVNULL,
            stderr=open(self._play_log, "w"),
            creationflags=creationflags,
        )
        if self._rtl.stdout is not None:
            self._rtl.stdout.close()

    def command_preview(self) -> str:
        """Human-readable version of the pipeline, so users can debug by hand."""
        rtl = " ".join(self._rtl_cmd())
        ply = " ".join(self._player_cmd())
        return f"{rtl} | {ply}"

    def alive(self) -> bool:
        return (self._rtl is not None and self._rtl.poll() is None
                and self._play is not None and self._play.poll() is None)

    def diagnose(self) -> Optional[str]:
        """If either process died, return a diagnostic string (or None)."""
        rtl_dead  = self._rtl  is not None and self._rtl.poll()  is not None
        play_dead = self._play is not None and self._play.poll() is not None
        if not (rtl_dead or play_dead):
            return None
        parts: List[str] = []
        if rtl_dead:
            parts.append(f"[bold red]rtl_fm exited with code {self._rtl.returncode}[/]")
            if self._rtl_log:
                try:
                    text = open(self._rtl_log).read().strip()
                    if text:
                        parts.append(f"[red]rtl_fm said:[/]\n{text}")
                except Exception:
                    pass
        if play_dead:
            parts.append(f"[bold red]audio player exited with code {self._play.returncode}[/]")
            if self._play_log:
                try:
                    text = open(self._play_log).read().strip()
                    if text:
                        parts.append(f"[red]player said:[/]\n{text}")
                except Exception:
                    pass
        return "\n\n".join(parts)

    def stop(self) -> None:
        sig = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT
        for proc in (self._play, self._rtl):
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(sig)
                    proc.wait(timeout=1.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

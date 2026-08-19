from __future__ import annotations

import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

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
        self._rtl = subprocess.Popen(
            self._rtl_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._play = subprocess.Popen(
            self._player_cmd(),
            stdin=self._rtl.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if self._rtl.stdout is not None:
            self._rtl.stdout.close()

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

from __future__ import annotations

import shutil
import signal
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AudioChain:
    """Encapsulates an rtl_fm -> player pipeline."""

    freq_hz: int
    mode: str = "wbfm"  # wbfm, nfm, am, usb, lsb
    sample_rate: int = 32000
    squelch: int = 0
    gain: str = "auto"

    _rtl: Optional[subprocess.Popen] = None
    _play: Optional[subprocess.Popen] = None

    def check(self) -> Optional[str]:
        if shutil.which("rtl_fm") is None:
            return "rtl_fm not installed (apt-get install rtl-sdr)"
        if not any(shutil.which(x) for x in ("play", "aplay", "sox")):
            return "no audio player found (apt-get install sox alsa-utils)"
        return None

    def _rtl_cmd(self) -> List[str]:
        cmd = [
            "rtl_fm",
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
        if shutil.which("play"):
            return [
                "play", "-q",
                "-r", "48000",
                "-t", "raw",
                "-e", "signed",
                "-b", "16",
                "-c", "1",
                "-",
            ]
        return [
            "aplay", "-q",
            "-r", "48000",
            "-f", "S16_LE",
            "-t", "raw",
            "-c", "1",
            "-",
        ]

    def start(self) -> None:
        self._rtl = subprocess.Popen(
            self._rtl_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._play = subprocess.Popen(
            self._player_cmd(),
            stdin=self._rtl.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._rtl.stdout is not None:
            self._rtl.stdout.close()

    def stop(self) -> None:
        for proc in (self._play, self._rtl):
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=1.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

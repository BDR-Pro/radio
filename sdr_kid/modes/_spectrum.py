"""Shared spectrum-sweep primitive used by both the Rich bar chart and the Textual waterfall."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


BANDS: Sequence[Tuple[str, int, int]] = (
    ("FM broadcast",          88_000_000, 108_000_000),
    ("Aviation VHF",         118_000_000, 137_000_000),
    ("Weather sats (NOAA)",  137_000_000, 138_000_000),
    ("VHF ham / sats",       144_000_000, 148_000_000),
    ("Marine VHF",           156_000_000, 162_000_000),
    ("PMR446 (EU walkies)",  446_000_000, 446_200_000),
    ("70cm ham",             430_000_000, 440_000_000),
    ("ADS-B",              1_090_000_000, 1_090_500_000),
)


@dataclass
class Sweep:
    freqs_hz: List[int]
    powers_db: List[float]


def make_sdr():
    from rtlsdr import RtlSdr  # type: ignore
    sdr = RtlSdr()
    sdr.sample_rate = 2.048e6
    sdr.gain = "auto"
    return sdr


def sweep(sdr, lo_hz: int, hi_hz: int, samples_per_hop: int = 128 * 1024) -> Sweep:
    step = int(sdr.sample_rate * 0.9)
    freqs = list(range(lo_hz + step // 2, hi_hz, step))
    if not freqs:
        freqs = [(lo_hz + hi_hz) // 2]
    powers: List[float] = []
    for f in freqs:
        sdr.center_freq = f
        iq = sdr.read_samples(samples_per_hop)
        p = float(np.mean(np.abs(iq) ** 2))
        powers.append(10.0 * np.log10(p + 1e-12))
    return Sweep(freqs, powers)


def normalize(powers: Sequence[float]) -> List[float]:
    if not powers:
        return []
    lo, hi = min(powers), max(powers)
    span = max(hi - lo, 1.0)
    return [(p - lo) / span for p in powers]


COLOR_STOPS = [
    (0.0, (10, 20, 60)),
    (0.25, (30, 80, 200)),
    (0.5, (0, 200, 200)),
    (0.75, (255, 220, 60)),
    (1.0, (255, 60, 60)),
]


def color_for(norm: float) -> str:
    """Return a hex color for a normalized 0..1 power value."""
    n = max(0.0, min(1.0, norm))
    for i in range(1, len(COLOR_STOPS)):
        x1, c1 = COLOR_STOPS[i - 1]
        x2, c2 = COLOR_STOPS[i]
        if n <= x2:
            t = (n - x1) / max(x2 - x1, 1e-9)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#ffffff"

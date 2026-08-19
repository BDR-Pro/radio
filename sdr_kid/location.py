"""Shared 'where are you standing?' picker.

Persists the answer in ~/.sdr_kid_home.json so the kid doesn't have to
re-enter their city every time they open a mode that needs it (ISS
passes, NOAA passes, plane radius searches).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

import questionary
from rich.console import Console


HOME_FILE = Path.home() / ".sdr_kid_home.json"

PRESETS = {
    "Riyadh":   (24.7136,  46.6753),
    "Jeddah":   (21.4858,  39.1925),
    "London":   (51.5074,  -0.1278),
    "New York": (40.7128, -74.0060),
    "Tokyo":    (35.6762, 139.6503),
}


def remember(lat: float, lon: float) -> None:
    HOME_FILE.write_text(json.dumps({"lat": lat, "lon": lon}))


def recall() -> Optional[Tuple[float, float]]:
    if not HOME_FILE.exists():
        return None
    try:
        d = json.loads(HOME_FILE.read_text())
        return float(d["lat"]), float(d["lon"])
    except Exception:
        return None


def ask(console: Console, allow_saved: bool = True) -> Optional[Tuple[float, float]]:
    """Prompt the user, honouring the previously-saved location."""
    saved = recall() if allow_saved else None
    if saved:
        choice = questionary.select(
            f"use your saved location ({saved[0]:.2f}, {saved[1]:.2f})?",
            choices=["yes", "pick another", "cancel"],
        ).ask()
        if choice == "yes":
            return saved
        if choice in (None, "cancel"):
            return None
    picked = questionary.select(
        "where are you standing?",
        choices=list(PRESETS.keys()) + ["Custom coordinates", "Cancel"],
    ).ask()
    if not picked or picked == "Cancel":
        return None
    if picked == "Custom coordinates":
        lat = questionary.text("latitude:").ask()
        lon = questionary.text("longitude:").ask()
        try:
            home = (float(lat), float(lon))
        except (TypeError, ValueError):
            console.print("[red]that wasn't a number.[/]")
            return None
    else:
        home = PRESETS[picked]
    remember(*home)
    return home

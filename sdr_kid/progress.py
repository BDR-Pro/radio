"""Simple JSON-backed achievement tracker.

Modes call `record(event, **payload)`; the tracker unlocks matching quests
and returns the newly unlocked ones so the caller can celebrate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


PROGRESS_FILE = Path.home() / ".sdr_kid_progress.json"


@dataclass
class Quest:
    key: str
    title: str
    hint: str
    check: Callable[[dict], bool]


def _counter(event: str, target: int) -> Callable[[dict], bool]:
    return lambda state: state.get("counters", {}).get(event, 0) >= target


def _any(event: str) -> Callable[[dict], bool]:
    return lambda state: state.get("counters", {}).get(event, 0) >= 1


QUESTS: List[Quest] = [
    Quest("first_plane",   "First plane spotted",
          "See any aircraft in the plane tracker.",           _any("plane_seen")),
    Quest("five_planes",   "Five planes seen",
          "Log at least five distinct aircraft.",             _counter("plane_seen", 5)),
    Quest("fifty_planes",  "Fifty planes seen",
          "Log at least fifty distinct aircraft.",            _counter("plane_seen", 50)),
    Quest("iss_map",       "Located the ISS",
          "Open the live ISS map once.",                      _any("iss_map_opened")),
    Quest("iss_pass",      "Predicted an ISS pass",
          "Run the ISS 'next passes' report.",                _any("iss_pass_listed")),
    Quest("iss_tune",      "Tuned 145.800 MHz",
          "Point the radio at the astronaut voice channel.",  _any("iss_tuned")),
    Quest("fm_listen",     "Listened to FM",
          "Play any broadcast FM station.",                   _any("fm_played")),
    Quest("atc_listen",    "Eavesdropped on ATC",
          "Tune any aviation AM channel.",                    _any("atc_played")),
    Quest("first_ship",    "First ship decoded",
          "Receive at least one AIS sentence.",               _any("ship_seen")),
    Quest("spectrum_swept","Swept the RF spectrum",
          "Run the RF explorer on any band.",                 _any("spectrum_swept")),
    Quest("noaa_image",    "Decoded a weather satellite",
          "Produce one NOAA APT image.",                      _any("noaa_decoded")),
    Quest("iq_recorded",   "Saved raw radio",
          "Record any IQ sample file.",                       _any("iq_recorded")),
    Quest("watchlist_hit", "Watchlist alert triggered",
          "Have a callsign from your watchlist enter range.", _any("watchlist_hit")),
]


_lock = RLock()


def _load() -> dict:
    if not PROGRESS_FILE.exists():
        return {"counters": {}, "unlocked": []}
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except Exception:
        return {"counters": {}, "unlocked": []}


def _save(state: dict) -> None:
    PROGRESS_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def record(event: str, amount: int = 1) -> List[Quest]:
    """Bump an event counter and return newly unlocked quests."""
    with _lock:
        state = _load()
        counters = state.setdefault("counters", {})
        counters[event] = counters.get(event, 0) + amount
        unlocked = set(state.setdefault("unlocked", []))
        just_unlocked: List[Quest] = []
        for q in QUESTS:
            if q.key in unlocked:
                continue
            if q.check(state):
                unlocked.add(q.key)
                just_unlocked.append(q)
        state["unlocked"] = sorted(unlocked)
        _save(state)
    return just_unlocked


def summary_table() -> Table:
    state = _load()
    unlocked = set(state.get("unlocked", []))
    counters = state.get("counters", {})
    table = Table(
        title=":trophy: [bold]your SDR quests[/]",
        border_style="magenta",
        header_style="bold magenta",
    )
    table.add_column("", width=2)
    table.add_column("quest", style="bold white")
    table.add_column("how to earn it", style="dim")
    for q in QUESTS:
        icon = "[green]★[/]" if q.key in unlocked else "[dim]·[/]"
        table.add_row(icon, q.title, q.hint)
    done = len(unlocked)
    total = len(QUESTS)
    table.caption = f"{done}/{total} unlocked  •  events tracked: {sum(counters.values())}"
    return table


def celebrate(console: Console, unlocked: List[Quest]) -> None:
    if not unlocked:
        return
    body = "\n".join(f":sparkles:  [bold yellow]{q.title}[/] — {q.hint}" for q in unlocked)
    console.print(Panel(body, title="[yellow]:trophy: quest unlocked![/]", border_style="yellow"))

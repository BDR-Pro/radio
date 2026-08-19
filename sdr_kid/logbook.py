"""SQLite logbook for aircraft observations + a callsign watchlist."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List, Optional


DB_PATH = Path.home() / ".sdr_kid_logbook.sqlite"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    icao       TEXT NOT NULL,
    callsign   TEXT,
    country    TEXT,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    min_alt_m  REAL,
    max_alt_m  REAL,
    max_kt     REAL,
    hits       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (icao)
);
CREATE TABLE IF NOT EXISTS watchlist (
    pattern    TEXT NOT NULL PRIMARY KEY,   -- ICAO hex or callsign fragment (upper)
    note       TEXT,
    added_at   REAL NOT NULL
);
"""


@dataclass
class Sighting:
    icao: str
    callsign: Optional[str] = None
    country: Optional[str] = None
    alt_m: Optional[float] = None
    speed_kt: Optional[float] = None


_lock = RLock()


@contextmanager
def _conn():
    con = sqlite3.connect(str(DB_PATH))
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def record_batch(sightings: Iterable[Sighting]) -> int:
    """Insert or update rows for a sighting batch. Returns number of *new* aircraft."""
    now = time.time()
    new_count = 0
    with _lock, _conn() as con:
        for s in sightings:
            if not s.icao:
                continue
            row = con.execute("SELECT icao FROM observations WHERE icao = ?", (s.icao,)).fetchone()
            if row is None:
                new_count += 1
                con.execute(
                    "INSERT INTO observations "
                    "(icao, callsign, country, first_seen, last_seen, min_alt_m, max_alt_m, max_kt, hits) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (s.icao, s.callsign, s.country, now, now,
                     s.alt_m, s.alt_m, s.speed_kt),
                )
            else:
                con.execute(
                    "UPDATE observations SET "
                    " callsign  = COALESCE(NULLIF(?,''), callsign),"
                    " country   = COALESCE(NULLIF(?,''), country),"
                    " last_seen = ?,"
                    " min_alt_m = MIN(COALESCE(min_alt_m, ?), COALESCE(?, min_alt_m)),"
                    " max_alt_m = MAX(COALESCE(max_alt_m, ?), COALESCE(?, max_alt_m)),"
                    " max_kt    = MAX(COALESCE(max_kt, 0),   COALESCE(?, 0)),"
                    " hits      = hits + 1 "
                    "WHERE icao = ?",
                    (s.callsign or "", s.country or "", now,
                     s.alt_m, s.alt_m, s.alt_m, s.alt_m, s.speed_kt, s.icao),
                )
    return new_count


def stats() -> Dict[str, int]:
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(hits), 0), COALESCE(MAX(max_alt_m), 0) "
            "FROM observations"
        ).fetchone()
        return {
            "aircraft":  int(row[0] or 0),
            "sightings": int(row[1] or 0),
            "max_alt_m": int(row[2] or 0),
        }


def top(limit: int = 10) -> List[dict]:
    with _lock, _conn() as con:
        cur = con.execute(
            "SELECT icao, callsign, country, hits, max_alt_m, max_kt, first_seen, last_seen "
            "FROM observations ORDER BY last_seen DESC LIMIT ?", (limit,)
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def watchlist_add(pattern: str, note: str = "") -> None:
    with _lock, _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO watchlist (pattern, note, added_at) VALUES (?, ?, ?)",
            (pattern.strip().upper(), note, time.time()),
        )


def watchlist_remove(pattern: str) -> None:
    with _lock, _conn() as con:
        con.execute("DELETE FROM watchlist WHERE pattern = ?", (pattern.strip().upper(),))


def watchlist_all() -> List[dict]:
    with _lock, _conn() as con:
        cur = con.execute("SELECT pattern, note, added_at FROM watchlist ORDER BY added_at DESC")
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def watchlist_hits(sightings: Iterable[Sighting]) -> List[tuple]:
    """Return [(pattern, note, sighting)] for every matching sighting."""
    patterns = watchlist_all()
    if not patterns:
        return []
    hits: List[tuple] = []
    for s in sightings:
        haystack = f"{s.icao} {s.callsign or ''}".upper()
        for row in patterns:
            if row["pattern"] and row["pattern"] in haystack:
                hits.append((row["pattern"], row.get("note", ""), s))
    return hits

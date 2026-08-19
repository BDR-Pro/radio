# Notes for Claude working in this repo

> Read this before editing. It captures the shape of the codebase, non-obvious
> constraints, and how to test changes without radio hardware.

## What the project is

`sdr_kid` — a menu-driven CLI (Rich + Textual + questionary + FastAPI + folium)
that turns a USB RTL-SDR dongle into a playground for a young engineer. Every
"mode" is a small Python file under `sdr_kid/modes/` invoked from a top-level
menu in `sdr_kid/app.py`.

## Architecture at a glance

```
sdr_kid/
├── app.py            # top-level menu; MENU = [(label, run_fn), ...]
├── banner.py         # pyfiglet splash
├── dongle.py         # rtl_test / pyrtlsdr detection + wait wizard
├── server.py         # FastAPI + uvicorn (background thread) + SpectrumBus
│                     # Also owns MAP_META, the pretty landing page, /ws/spectrum,
│                     # and /live (browser waterfall).
├── progress.py       # JSON-backed quests + record(event) API + celebrate()
├── logbook.py        # SQLite aircraft logbook + watchlist_hits()
├── alerts.py         # Background overhead-pass service (skyfield + plyer)
├── static/           # Folium maps + NOAA images + live.html land here
└── modes/
    ├── _audio.py     # rtl_fm | sox pipeline (shared by fm.py & atc.py)
    ├── _spectrum.py  # DSP primitives (make_sdr, sweep, color_for, normalize)
    ├── fm.py         # Rich Live wrapper around AudioChain (wbfm)
    ├── atc.py        # Same, AM demod, aviation presets
    ├── planes.py     # OpenSky → folium map, feeds logbook + watchlist
    ├── ships.py      # UDP :10110 NMEA listener + pyais decode
    ├── iss.py        # skyfield passes / open-notify live pos / 145.800 MHz
    ├── explore.py    # Textual waterfall + Rich fallback; publishes to BUS
    ├── noaa.py       # rtl_fm record → noaa-apt decode → PNG in static/
    ├── iq.py         # Raw IQ record & replay (custom .iq format, int8 pairs)
    ├── alerts_ui.py  # UI wrapper around alerts.AlertService
    └── logbook_ui.py # Table + watchlist add/remove
```

### Cross-cutting glue

- **Every mode is `def run(console: Console) -> None`.** Adding a new mode is
  one new file + one line in `MENU` in `app.py`.
- **`sdr_kid.server.BUS`** — a `SpectrumBus` singleton. Any code that has a
  spectrum sweep can call `BUS.publish(freqs_hz, powers_db)` and the browser
  page at `/live` picks it up over WebSocket. `explore.py` is the only current
  publisher.
- **`sdr_kid.server.get_server()`** — starts uvicorn on 127.0.0.1:8000 in a
  daemon thread (idempotent). Call it before you generate a map or want the
  live page reachable.
- **`sdr_kid.server.write_static(name, html)`** — writes to `sdr_kid/static/`,
  which the landing page auto-lists via `MAP_META`.
- **`sdr_kid.progress.record(event, amount=1)`** — bumps a counter and returns
  newly-unlocked `Quest` objects. Pair with `progress.celebrate(console, ...)`.
- **`sdr_kid.logbook.record_batch([Sighting(...)])`** returns the number of
  *new* aircraft. `watchlist_hits(...)` returns `[(pattern, note, sighting)]`.

## Testing without hardware

The suite (in `tests/`) is designed to run with no dongle:

- `tests/conftest.py` stubs `rtlsdr` with a fake `RtlSdr` that returns
  random complex samples, and points every `~/.sdr_kid_*` file into a temp
  directory per test (`isolated_home` autouse fixture).
- Real subprocesses (`rtl_fm`, `sox`, `noaa-apt`) are only exercised in the
  live modes, never in tests — the tests cover the code paths *around* them.
- `test_server.py` boots a real uvicorn on a random port and speaks WebSocket
  against it (the TestClient's WS shim deadlocks under FastAPI lifespan;
  don't use it here).

Run it all:

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

## Non-obvious gotchas

1. **`webbrowser.open` in a sandbox will noisily fail.** All call sites are
   wrapped in `try/except Exception: pass`. If you add a new one, do the same.
2. **`pyais` decodes one *complete* AIS message at a time.** Multi-fragment
   sentences (types 5/24) MUST be reassembled before calling `decode(*frames)`.
   `AISListener._absorb` already handles this — study it before touching.
3. **The Textual explorer runs the SDR in a worker thread** and pushes results
   via `App.call_from_thread(self._absorb, sw)`. Never touch widget state
   from the SDR thread directly.
4. **FastAPI `lifespan` binds the `BUS`'s event loop.** If you call
   `BUS.publish` before the app has started, nothing happens (frames are
   dropped silently). Tests start uvicorn and sleep briefly to let it come up.
5. **The `.iq` file format is custom**: 24-byte header
   (`<4sIQQd` = magic `SDRK`, version, center Hz, sample rate, timestamp),
   then int8 interleaved I/Q. Half the size of float32; playback quality is
   equivalent since RTL-SDR's ADC is 8-bit anyway.
6. **`sdr_kid/static/` is committed with a `.gitkeep`.** Runtime files that
   land there (`planes.html`, `noaa-*.png`, `live.html`) are transient and
   generally shouldn't be committed.
7. **All external hosts may be blocked in a sandbox.** Do not assume network
   works during code review; test with fakes.

## Common commands

```bash
python -m sdr_kid                    # run the app
python -m sdr_kid --skip-dongle      # online-only modes (planes/ships/ISS)
python -m pytest -q                  # tests (fast, no hardware needed)
python -c "from sdr_kid.server import create_app; create_app()"  # smoke import
```

## Extension pointers (things you're likely asked to add)

- **New radio mode** → new file in `sdr_kid/modes/`, add `run(console)`, wire
  into `MENU`. Use `_audio.AudioChain` for demodulated voice, `_spectrum.sweep`
  for spectrum work, `get_server()` + `write_static()` for browser output.
- **New quest** → append a `Quest(...)` to `QUESTS` in `progress.py`, then
  call `progress.record("your_event")` from the mode.
- **New card on the landing page** → add an entry to `MAP_META` in `server.py`.
  Any HTML file dropped in `static/` shows up automatically.
- **New WebSocket stream** → add an endpoint next to `/ws/spectrum` in
  `create_app()` and follow the `SpectrumBus` pattern for thread-safe fan-out.

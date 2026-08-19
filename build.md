# How I built SDR Kid (with Python)

This is a tour of the project — the *why* behind each piece — so you can
change it, break it, and remake it yourself. Pair this with the source
files in `sdr_kid/`; nothing here is more than a hundred lines you can't
read in one sitting.

## The idea in one sentence

> The USB dongle turns radio waves into numbers. Python turns numbers into
> anything we want.

That's the whole trick of Software Defined Radio. Instead of a factory-made
box that only does FM, the RTL-SDR ships raw complex samples (I/Q data) to
the computer, and *software* decides whether those samples become music,
plane positions, or a spectrum picture.

## The libraries I picked and why

| Library         | Why it's here                                                        |
|-----------------|----------------------------------------------------------------------|
| `rich`          | Colored panels, tables, live updating text in the terminal.          |
| `textual`       | Reserved for future full-screen dashboards (spectrum waterfall).     |
| `questionary`   | Arrow-key menus that a kid can use without reading docs.             |
| `pyfiglet`      | Big ASCII banner — first impressions matter.                         |
| `pyrtlsdr`      | Python bindings to the C driver `librtlsdr` — talk to the dongle.    |
| `numpy` / `scipy` | Do FFTs and power measurements on the I/Q samples.                 |
| `fastapi` + `uvicorn` | Tiny web server that serves the live maps.                    |
| `folium`        | Renders Leaflet.js maps from Python — no JS to write.                |
| `httpx`         | Pulls plane data (OpenSky), ship data (AIS feeds), ISS position.     |
| `skyfield`      | Real satellite orbital math — predicts when the ISS will fly over.   |

Everything is pip-installable and pure Python except `pyrtlsdr`, which
needs the C library `librtlsdr` (installed via `apt` / `brew`).

## Project layout

```
radio/
├── README.md            <- install + play instructions
├── build.md             <- (you are here)
├── requirements.txt     <- pinned minimums so pip installs cleanly
├── pyproject.toml       <- makes the project pip-installable
└── sdr_kid/
    ├── __main__.py      <- lets `python -m sdr_kid` work
    ├── app.py           <- top-level menu loop
    ├── banner.py        <- ASCII splash
    ├── dongle.py        <- detect and describe the USB dongle
    ├── server.py        <- background FastAPI server for maps
    ├── static/          <- generated HTML maps live here
    └── modes/
        ├── _audio.py    <- shared rtl_fm → sox pipeline
        ├── fm.py        <- FM broadcast
        ├── atc.py       <- AM aviation voice
        ├── planes.py    <- ADS-B via OpenSky
        ├── ships.py     <- AIS ship feed
        ├── iss.py       <- ISS position, passes, 145.800 MHz
        └── explore.py   <- spectrum sweep with pyrtlsdr + numpy
```

## Design decisions

### 1. Menu-first, not command-line-flag-first

A kid opens `python -m sdr_kid`, sees a big banner, sees a menu, presses
Enter. No `--freq 101500000 --mode wbfm` to memorize. `questionary` gives
arrow-key menus in ten lines of code.

### 2. Detect the dongle before anything else

`dongle.py` tries two ways:

1. `rtl_test -t` (fast, uses the installed C tool)
2. `pyrtlsdr.RtlSdr()` fallback (Python-only path)

A friendly panel tells the kid what to plug in, spins for two minutes, and
either celebrates or explains why the dongle isn't visible. A `--skip-dongle`
flag lets online-only modes still work.

### 3. Audio modes share one pipeline

FM broadcast and ATC both boil down to *"tune → demodulate → play"*.
Rather than duplicate that in two files, `modes/_audio.py` wraps
`rtl_fm` (from the `rtl-sdr` package) piped into `sox`'s `play` (or
`aplay` as a fallback). It's ~90 lines and handles both modes by changing
one `-M` flag (`wbfm` vs `am`).

```python
chain = AudioChain(freq_hz=101_500_000, mode="wbfm", sample_rate=200_000)
chain.start()  # spawns two subprocesses linked by a Unix pipe
```

Rich's `Live` display then shows a friendly "now playing" panel that updates
each second, and `Ctrl+C` cleanly kills both subprocesses.

### 4. Maps are HTML files, served from a background FastAPI

Rendering a folium `Map` returns HTML. Instead of writing it to disk and
telling the kid to double-click, `server.py` runs a `uvicorn` server in a
background thread on `127.0.0.1:8000` and any mode that produces a map
just calls `write_static("planes.html", html)`. The first time a mode
writes a map it also fires `webbrowser.open(...)` so the map pops up
automatically.

Because uvicorn runs in a daemon thread, when the Python process exits the
server dies with it — no cleanup needed.

### 5. Real data over the internet where it makes sense

`planes.py` and `ships.py` prefer public APIs (OpenSky Network, AIS mirrors)
because a beginner without an antenna on their roof won't get plane hits
from the dongle alone. The README explains how to become a *real* ADS-B or
AIS receiver later — that's the aspirational goal.

### 6. The RF explorer is the one that *really* uses the dongle

`modes/explore.py` opens the SDR with `pyrtlsdr`, hops the center frequency
across a chosen band (e.g. 88–108 MHz), reads a few thousand I/Q samples at
each step, computes `10·log10(mean(|iq|²))` — a power estimate in dB — and
paints it as a colored bar chart in the terminal using Rich. Green = quiet,
yellow = busy, red = loud transmitter. That single loop is the essence of a
spectrum analyzer, and it's about 30 lines of Python.

### 7. ISS mode combines *math* and *radio*

`modes/iss.py` shows two things you can only really appreciate together:

- **Prediction** — `skyfield` loads the ISS's TLE (a two-line orbital
  element set) from Celestrak, then uses your latitude/longitude to compute
  when the station will next rise above 10° elevation. That's real
  astrodynamics running in your terminal.
- **Reception** — the astronauts' voice/SSTV downlink is on 145.800 MHz
  FM. When the ISS is above the horizon, pointing your antenna up and
  tuning there might catch actual astronaut voice or SSTV image tones.

The live world map (updated every 5s) uses `open-notify.org`'s tiny JSON
API so you don't need TLE math just to know where the station is *right now*.

### 8. No global state, no framework lock-in

Every mode is a plain function `run(console)`. The main menu is a `for`
loop over `[(label, run_fn), ...]`. Adding your own mode is:

```python
# sdr_kid/modes/pagers.py
def run(console):
    ...   # do your thing
```

then add one line to `MENU` in `app.py`. That's the whole extension surface.

## The tricky bits worth reading

- **Piping two subprocesses in Python.** `_audio.py` opens `rtl_fm` with
  `stdout=PIPE` and hands that pipe as `stdin` to `play`, then closes the
  parent-side pipe so only the child sees it. That's how `|` works in a
  shell but done explicitly so we can kill both cleanly on Ctrl+C.
- **Rich `Live` + a blocking loop.** Every mode uses
  `with Live(panel) as live: while True: sleep; live.update(new_panel)`.
  Rich handles the "erase and re-draw" magic so the terminal looks like a
  real dashboard.
- **Background uvicorn.** `MapServer.start()` creates a `uvicorn.Server`
  and runs it in a daemon thread. The `Server` object has a `should_exit`
  attribute we flip to shut it down cleanly.
- **Rotating serial-hop spectrum.** The dongle can only sample ~2.4 MHz at
  once. To "see" a 20 MHz band we retune between reads and stitch the
  answers together. It's not fast, but it's honest.

## What I'd add next (over to you)

- **NOAA weather satellite APT images** — 137 MHz FM, decode with
  [`noaa-apt`](https://noaa-apt.mbernardi.com.ar/). Save as PNG, serve it
  through the same FastAPI.
- **A Textual dashboard** with a live waterfall (time on Y, freq on X,
  power as color). `Textual`'s `Widget.render()` + `RichCast` is perfect
  for this.
- **Automatic ISS notifier** — schedule a system notification 10 minutes
  before a good pass so you never miss one.
- **Trunking scanner** for local police / EMS if that's legal where you
  live (check your country's laws first!).

Every one of those is fewer than 300 lines of Python on top of what's
already here. Go build it.

— B.

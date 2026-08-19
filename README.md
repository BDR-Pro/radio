# SDR Kid — a Software Defined Radio playground

Hey! You have a USB Software Defined Radio (SDR) dongle and a laptop. That's
everything you need to:

- **Listen to FM music** stations
- **Track airplanes** flying near you on a live map
- **Eavesdrop on pilots** talking to Air Traffic Control
- **Watch the International Space Station** fly overhead (and tune to the
  astronauts' voice frequency)
- **Track ships** at sea
- **Sweep the whole radio sky** and see what's talking

Everything runs from a pretty terminal (Rich + Textual + questionary) and
opens live maps in your browser (FastAPI + Folium).

![sdr-kid demo](https://placekitten.com/720/1) <!-- swap for your own screenshot -->

---

## 1. Grab the code

Open **Visual Studio Code**, then open a terminal (`Ctrl + \`` or `View → Terminal`) and run:

```bash
git clone https://github.com/bdr-pro/radio.git sdr-kid
cd sdr-kid
```

## 2. Make a Python virtual environment

A "virtual environment" (venv) is a private box for this project's Python
libraries so they don't get mixed up with your other Python things.

```bash
python -m venv .venv
```

Turn it on:

- **macOS / Linux:**  `source .venv/bin/activate`
- **Windows PowerShell:**  `.venv\Scripts\Activate.ps1`

Your terminal prompt should now start with `(.venv)`.

## 3. Install the Python libraries

```bash
pip install -r requirements.txt
```

## 4. Install the little SDR helpers (one-time, needs sudo)

The dongle needs a driver called **rtl-sdr**, plus something that can play
sound (**sox**). Pick your OS:

**Ubuntu / Debian / Raspberry Pi:**
```bash
sudo apt update
sudo apt install -y rtl-sdr sox
# optional but recommended: rtl_ais for the ship tracker
sudo apt install -y rtl-ais || \
  (git clone https://github.com/dgiardini/rtl-ais && cd rtl-ais && make && sudo make install)
```

**macOS (with Homebrew):**
```bash
brew install librtlsdr sox rtl-ais
```

**Windows:**
- Download the RTL-SDR drivers from https://www.rtl-sdr.com/ (follow the
  Zadig install page — this replaces Windows' built-in TV driver so your
  Python code can talk to the dongle).
- Install SoX from https://sox.sourceforge.net/ and add it to your PATH.

### Linux only — let normal users touch the dongle

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"' | sudo tee /etc/udev/rules.d/20-rtlsdr.rules
sudo udevadm control --reload
```

Unplug the dongle and plug it back in.

Also, the Linux kernel sometimes claims the dongle as a TV tuner. Block
that so `rtl_test` works:

```bash
echo -e "blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830" | sudo tee /etc/modprobe.d/blacklist-rtl.conf
```

Reboot once. That's it forever.

## 5. Run it!

```bash
python -m sdr_kid
```

You'll see a big banner, be asked to plug the dongle in, and then a menu of
things to try. Use the arrow keys and `Enter`. Press `Ctrl+C` any time to
stop a mode and come back to the menu.

If you want to poke around **without** the dongle (planes / ships / ISS map
still work using the internet):

```bash
python -m sdr_kid --skip-dongle
```

---

## Ship tracker: one extra step

The ship tracker needs a second little program running in another terminal
that decodes the raw radio into AIS sentences and pipes them to SDR Kid over
UDP port `10110`. Pick the one for your OS:

**Linux / macOS** (once `rtl-ais` is installed from step 4):

```bash
rtl_ais -h 127.0.0.1 -P 10110
```

**Windows** — there's no `apt-get` for `rtl-ais`, so use one of these:

*Option A — `AIS-catcher` (easiest, well-maintained).*
1. Grab the Windows zip from
   <https://github.com/jvde-github/AIS-catcher/releases> (pick the
   `AIS-catcher-vX.Y.Z-win64.zip` asset) and unzip it somewhere like
   `C:\ais-catcher\`.
2. Open a **second** PowerShell window (leave SDR Kid running in the first).
3. Run:

   ```powershell
   cd C:\ais-catcher
   .\AIS-catcher.exe -u 127.0.0.1 10110
   ```

   That command tunes both AIS channels (161.975 & 162.025 MHz), decodes them,
   and fires the NMEA sentences at SDR Kid.

*Option B — `rtl-ais` Windows build.*
1. Download the prebuilt Windows binary from
   <https://github.com/dgiardini/rtl-ais/releases> (the `rtl-ais-win.zip` asset).
   Unzip into `C:\rtl-ais\`.
2. Make sure the folder is on your `PATH` **or** just `cd` into it.
3. Run:

   ```powershell
   cd C:\rtl-ais
   .\rtl_ais.exe -h 127.0.0.1 -P 10110
   ```

   Same idea as Linux/macOS, same UDP port.

**Then**, in your first terminal, pick **Track ships** in the SDR Kid menu.
Boats within about 40 km of a coast (or 10 km of a river) will start
appearing on the map.

> Firewall note (Windows): the first time you launch the decoder, Windows
> Defender may ask to allow it — click *Allow access* for **Private
> networks** only. SDR Kid listens on `127.0.0.1`, so nothing leaves your
> laptop.

## Where's the map?

Whenever a mode has something visual (planes, ships, ISS), SDR Kid starts a
tiny FastAPI web server on `http://127.0.0.1:8000` and opens it in your
browser. The maps update automatically.

## What's in each folder?

```
sdr_kid/
  app.py            <- the main menu you see
  banner.py         <- the ASCII art
  dongle.py         <- "is the USB stick plugged in?" logic
  server.py         <- the FastAPI map server + live /ws/spectrum
  progress.py       <- your quests / achievements
  logbook.py        <- SQLite aircraft logbook + watchlist
  alerts.py         <- background ISS/NOAA overhead alerts
  modes/
    fm.py           <- FM radio
    atc.py          <- Air Traffic Control
    planes.py       <- ADS-B airplane tracking + auto-log to logbook
    ships.py        <- AIS ship tracking (rtl_ais on UDP 10110)
    iss.py          <- International Space Station
    explore.py      <- RF spectrum sweep (Rich bars + Textual waterfall)
    noaa.py         <- NOAA weather-satellite APT image decoder
    iq.py           <- record & replay raw radio
    alerts_ui.py    <- overhead-pass alert control panel
    logbook_ui.py   <- browse your logbook / edit the watchlist
    _audio.py       <- shared rtl_fm audio pipeline
    _spectrum.py    <- shared spectrum DSP primitives
tests/              <- pytest suite (runs with no hardware)
```

The live spectrum browser view is at `http://127.0.0.1:8000/live`
whenever the RF-explorer mode is running.

Open any file in VS Code and read it! Each one is under 200 lines and shows
you *exactly* how radio + Python fit together.

## Running the tests

```bash
python -m pytest -q
```

Tests fake the dongle so they work anywhere.

## Troubleshooting

- **"no supported devices found"** — the driver can't see the dongle. Run
  `rtl_test`. On Linux, make sure you did the blacklist step above.
- **No sound in FM mode** — check your speakers 🙂 or run
  `play -n synth 1 sine 440` to test SoX.
- **"pyrtlsdr not usable"** — `pip install pyrtlsdr` inside your venv, and
  make sure `librtlsdr` is installed system-wide.
- **Menu keys don't move** — you're probably running in a plain Windows
  CMD window without ANSI. Use Windows Terminal or the VS Code integrated
  terminal.

## How I built this

See [`build.md`](./build.md) — a walkthrough of the design decisions and how
each Python file works.

## Now go build something wild

- Automatically record every ATC exchange near a specific airport.
- Log every plane that crosses your neighborhood into a SQLite file.
- Add NOAA weather satellite decoding to grab images from space.
- Beep when the ISS is above your horizon.

The dongle already can. The Python is already here. You do the wiring.

**73!** *(radio-speak for "best wishes")*

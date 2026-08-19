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

---

## 🚀 Windows? Use the one-click installer.

Skip all the manual steps below — this PowerShell script downloads
rtl-sdr, SoX, AIS-catcher, dump1090, noaa-apt, and Zadig, unzips them
under `%USERPROFILE%\sdr-kid-tools\`, and adds each folder to your PATH.
No admin needed.

Copy-paste this into **PowerShell**:

```powershell
irm https://raw.githubusercontent.com/BDR-Pro/radio/main/scripts/install-windows.ps1 | iex
```

The script:
- Downloads and extracts every command-line tool SDR Kid can use.
- Adds each folder to your **User** PATH permanently.
- Runs the SoX GUI installer for you (accept the default path).
- Downloads Zadig and tells you exactly what to click to swap the USB driver.

Then close and re-open PowerShell (Windows only reads PATH at shell
startup), and follow steps 1 → 2 → 3 → 5 below (skip step 4 — the
script did it).

Options — pass flags by downloading first, then running:

```powershell
# save the script locally
irm https://raw.githubusercontent.com/BDR-Pro/radio/main/scripts/install-windows.ps1 -OutFile install.ps1

# see what it WOULD do (no changes)
powershell -ExecutionPolicy Bypass -File .\install.ps1 -DryRun

# skip Zadig if you already ran it once
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipZadig
```

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

Windows needs three things: the RTL-SDR tools, SoX (for audio), and the
right USB driver. All three follow the same *download → unzip → add to
PATH* pattern.

1. **RTL-SDR tools** — download the zip from
   <https://ftp.osmocom.org/binaries/windows/rtl-sdr/> (grab
   `rtl-sdr-64bit-*.zip`). Unzip somewhere permanent, e.g.
   `C:\Users\<you>\radio\rtl-sdr-64bit-20260816\`.
2. **SoX** — install from <https://sourceforge.net/projects/sox/> (default
   install path is `C:\Program Files (x86)\sox-14-4-2\`).
3. **Add both folders to your user PATH.** Open **PowerShell** and paste
   this (adjust the two paths at the top to match yours):

   ```powershell
   $folders = @(
     'C:\Users\bader\radio\rtl-sdr-64bit-20260816',
     'C:\Program Files (x86)\sox-14-4-2'
   )
   $old = [Environment]::GetEnvironmentVariable('Path','User')
   foreach ($f in $folders) {
     if (-not ($old.Split(';') -contains $f)) {
       $old = "$old;$f"
       Write-Host "added $f"
     }
     $env:Path += ";$f"   # also apply to THIS shell
   }
   [Environment]::SetEnvironmentVariable('Path', $old, 'User')
   ```

   That's a **one-time** step — it survives reboots and applies to
   every new PowerShell / VS Code terminal you open. Verify with:

   ```powershell
   where.exe rtl_test        # should print the .exe's full path
   where.exe sox             # same
   rtl_test.exe -t           # should print "Found Rafael Micro R820T tuner"
   ```

   > ⚠️ **After adding to PATH, close and re-open PowerShell / VS Code.**
   > Windows only reads PATH when a shell (or an app like VS Code) starts.
   > If `where.exe rtl_test` prints nothing, you're in an old shell — close
   > it and open a fresh one. Same for VS Code: quit it entirely (not just
   > the window) so its integrated terminal picks up the new PATH.

4. **Replace the USB driver with Zadig** — Windows installs a TV-tuner
   driver by default, and no SDR tool can talk to the dongle that way.
   Download **Zadig** from <https://zadig.akeo.ie/>:
   - Plug the dongle in.
   - In Zadig: **Options → List All Devices**.
   - From the dropdown pick **Bulk-In, Interface (Interface 0)** — *not*
     "RTL2832U" alone.
   - Confirm the target driver is **WinUSB**, then click **Replace Driver**.
   - Unplug and re-plug the dongle.

   You only ever do this once per dongle per machine.

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

You'll see a big banner, a quick dongle check, and then a menu:

```
> Listen to FM radio (music)
  Track airplanes — my antenna (dump1090)     ← real ADS-B from YOUR dongle
  Track airplanes — the world (OpenSky)       ← online, no dongle needed
  Listen to Air Traffic Control
  Look at the ISS (space station)
  Track ships on the ocean                    ← needs AIS-catcher or rtl_ais
  Explore the RF spectrum                     ← also streams to /live in browser
  Catch a NOAA weather-satellite image        ← picture from space!
  Overhead alerts (ISS / NOAA)
  Airplane logbook + watchlist
  Record & replay raw radio (IQ)
  Show my quests
```

Arrow keys + `Enter`. `Ctrl+C` any time to stop a mode and come back.

If you want to poke around **without** the dongle (planes / ships / ISS map
still work using the internet):

```bash
python -m sdr_kid --skip-dongle
```

---

## Airplane tracker: two modes

SDR Kid ships **two** airplane trackers, side-by-side in the menu.

**"The world" (OpenSky)** — pulls positions from the free
[OpenSky Network](https://opensky-network.org/) web API. No dongle
required. Shows every ADS-B receiver on Earth pooled together.

**"My antenna" (dump1090)** — talks to a locally-running `dump1090` on
`127.0.0.1:30003` and shows **the planes your antenna is actually
decoding at 1090 MHz**. This is the fun one — every dot on the map is a
radio signal that literally arrived at your desk.

### Setting up the local mode

1. Install `dump1090`:
   - **Windows:** the one-click installer above already did it.
     Otherwise grab the zip from
     <https://github.com/mutability/dump1090/releases>.
   - **Linux:** `sudo apt install dump1090-mutability` (or `dump1090-fa`).
   - **macOS:** `brew install dump1090`.
2. In a **second terminal**, start it:
   ```powershell
   dump1090.exe --net       # Windows
   ```
   ```bash
   dump1090 --net           # Linux / macOS
   ```
3. In your SDR Kid terminal, pick **"Track airplanes — my antenna
   (dump1090)"**. Fly overhead planes appear within seconds; every one
   is auto-logged to your logbook.

> ⚠️ Same "one program owns the dongle" rule as the ship tracker: while
> `dump1090` is running it holds the RTL-SDR, so SDR Kid's startup probe
> will report the dongle as busy — that's expected, and the menu still
> opens.

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

   Prefer to run it from anywhere? Add it to your user PATH once:

   ```powershell
   $ais = 'C:\ais-catcher'
   [Environment]::SetEnvironmentVariable('Path',
     ([Environment]::GetEnvironmentVariable('Path','User') + ";$ais"), 'User')
   $env:Path += ";$ais"
   ```

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

> ⚠️ **Only one program can own the RTL-SDR dongle at a time.** Because
> AIS-catcher (or `rtl_ais`) already holds it, SDR Kid's startup dongle
> probe won't be able to see it — that's normal. SDR Kid detects this and
> continues in "no direct dongle" mode; Track ships still works because
> it reads NMEA over UDP, not from the radio directly. If you want to
> skip the probe entirely, launch SDR Kid with `--skip-dongle`.

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
  deps.py           <- OS-aware external-tool detection + install hints
  modes/
    fm.py           <- FM radio
    atc.py          <- Air Traffic Control
    planes.py       <- Airplane tracking via the OpenSky Network API
    planes_local.py <- Airplane tracking from YOUR antenna via dump1090
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

Tests fake the dongle so they work anywhere. 43 checks covering
achievements, logbook + watchlist, spectrum helpers, real AIS decode
(single + multi-fragment), IQ round-trip, FastAPI landing page +
WebSocket end-to-end, location picker, doctor probes, and the CLI
(`--help`, `--version`, `--list`, `--doctor`).

## Is my setup working? — `--doctor`

Not sure if everything's installed correctly? Run:

```bash
python -m sdr_kid --doctor
```

You'll get a table like:

```
✔ pass  python: rich                stream spectrum to the browser
✔ pass  python: pyais               decode ship AIS sentences
✘ fail  tool: rtl_fm                needed to listen to FM / ATC / NOAA
! warn  tool: dump1090              needed to run the airplane tracker
✔ pass  port 8000: free             SDR Kid can start the map server
· skip  dump1090: 127.0.0.1:30003   nothing listening (start it when you want it)
✔ pass  UDP 10110: can bind         ship tracker will be able to listen for AIS
✔ pass  sqlite: read/write          logbook can persist plane sightings
```

Every red row gets an OS-specific fix line ("`sudo apt install rtl-sdr`",
"add `C:\rtl-sdr\` to PATH", etc.) — no more guessing what's broken.
The doctor is also available from the interactive menu as **"Health
check (is everything installed?)"**.

## Troubleshooting

**Everyone**
- **"no supported devices found"** — the driver can't see the dongle. Run
  `rtl_test`. On Linux, make sure you did the blacklist step above.
- **No sound in FM mode** — check your speakers 🙂 or (Linux/macOS) run
  `play -n synth 1 sine 440` to test SoX. Windows: `sox -n -d synth 1 sine 440`.
- **"pyrtlsdr not usable"** — `pip install pyrtlsdr` inside your venv, and
  make sure `librtlsdr` is installed system-wide.
- **Menu keys don't move** — you're probably running in a plain Windows
  CMD window without ANSI. Use Windows Terminal or the VS Code integrated
  terminal.

**Windows-specific**
- **FM says it's playing but you hear nothing** — usually SoX rejecting
  the bare `-d`. Test with `sox -n -t waveaudio -d synth 1 sine 440`.
  If you hear the beep, SDR Kid (from `827317c` onward) already picks the
  right driver — just `git pull`. If SoX says *"no default audio device
  configured"*, your SoX build is old — reinstall it from the one-click
  installer.
- **`rtl_test.exe is not recognized`** — PATH not set (or you're in an old
  PowerShell window that captured the old PATH). Close & reopen PowerShell,
  or `$env:Path += ";$env:USERPROFILE\sdr-kid-tools\rtl-sdr\x64"` in the
  current session. See the Windows install block above for the persistent
  one-liner.
- **`usb_open error -3`** — Windows still has the TV-tuner driver on the
  dongle. Run **Zadig** (see step 4 of the Windows install) and bind the
  "Bulk-In, Interface (Interface 0)" entry to **WinUSB**.
- **`cb transfer status: 5, canceling ... RTLSDR: lost device`** — the
  dongle was pulled out from under whatever program was using it, usually
  because another process opened it in the meantime. Only **one** program
  can own the RTL-SDR at a time. Kill any leftover `AIS-catcher.exe`,
  `rtl_fm.exe`, `SDRSharp.exe` in Task Manager and try again.
- **SDR Kid's dongle probe fails but AIS-catcher works** — that's expected
  when AIS-catcher is already running. SDR Kid will now continue in
  "soft-warn" mode; pick **Track ships** and it'll read the NMEA feed over
  UDP. To skip the probe entirely: `python -m sdr_kid --skip-dongle`.
- **Prefer USB-2 ports (black) over USB-3 (blue)** — USB-3 hubs on many
  laptops generate RF noise that clobbers weak signals; the dongle also
  seems to disconnect less on USB-2.

Every error panel now includes an OS-specific install command (thanks to
`sdr_kid/deps.py`), so you should rarely need to guess what's missing.

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

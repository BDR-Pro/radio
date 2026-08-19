from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import Deque, List, Optional

import questionary
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from sdr_kid import progress as achievements
from sdr_kid.modes._spectrum import BANDS, Sweep, color_for, make_sdr, normalize, sweep
from sdr_kid.server import BUS, get_server


BAR_CHARS = " ▁▂▃▄▅▆▇█"


def _pick_band() -> Optional[tuple[str, int, int]]:
    labels = [f"{n}  ({lo/1e6:.1f}-{hi/1e6:.1f} MHz)" for n, lo, hi in BANDS]
    ans = questionary.select(
        "Which slice of the radio sky?",
        choices=labels + ["Custom range", "Cancel"],
    ).ask()
    if not ans or ans == "Cancel":
        return None
    if ans == "Custom range":
        lo = questionary.text("Low MHz:").ask()
        hi = questionary.text("High MHz:").ask()
        try:
            return (f"{lo}-{hi} MHz", int(float(lo) * 1e6), int(float(hi) * 1e6))
        except (TypeError, ValueError):
            return None
    idx = labels.index(ans)
    return BANDS[idx]


def _ui_choice() -> str:
    return questionary.select(
        "How should we show it?",
        choices=[
            "Textual waterfall (fullscreen, keyboard-driven)",
            "Rich bar chart (simple scrolling view)",
            "Cancel",
        ],
    ).ask() or "Cancel"


# --- Rich fallback (bar chart) -------------------------------------------------


def _render_bars(name: str, lo: int, hi: int, sw: Optional[Sweep]) -> Panel:
    if sw is None or not sw.powers_db:
        return Panel(f"scanning {name}…", border_style="magenta")
    norms = normalize(sw.powers_db)
    lines: List[Text] = []
    width = 40
    for f, p, n in zip(sw.freqs_hz, sw.powers_db, norms):
        idx = min(len(BAR_CHARS) - 1, int(n * (len(BAR_CHARS) - 1)))
        col = color_for(n)
        lines.append(Text.assemble(
            (f"{f/1e6:8.2f} MHz  ", "dim"),
            (BAR_CHARS[idx] * width, col),
            (f"  {p:+6.1f} dB", "dim"),
        ))
    return Panel(
        Group(*lines),
        title=f"[magenta]:mag: RF explorer — {name}[/]",
        border_style="magenta",
        subtitle=f"[dim]{lo/1e6:.2f}-{hi/1e6:.2f} MHz • Ctrl+C to stop[/]",
    )


def _run_rich(console: Console, name: str, lo: int, hi: int) -> None:
    try:
        sdr = make_sdr()
    except Exception as exc:
        console.print(Panel(f"[red]could not open dongle: {exc}[/]"))
        return
    get_server()  # ensure the WS server is running so /live works
    latest: Optional[Sweep] = None
    try:
        with Live(_render_bars(name, lo, hi, latest), console=console, refresh_per_second=4) as live:
            while True:
                latest = sweep(sdr, lo, hi)
                BUS.publish(latest.freqs_hz, latest.powers_db)
                live.update(_render_bars(name, lo, hi, latest))
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sdr.close()
        except Exception:
            pass


# --- Textual waterfall ---------------------------------------------------------


def _run_textual(name: str, lo: int, hi: int) -> None:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.reactive import reactive
    from textual.widget import Widget
    from textual.widgets import Footer, Header, Static
    from rich.text import Text as RichText

    class Waterfall(Widget):
        DEFAULT_CSS = "Waterfall{ height: 1fr; }"
        rows: Deque[List[float]] = deque(maxlen=200)

        def __init__(self, band_lo: int, band_hi: int, **kw):
            super().__init__(**kw)
            self.band_lo = band_lo
            self.band_hi = band_hi

        def push(self, powers: List[float]) -> None:
            self.rows.appendleft(list(powers))
            self.refresh()

        def render(self) -> RichText:
            if not self.rows:
                return RichText("scanning…", style="dim")
            width = max(self.size.width - 12, 20)
            height = min(len(self.rows), max(self.size.height - 2, 4))
            all_vals = [v for row in list(self.rows)[:height] for v in row]
            if not all_vals:
                return RichText("scanning…", style="dim")
            pmin, pmax = min(all_vals), max(all_vals)
            span = max(pmax - pmin, 1.0)
            out = RichText()
            for r in range(height):
                row = self.rows[r]
                if not row:
                    continue
                step = max(1, len(row) // width)
                for i in range(0, len(row), step):
                    chunk = row[i:i + step]
                    n = (sum(chunk) / len(chunk) - pmin) / span
                    out.append("█", style=color_for(n))
                out.append(f"  {pmax:+5.0f}dB\n" if r == 0 else "\n", style="dim")
            return out

    class PeakBar(Widget):
        DEFAULT_CSS = "PeakBar{ height: 3; }"
        latest: Sweep | None = reactive(None)

        def render(self) -> RichText:
            if self.latest is None:
                return RichText("no sweep yet", style="dim")
            peak_idx = max(range(len(self.latest.powers_db)),
                           key=lambda i: self.latest.powers_db[i])
            peak_hz = self.latest.freqs_hz[peak_idx]
            peak_db = self.latest.powers_db[peak_idx]
            t = RichText()
            t.append("peak: ", style="dim")
            t.append(f"{peak_hz/1e6:8.3f} MHz  ", style="bold yellow")
            t.append(f"{peak_db:+6.1f} dB", style="bold red")
            t.append("     ")
            t.append(f"band: {self.latest.freqs_hz[0]/1e6:.2f}"
                     f"–{self.latest.freqs_hz[-1]/1e6:.2f} MHz",
                     style="cyan")
            return t

    class ExplorerApp(App):
        TITLE = "SDR Kid — RF Explorer"
        SUB_TITLE = name
        CSS = """
        Screen { background: #0b1020; }
        Header { background: #182349; }
        Footer { background: #182349; }
        #peak  { padding: 1 2; }
        #legend{ dock: bottom; padding: 0 2; color: #98a3c9; }
        """
        BINDINGS = [
            Binding("q", "quit", "quit"),
            Binding("1", "band(0)", "FM"),
            Binding("2", "band(1)", "AirVHF"),
            Binding("3", "band(3)", "HamVHF"),
            Binding("4", "band(4)", "Marine"),
            Binding("5", "band(7)", "ADS-B"),
            Binding("r", "reset",  "reset"),
        ]

        def __init__(self, lo: int, hi: int):
            super().__init__()
            self.lo = lo
            self.hi = hi
            self.sdr = None
            self._stop = threading.Event()
            self._thread: Optional[threading.Thread] = None

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical():
                yield PeakBar(id="peak")
                yield Waterfall(self.lo, self.hi, id="fall")
                yield Static(
                    "colors: [#1a1f5c]cold[/] → [#00c8c8]cool[/] → "
                    "[#ffdc3c]warm[/] → [#ff3c3c]hot[/]  ·  keys: 1 FM / 2 Air / "
                    "3 Ham / 4 Marine / 5 ADS-B / r reset / q quit",
                    id="legend",
                )
            yield Footer()

        def on_mount(self) -> None:
            self._start_worker()

        def _start_worker(self) -> None:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=0.5)
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

        def _worker(self) -> None:
            try:
                if self.sdr is None:
                    self.sdr = make_sdr()
            except Exception as exc:
                self.call_from_thread(self.exit, f"could not open dongle: {exc}")
                return
            while not self._stop.is_set():
                try:
                    sw = sweep(self.sdr, self.lo, self.hi)
                except Exception:
                    time.sleep(0.5)
                    continue
                self.call_from_thread(self._absorb, sw)
                time.sleep(0.1)

        def _absorb(self, sw: Sweep) -> None:
            self.query_one("#fall", Waterfall).push(sw.powers_db)
            self.query_one("#peak", PeakBar).latest = sw
            BUS.publish(sw.freqs_hz, sw.powers_db)

        def action_band(self, idx: int) -> None:
            if 0 <= idx < len(BANDS):
                nm, lo, hi = BANDS[idx]
                self.lo, self.hi = lo, hi
                self.sub_title = nm
                self.query_one("#fall", Waterfall).rows.clear()
                self._start_worker()

        def action_reset(self) -> None:
            self.query_one("#fall", Waterfall).rows.clear()

        def on_unmount(self) -> None:
            self._stop.set()
            if self.sdr is not None:
                try:
                    self.sdr.close()
                except Exception:
                    pass

    ExplorerApp(lo, hi).run()


def run(console: Console) -> None:
    picked = _pick_band()
    if picked is None:
        return
    name, lo, hi = picked
    server = get_server()
    console.print(f"[dim]live browser view: {server.url}/live[/]")
    achievements.celebrate(console, achievements.record("spectrum_swept"))
    if not sys.stdout.isatty():
        console.print("[dim]no interactive TTY — using Rich fallback[/]")
        _run_rich(console, name, lo, hi)
        return
    choice = _ui_choice()
    if choice.startswith("Textual"):
        _run_textual(name, lo, hi)
    elif choice.startswith("Rich"):
        _run_rich(console, name, lo, hi)
    console.print("[dim]stopped.[/]")

import os
import sys
import tempfile
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """Force all $HOME-derived files into a tmp dir so tests never touch real state."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # modules that captured the path at import time need re-patching
    import sdr_kid.progress as progress_mod
    import sdr_kid.logbook  as logbook_mod
    import sdr_kid.alerts   as alerts_mod
    import sdr_kid.modes.iq as iq_mod
    monkeypatch.setattr(progress_mod, "PROGRESS_FILE", fake_home / ".sdr_kid_progress.json")
    monkeypatch.setattr(logbook_mod,  "DB_PATH",       fake_home / ".sdr_kid_logbook.sqlite")
    monkeypatch.setattr(alerts_mod,   "CACHE",         fake_home / ".sdr_kid_tles.json")
    iq_dir = fake_home / "iq"; iq_dir.mkdir()
    monkeypatch.setattr(iq_mod, "IQ_DIR", iq_dir)
    yield


@pytest.fixture(autouse=True)
def stub_rtlsdr(monkeypatch):
    """Provide a fake rtlsdr module so imports don't fail without the C driver."""
    if "rtlsdr" not in sys.modules:
        mod = types.ModuleType("rtlsdr")
        class RtlSdr:  # minimal shim
            sample_rate = 2.048e6
            center_freq = 100e6
            gain = "auto"
            def read_samples(self, n):
                import numpy as np
                return (np.random.randn(n) + 1j*np.random.randn(n)).astype(np.complex64) * 0.1
            def close(self): pass
            def get_tuner_type(self): return "R820T"
        mod.RtlSdr = RtlSdr
        sys.modules["rtlsdr"] = mod

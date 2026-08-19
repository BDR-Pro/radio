import numpy as np

from sdr_kid.modes import iq


def test_iq_roundtrip(tmp_path):
    rec = iq.record(center_hz=100_000_000, sample_rate=250_000, seconds=1,
                    path=tmp_path / "test.iq",
                    console=__import__("rich").console.Console(quiet=True))
    assert rec.samples > 0
    r2 = iq.open_recording(rec.path)
    assert r2.center_hz == 100_000_000
    assert r2.sample_rate == 250_000
    total = 0
    for chunk in iq.iterate_samples(rec.path):
        total += len(chunk)
    assert total == rec.samples

import subprocess
import sys


def test_help_exits_zero():
    r = subprocess.run(
        [sys.executable, "-m", "sdr_kid", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    assert "SDR Kid" in r.stdout
    assert "--skip-dongle" in r.stdout
    assert "--list" in r.stdout


def test_version_exits_zero():
    r = subprocess.run(
        [sys.executable, "-m", "sdr_kid", "--version"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    assert "sdr-kid" in r.stdout


def test_list_prints_mode_table():
    r = subprocess.run(
        [sys.executable, "-m", "sdr_kid", "--list"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    assert "FM" in r.stdout
    assert "dump1090" in r.stdout
    assert "OpenSky" in r.stdout

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
    assert "Health check" in r.stdout


def test_doctor_runs_and_produces_output():
    r = subprocess.run(
        [sys.executable, "-m", "sdr_kid", "--doctor"],
        capture_output=True, text=True, timeout=30,
    )
    # exit code is 0 (all pass/warn/skip) or 1 (something failed) — both are OK
    assert r.returncode in (0, 1)
    assert "health check" in r.stdout.lower()
    assert "pass" in r.stdout.lower() or "fail" in r.stdout.lower()


def test_test_audio_prints_a_helpful_message():
    r = subprocess.run(
        [sys.executable, "-m", "sdr_kid", "--test-audio"],
        capture_output=True, text=True, timeout=15,
    )
    # exit code 0 = worked (sox present + audio device), 1 = sox missing or
    # driver rejected — either produces a message about SoX in stdout.
    assert r.returncode in (0, 1)
    combined = (r.stdout + r.stderr).lower()
    assert "sox" in combined or "440" in combined

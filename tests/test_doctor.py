"""Sanity coverage for the health-check module."""
import socket

import pytest

from sdr_kid import doctor
from sdr_kid.doctor import (
    Check, PASS, WARN, FAIL, SKIP,
    check_python, check_python_packages, check_sqlite,
    check_static_dir_writable, check_home_writable,
    check_port_free, check_udp_bindable, check_tcp_reachable,
    check_dongle, check_external_tools, run_all, render,
)


def test_check_python_passes_on_supported_interpreter():
    r = check_python()
    assert r.status == PASS
    assert "on" in r.detail


def test_check_python_packages_all_pass_in_dev_env():
    results = check_python_packages()
    # every REQUIRED package is installed in the CI env; pyrtlsdr is optional
    hard = [r for r in results if not r.name.endswith("pyrtlsdr")]
    assert all(r.status == PASS for r in hard), \
        [(r.name, r.status, r.detail) for r in hard if r.status != PASS]


def test_check_sqlite_roundtrips():
    r = check_sqlite()
    assert r.status == PASS


def test_check_home_writable():
    r = check_home_writable()
    assert r.status == PASS


def test_check_static_dir_writable():
    r = check_static_dir_writable()
    assert r.status == PASS


def test_check_port_free_when_port_is_free():
    # pick an ephemeral port for the test
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    r = check_port_free(port)
    assert r.status == PASS


def test_check_port_free_reports_warn_when_busy():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    try:
        r = check_port_free(port)
        assert r.status == WARN
    finally:
        s.close()


def test_check_udp_bindable_reports_warn_when_busy():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        r = check_udp_bindable(port)
        assert r.status == WARN
    finally:
        s.close()


def test_check_tcp_reachable_skips_when_nothing_there():
    # pick a port we know is closed
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    r = check_tcp_reachable("nothing", "127.0.0.1", port, "some feature")
    assert r.status == SKIP


def test_check_dongle_status_is_one_of_known():
    r = check_dongle()
    assert r.status in (PASS, WARN, FAIL)   # depends on environment


def test_check_external_tools_returns_a_list():
    results = check_external_tools()
    assert isinstance(results, list) and results
    for r in results:
        assert r.status in (PASS, WARN, FAIL)
        # every failing/warning check includes a fix hint from deps.py
        if r.status in (FAIL, WARN):
            assert r.fix or r.detail


def test_run_all_returns_flat_list():
    results = run_all()
    assert all(isinstance(r, Check) for r in results)
    # nothing crashed the runner
    assert any(r.status == PASS for r in results)


def test_render_produces_output(capsys):
    from rich.console import Console
    console = Console(force_terminal=False, width=120)
    render(console, run_all())
    out = capsys.readouterr().out
    assert "health check" in out.lower()

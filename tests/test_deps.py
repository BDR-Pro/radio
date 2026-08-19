import sys

from sdr_kid import deps


def test_current_os_is_known():
    assert deps.current_os() in ("windows", "macos", "linux", "other")


def test_missing_tool_message_is_os_specific(monkeypatch):
    monkeypatch.setattr(deps, "which", lambda _n: None)  # pretend everything missing
    # windows
    monkeypatch.setattr(deps, "current_os", lambda: "windows")
    m = deps.RTL_FM.check()
    assert m is not None
    body = m.message()
    assert "rtl_fm" in body and "PATH" in body and "windows" in body
    # linux
    monkeypatch.setattr(deps, "current_os", lambda: "linux")
    body = deps.RTL_FM.check().message()
    assert "apt install rtl-sdr" in body
    # macos
    monkeypatch.setattr(deps, "current_os", lambda: "macos")
    body = deps.RTL_FM.check().message()
    assert "brew install rtl-sdr" in body


def test_require_returns_none_when_present(monkeypatch):
    monkeypatch.setattr(deps, "which", lambda n: "/fake/" + n)
    assert deps.require(deps.RTL_FM, deps.SOX) is None


def test_require_concatenates_multiple(monkeypatch):
    monkeypatch.setattr(deps, "which", lambda n: None)
    monkeypatch.setattr(deps, "current_os", lambda: "linux")
    msg = deps.require(deps.RTL_FM, deps.SOX)
    assert "rtl_fm" in msg and "sox" in msg and "---" in msg

from sdr_kid import location


def test_roundtrip():
    location.remember(21.5, 39.2)
    assert location.recall() == (21.5, 39.2)


def test_recall_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(location, "HOME_FILE", tmp_path / "nope.json")
    assert location.recall() is None


def test_recall_corrupt_returns_none(tmp_path, monkeypatch):
    p = tmp_path / "bad.json"
    p.write_text("not json {{{")
    monkeypatch.setattr(location, "HOME_FILE", p)
    assert location.recall() is None


def test_presets_exist():
    assert "Riyadh" in location.PRESETS
    assert all(isinstance(v, tuple) and len(v) == 2 for v in location.PRESETS.values())

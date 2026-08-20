from sdr_kid.doctor import _model_capabilities


def test_rtl_sdr_blog_v3_gets_am_hint():
    assert "direct sampling" in _model_capabilities("RTL-SDR Blog v3, SN: 001")


def test_nooelec_flagged_as_vhf_only():
    caps = _model_capabilities("Nooelec, NESDR SMArt v5, SN: 93163378")
    assert "Nooelec" in caps and "upconverter" in caps


def test_generic_rtl2832_falls_back():
    assert "generic" in _model_capabilities("Realtek, RTL2832UHIDIR")


def test_unknown_model_still_returns_something():
    assert _model_capabilities("some random dongle") != ""

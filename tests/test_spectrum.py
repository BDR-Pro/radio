from sdr_kid.modes._spectrum import BANDS, color_for, normalize


def test_normalize_bounds():
    assert normalize([-40, -30, -20]) == [0.0, 0.5, 1.0]


def test_normalize_empty():
    assert normalize([]) == []


def test_color_gradient_endpoints():
    cold = color_for(0.0)
    hot  = color_for(1.0)
    mid  = color_for(0.5)
    assert cold.startswith("#") and hot.startswith("#") and mid.startswith("#")
    # cold should be blue-heavy, hot should be red-heavy
    def rgb(h): return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    r0, g0, b0 = rgb(cold)
    r1, g1, b1 = rgb(hot)
    assert b0 > r0 and r1 > b1


def test_bands_are_ordered_and_valid():
    for name, lo, hi in BANDS:
        assert isinstance(name, str) and lo < hi and lo > 0

from sdr_kid import logbook


def test_new_and_existing_aircraft():
    s = [logbook.Sighting(icao="ABC123", callsign="QF1", country="AU", alt_m=10000, speed_kt=450)]
    new1 = logbook.record_batch(s)
    assert new1 == 1
    new2 = logbook.record_batch(s)
    assert new2 == 0
    top = logbook.top()
    assert top[0]["icao"] == "ABC123" and top[0]["hits"] == 2


def test_watchlist_hit_match_by_callsign():
    logbook.watchlist_add("QF1", "watch qantas 1")
    hits = logbook.watchlist_hits([
        logbook.Sighting(icao="XX", callsign="QF1234"),   # substring match
        logbook.Sighting(icao="YY", callsign="AAL100"),   # no match
    ])
    assert len(hits) == 1 and hits[0][0] == "QF1"


def test_watchlist_hit_by_icao():
    logbook.watchlist_add("DEADBE", "spec plane")
    hits = logbook.watchlist_hits([logbook.Sighting(icao="deadbeef", callsign=None)])
    assert len(hits) == 1


def test_watchlist_remove():
    logbook.watchlist_add("XYZ")
    logbook.watchlist_remove("XYZ")
    assert not any(r["pattern"] == "XYZ" for r in logbook.watchlist_all())

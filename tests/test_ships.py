import socket, time

import pytest

from sdr_kid.modes.ships import AISListener


AIS_POS   = b"!AIVDM,1,1,,B,15N:;kPP00J:UAlEbmVfl?vD08:H,0*17"
AIS_STAT1 = b"!AIVDM,2,1,3,B,55P5TL01VIaAL@7WKO@mBplU@<PDhh000000001S;AJ::4A80?4i@E53,0*3E"
AIS_STAT2 = b"!AIVDM,2,2,3,B,1@0000000000000,2*55"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


def _send(port, frames):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for f in frames:
        s.sendto(f + b"\r\n", ("127.0.0.1", port))


def test_position_report_decodes():
    port = _free_port()
    L = AISListener(port=port)
    assert L.start() is None
    _send(port, [AIS_POS])
    time.sleep(0.1); L.poll()
    ships = {m: s for m, s in L.ships.items() if s.lat is not None}
    assert 367168462 in ships
    assert ships[367168462].lat == pytest.approx(37.86991, rel=1e-4)
    L.close()


def test_multipart_static_report_reassembles():
    port = _free_port()
    L = AISListener(port=port)
    assert L.start() is None
    _send(port, [AIS_STAT1, AIS_STAT2])
    time.sleep(0.1); L.poll()
    assert 369190000 in L.ships
    s = L.ships[369190000]
    assert s.name == "MT.MITCHELL"
    assert s.destination == "SEATTLE"
    L.close()

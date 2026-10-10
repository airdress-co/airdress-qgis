import urllib.request

from airdress_qgis.auth.loopback import LoopbackReceiver


def test_receives_one_callback_and_ignores_other_paths():
    r = LoopbackReceiver()
    r.start()
    base = r.redirect_uri.rsplit("/", 1)[0]
    try:
        urllib.request.urlopen(base + "/favicon.ico", timeout=5)
    except Exception:
        pass
    assert not r.done()
    with urllib.request.urlopen(r.redirect_uri + "?code=abc&state=s", timeout=5) as resp:
        assert b"return to QGIS" in resp.read()
    assert r.wait(5) == {"code": "abc", "state": "s"}
    assert r.redirect_uri.startswith("http://127.0.0.1:")

import pytest

from airdress_qgis.auth.credentials import Credentials


def test_exact_host_only():
    c = Credentials()
    c.set("https://maps.airdress.co", "T")
    assert c.for_url("https://maps.airdress.co/tiles/basemap/s/0/0/0.mvt") == "T"
    assert c.for_url("https://MAPS.airdress.co/x") == "T"
    for url in [
        "http://maps.airdress.co/x",  # not https
        "https://maps.airdress.co:8443/x",  # another port
        "https://evil-maps.airdress.co/x",
        "https://maps.airdress.co.example/x",
        "https://x.maps.airdress.co/x",
        "https://account.airdress.co/x",
        "https://user@evil.example/x",
    ]:
        assert c.for_url(url) is None, url


def test_userinfo_cannot_smuggle_the_host():
    c = Credentials()
    c.set("https://maps.airdress.co", "T")
    assert c.for_url("https://maps.airdress.co@evil.example/x") is None


def test_only_https_origins_can_hold_a_token():
    with pytest.raises(ValueError):
        Credentials().set("http://maps.airdress.co", "T")

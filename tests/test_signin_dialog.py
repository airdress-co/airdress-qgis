"""The sign-in dialog, both ways, against the fake authorization server."""

import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("qgis.core")


@pytest.fixture
def dialog(qgis_app, monkeypatch):
    from airdress_qgis import signin
    from airdress_qgis.auth.oauth import AuthorizationServer

    from .fakes import Clock, FakeHub

    clock = Clock()
    hub = FakeHub(clock)
    server = AuthorizationServer("https://hub.example", "airdress-qgis", hub.post, clock)
    opened = []
    monkeypatch.setattr(signin.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    now = {"t": 1000.0}
    monkeypatch.setattr(signin.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(signin.time, "time", lambda: clock.now)
    d = signin.SignInDialog(server)
    d.hub, d.opened, d.now, d.clock = hub, opened, now, clock
    yield d
    d.done(0)


def _callback(d, **query):
    url = d.opened[0]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    target = q["redirect_uri"] + "?" + "&".join(f"{k}={v}" for k, v in {"state": q["state"], **query}.items())
    urllib.request.urlopen(target, timeout=5).read()
    d._receiver.wait(5)


def test_browser_sign_in_completes_without_copying_anything(dialog):
    dialog.start_browser()
    q = parse_qs(urlsplit(dialog.opened[0]).query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"][0].startswith("http://127.0.0.1:")
    _callback(dialog, code="good-code")
    dialog._check_loopback()
    assert dialog.tokens is not None and dialog.result() == 1


def test_a_callback_with_the_wrong_state_is_refused(dialog):
    dialog.start_browser()
    url = dialog.opened[0]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    urllib.request.urlopen(q["redirect_uri"] + "?code=good-code&state=forged", timeout=5).read()
    dialog._receiver.wait(5)
    dialog._check_loopback()
    assert dialog.tokens is None and "did not complete" in dialog.message.text()


def test_a_browser_that_never_comes_back_offers_the_code(dialog):
    dialog.start_browser()
    dialog.now["t"] += 121
    dialog._check_loopback()
    assert "Use a code instead" in dialog.message.text() and dialog._receiver is None


def test_device_code_polls_until_approved(dialog):
    dialog.start_device()
    assert dialog.code.text() == "ABCD-EFGH"
    for _ in range(5):
        dialog.now["t"] += 6
        dialog._poll_device()
        if dialog.tokens:
            break
    assert dialog.tokens is not None and dialog.result() == 1


def test_device_code_slows_down_when_asked(dialog):
    dialog.hub.device_mode = "slow_down"
    dialog.start_device()
    dialog.now["t"] += 6
    dialog._poll_device()
    assert dialog._interval == 10


def test_device_code_declined_or_expired_says_so(dialog):
    dialog.hub.device_mode = "denied"
    dialog.start_device()
    dialog.now["t"] += 6
    dialog._poll_device()
    assert dialog.message.text() == "The request was declined."

    dialog.hub.device_mode = "ok"
    dialog.start_device()
    dialog.clock.now += 601
    dialog.now["t"] += 6
    dialog._poll_device()
    assert "expired" in dialog.message.text()

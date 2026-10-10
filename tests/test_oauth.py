import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from airdress_qgis.auth.oauth import AuthorizationServer, OAuthError, pkce_pair

from .fakes import Clock, FakeHub


def server():
    clock = Clock()
    hub = FakeHub(clock)
    return AuthorizationServer("https://hub.example", "airdress-qgis", hub.post, clock), hub, clock


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_authorize_url_carries_pkce_resource_and_loopback():
    s, _, _ = server()
    url = s.authorize_url("http://127.0.0.1:5555/callback", "https://hub.example/api", "offline_access", "st", "ch")
    parts = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.path == "/oauth/authorize"
    assert q["code_challenge_method"] == "S256" and q["code_challenge"] == "ch"
    assert q["resource"] == "https://hub.example/api"
    assert q["redirect_uri"] == "http://127.0.0.1:5555/callback"
    assert q["client_id"] == "airdress-qgis" and q["state"] == "st"


def test_code_exchange():
    s, hub, clock = server()
    tokens = s.exchange_code("good-code", "v", "http://127.0.0.1:1/callback", "https://hub.example/api")
    assert tokens.access_token.startswith("at-") and tokens.refresh_token.startswith("rt-")
    assert tokens.expires_at == clock.now + 900
    assert hub.calls[-1][1]["client_id"] == "airdress-qgis"


def test_bad_code_is_an_oauth_error():
    s, _, _ = server()
    with pytest.raises(OAuthError) as err:
        s.exchange_code("bad", "v", "http://127.0.0.1:1/callback", "r")
    assert err.value.code == "invalid_grant"


def test_device_flow_pending_then_tokens():
    s, _, _ = server()
    start = s.start_device("https://hub.example/api", "offline_access")
    assert start.user_code == "ABCD-EFGH" and start.interval == 5
    assert s.poll_device(start.device_code) is None
    assert s.poll_device(start.device_code) is None
    assert s.poll_device(start.device_code).access_token.startswith("at-")

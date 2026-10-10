import pytest

from airdress_qgis import config
from airdress_qgis.auth.credentials import Credentials
from airdress_qgis.auth.oauth import AuthorizationServer
from airdress_qgis.auth.session import MemoryStore, MintRefused, Session, SignedOut, Store

from .fakes import Clock, FakeHub


def make(store=None):
    clock = Clock()
    hub = FakeHub(clock)
    server = AuthorizationServer("https://hub.example", "airdress-qgis", hub.post, clock)
    creds = Credentials()
    session = Session(server, hub.post, store or MemoryStore(), creds, clock)
    return session, hub, creds, clock


def signed_in():
    session, hub, creds, clock = make()
    session.adopt(session._server.exchange_code("good-code", "v", "http://127.0.0.1:1/callback", "r"))
    return session, hub, creds, clock


def test_maps_token_lands_in_credentials_for_the_maps_host_only():
    session, _, creds, _ = signed_in()
    session.ensure_fresh()
    assert creds.for_url(config.MAPS_ORIGIN + "/tiles/basemap/x/1/2/3.mvt").startswith("maps-")
    assert creds.hosts() == [config.MAPS_ORIGIN.split("://")[1]]


def test_maps_token_reused_until_margin_then_reminted():
    session, _hub, creds, clock = signed_in()
    session.ensure_fresh()
    first = creds.for_url(config.MAPS_ORIGIN + "/")
    clock.now += 900 - config.RENEW_MARGIN_SECONDS - 1
    session.ensure_fresh()
    assert creds.for_url(config.MAPS_ORIGIN + "/") == first
    clock.now += 2
    session.ensure_fresh()
    assert creds.for_url(config.MAPS_ORIGIN + "/") != first


def test_refresh_rotates_and_is_persisted():
    store = MemoryStore()
    session, hub, _, clock = make(store)
    session.adopt(session._server.exchange_code("good-code", "v", "u", "r"))
    before = store.value
    clock.now += 900  # access token past its margin
    session.ensure_fresh()
    assert store.value != before and store.value in hub.live_refresh


def test_reused_refresh_token_signs_out_and_clears():
    session, hub, creds, clock = signed_in()
    session.ensure_fresh()
    hub.live_refresh.clear()  # e.g. the grant was revoked on the account page
    clock.now += 2000
    with pytest.raises(SignedOut):
        session.ensure_fresh()
    assert not session.signed_in
    assert creds.hosts() == []


def test_sign_out_revokes_and_forgets_even_if_revoke_fails():
    session, hub, creds, _ = signed_in()
    session.ensure_fresh()
    assert session.sign_out() is None
    assert hub.revoked and not session.signed_in and creds.hosts() == []

    session, hub, creds, _ = signed_in()

    def broken(*a):
        return 500, None

    session._server._post = broken
    assert session.sign_out() is not None
    assert not session.signed_in


def test_restore_is_lazy_and_reads_the_store_once():
    class CountingStore(Store):
        loads = 0

        def load(self):
            CountingStore.loads += 1

        def save(self, value):
            return False

        def delete(self):
            pass

    session, _, _, _ = make(CountingStore())
    assert CountingStore.loads == 0
    assert not session.signed_in
    assert not session.signed_in
    assert CountingStore.loads == 1


def test_session_only_when_store_refuses():
    class Refusing(MemoryStore):
        def save(self, value):
            return False

    session, *_ = make(Refusing())
    session.adopt(session._server.exchange_code("good-code", "v", "u", "r"))
    assert session.signed_in and not session.persisted


def test_mint_refused_is_reported_with_status():
    session, hub, _, _ = signed_in()
    hub.mint_status = 403
    with pytest.raises(MintRefused) as err:
        session.ensure_fresh()
    assert err.value.status == 403

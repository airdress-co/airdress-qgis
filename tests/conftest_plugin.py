"""A plugin wired to the fake hub and to canned map-service answers."""

from __future__ import annotations

import pytest

STYLE = {
    "version": 8,
    "sprite": "/static/sprites/v4/light",
    "sources": {"protomaps": {"type": "vector", "url": "pmtiles:///basemap/s1/x.pmtiles"}},
    "layers": [
        {"id": "bg", "type": "background", "paint": {"background-color": "#ffffff"}},
        {
            "id": "water",
            "type": "fill",
            "source": "protomaps",
            "source-layer": "water",
            "paint": {"fill-color": "#0000ff"},
        },
    ],
}

ORIGIN = "https://maps.airdress.co"


def current_body(snap: str = "s1") -> dict:
    return {
        "style": f"/static/styles/{snap}/a.json",
        "snapshot": snap,
        "tiles": {
            "basemap": f"/tiles/basemap/{snap}/{{z}}/{{x}}/{{y}}.mvt",
            "boundaries": "/tiles/boundaries/overture-1/{z}/{x}/{y}.mvt",
        },
    }


@pytest.fixture
def wired(qgis_app, monkeypatch):
    from qgis.core import QgsProject
    from qgis.testing.mocked import get_iface

    import airdress_qgis
    from airdress_qgis import net
    from airdress_qgis.auth.oauth import AuthorizationServer
    from airdress_qgis.auth.session import MemoryStore, Session

    from .fakes import Clock, FakeHub

    iface = get_iface()
    iface.messageBar().pushMessage.reset_mock()
    plugin = airdress_qgis.classFactory(iface)
    clock = Clock()
    hub = FakeHub(clock)
    plugin.server = AuthorizationServer("https://hub.example", "airdress-qgis", hub.post, clock)
    plugin.session = Session(plugin.server, hub.post, MemoryStore(), plugin.credentials, clock)
    answers: dict = {}
    monkeypatch.setattr(net, "get_json", lambda url, headers=None: answers.get(url, (404, None)))
    monkeypatch.setattr(net, "get_bytes", lambda url: (404, b""))
    plugin.answers, plugin.hub, plugin.clock, plugin.iface = answers, hub, clock, iface
    QgsProject.instance().clear()
    yield plugin
    plugin.timer.stop()
    QgsProject.instance().clear()


def sign_in(plugin) -> None:
    plugin.session.adopt(plugin.server.exchange_code("good-code", "v", "http://127.0.0.1:1/callback", "r"))


def messages(plugin) -> list[str]:
    return [c.args[1] for c in plugin.iface.messageBar().pushMessage.call_args_list]

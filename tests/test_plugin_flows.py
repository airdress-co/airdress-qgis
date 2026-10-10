"""The plugin's own flows, against the fake hub and canned map answers."""

import pytest

pytest.importorskip("qgis.core")

from .conftest_plugin import ORIGIN, STYLE, current_body, messages, sign_in


def _serve_map(plugin, snap="s1"):
    plugin.answers[ORIGIN + "/current.json"] = (200, current_body(snap))
    plugin.answers[f"{ORIGIN}/static/styles/{snap}/a.json"] = (200, STYLE)


def test_add_basemap_then_boundaries_puts_boundaries_on_top(wired):
    from qgis.core import QgsProject

    from airdress_qgis.maps import layers

    sign_in(wired)
    _serve_map(wired)
    wired.add_layer("basemap")
    wired.add_layer("boundaries")
    order = [layers.kind_of(n.layer()) for n in QgsProject.instance().layerTreeRoot().findLayers()]
    assert order == ["boundaries", "basemap"]
    assert wired.credentials.for_url(ORIGIN + "/tiles/x").startswith("maps-")


def test_a_refused_style_is_reported_and_adds_nothing(wired):
    from qgis.core import QgsProject

    sign_in(wired)
    wired.answers[ORIGIN + "/current.json"] = (200, current_body())
    wired.answers[ORIGIN + "/static/styles/s1/a.json"] = (503, {"error": "maps_paused"})
    wired.add_layer("basemap")
    assert QgsProject.instance().mapLayers() == {}
    assert any("paused" in m for m in messages(wired))


def test_an_older_front_without_tiles_says_so_once(wired):
    sign_in(wired)
    wired.answers[ORIGIN + "/current.json"] = (200, {"style": "/static/a.json"})
    assert wired.current() is None
    assert messages(wired) == ["The Airdress map did not answer as expected. Try again later."]


def test_renew_reports_each_failure_in_one_sentence(wired):
    from airdress_qgis.auth.oauth import NetworkError

    assert wired.renew() is False  # never signed in
    assert "signed out" in messages(wired)[-1]

    sign_in(wired)
    wired.hub.mint_status = 403
    assert wired.renew() is False
    assert wired.timer.isActive()

    wired.hub.mint_status = 200

    def offline(*a):
        raise NetworkError("down")

    wired.session._mint_maps = offline
    assert wired.renew() is False
    assert "could not be reached" in messages(wired)[-1]
    assert wired.timer.isActive()


def test_the_same_sentence_is_not_repeated_within_a_minute(wired):
    wired.say("network")
    wired.say("network")
    assert len(messages(wired)) == 1


def test_sign_out_revokes_and_forgets(wired):
    sign_in(wired)
    wired.renew()
    wired.sign_out()
    assert wired.hub.revoked
    assert not wired.session.signed_in and wired.credentials.hosts() == []
    assert messages(wired)[-1] == "Signed out."


def test_sign_in_through_the_dialog_starts_renewal(wired, monkeypatch):
    from airdress_qgis import plugin as plugin_module

    server = wired.server

    class FakeDialog:
        def __init__(self, *a):
            self.tokens = server.exchange_code("good-code", "v", "u", "r")

        def start_browser(self):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(plugin_module, "SignInDialog", FakeDialog)
    assert wired.sign_in() is True
    assert wired.timer.isActive()
    assert wired.credentials.hosts() == ["maps.airdress.co"]


def test_a_project_reopened_signed_out_says_how_many_layers_wait(wired, tmp_path):
    from qgis.core import QgsProject

    sign_in(wired)
    _serve_map(wired)
    wired.add_layer("basemap")
    path = str(tmp_path / "p.qgz")
    QgsProject.instance().write(path)
    wired.session.sign_out()
    QgsProject.instance().clear()
    QgsProject.instance().read(path)
    wired.on_project_read()
    assert "1 layer(s)" in messages(wired)[-1]


def test_a_project_reopened_signed_in_moves_to_the_current_snapshot(wired, tmp_path):
    from qgis.core import QgsProject

    sign_in(wired)
    _serve_map(wired, "s1")
    wired.add_layer("basemap")
    path = str(tmp_path / "p.qgz")
    QgsProject.instance().write(path)
    QgsProject.instance().clear()
    QgsProject.instance().read(path)
    _serve_map(wired, "s2")
    wired.on_project_read()
    from airdress_qgis.maps import layers

    (layer,) = QgsProject.instance().mapLayers().values()
    assert layers.template_of(layer.source()) == ORIGIN + "/tiles/basemap/s2/{z}/{x}/{y}.mvt"


def test_go_to_centres_the_canvas_and_marks_the_place(wired):
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    canvas = wired.iface.mapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    canvas.setExtent(QgsRectangle(0, 40, 20, 60))
    wired.go_to({"lon": 11.57, "lat": 48.13, "layer": "locality"})
    centre = canvas.center()
    assert abs(centre.x() - 11.57) < 0.01 and abs(centre.y() - 48.13) < 0.01
    assert wired._marker is not None
    wired._clear_marker()
    assert wired._marker is None


def test_results_go_to_one_scratch_layer_on_request_only(wired):
    from qgis.core import QgsProject

    wired.add_to_scratch({"name": "München", "address": "Bayern", "lon": 11.57, "lat": 48.13})
    wired.add_to_scratch({"name": "Berlin", "address": "", "lon": 13.4, "lat": 52.5})
    (layer,) = QgsProject.instance().mapLayersByName("Airdress search results")
    assert layer.featureCount() == 2
    assert sorted(f["name"] for f in layer.getFeatures()) == ["Berlin", "München"]


def test_whats_here_names_the_place_under_the_click(wired):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY

    sign_in(wired)
    wired.iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    asked = []
    wired.call_json = lambda url, body, feedback=None: (
        asked.append((url, body))
        or (200, {"results": [{"name": "Marienplatz", "address": {"city": "München"}, "point": [11.57, 48.13]}]})
    )
    wired._reverse(QgsPointXY(11.57, 48.13), None)
    assert asked[0][0].endswith("/reverse") and asked[0][1]["point"] == [11.57, 48.13]
    assert messages(wired)[-1] == "Marienplatz — München"


def test_attribution_is_drawn_only_while_an_airdress_layer_shows(wired):
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    def corner_after_draw():
        image = QImage(400, 200, QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        painter = QPainter(image)
        wired._draw_attribution(painter)
        painter.end()
        return image.pixelColor(395, 195).name()

    assert corner_after_draw() == "#000000"
    sign_in(wired)
    _serve_map(wired)
    wired.add_layer("basemap")
    assert corner_after_draw() != "#000000"


def test_layout_attribution_needs_an_open_layout_and_names_the_credits(wired):
    from qgis.core import QgsLayoutItemLabel, QgsPrintLayout, QgsProject

    wired.iface.openLayoutDesigners.return_value = []
    wired.add_layout_attribution()
    assert "Open a print layout first" in messages(wired)[-1]

    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()

    class Designer:
        def layout(self):
            return layout

    wired.iface.openLayoutDesigners.return_value = [Designer()]
    wired.add_layout_attribution()
    (label,) = [i for i in layout.items() if isinstance(i, QgsLayoutItemLabel)]
    assert "OpenStreetMap" in label.text()

"""The Satellite mosaic and the aerial photos: parsing, credits, layers,
their place in the layer tree, and projects that outlive an archive."""

import pytest

pytest.importorskip("qgis.core")

from .conftest_plugin import ORIGIN, STYLE, current_body, messages, sign_in

VIENNA = {
    "path": "/imagery/aerial-at-vienna-2026-09/aerial-at-vienna-2026-09.pmtiles",
    "tiles": "/tiles/aerial/aerial-at-vienna-2026-09/{z}/{x}/{y}",
    "bounds": [16.18, 48.11, 16.58, 48.33],
    "minzoom": 12,
    "maxzoom": 17,
    "year": 2025,
    "years": "2024–2025",
    "credit": "aerial-at-basemap",
    "attribution": {
        "line": "Data source: basemap.at",
        "lineUrl": "https://basemap.at/",
        "licence": "CC BY 4.0",
        "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
        "changed": True,
    },
}
PARIS = {
    "tiles": "/tiles/aerial/aerial-fr-paris-2024/{z}/{x}/{y}",
    "bounds": [2.22, 48.81, 2.47, 48.91],
    "minzoom": 12,
    "maxzoom": 19,
    "years": "2024",
    "attribution": {
        "line": "IGN – BD ORTHO®, mise à jour 2024",
        "lineUrl": None,
        "licence": "",
        "licenceUrl": "",
        "changed": False,
    },
}


@pytest.fixture(autouse=True)
def reads_webp(monkeypatch):
    """Whether QGIS reads WebP is the install's (QGIS 4.2's image does not):
    these tests say it does, and the one about the refusal says it does not."""
    from airdress_qgis import plugin as plugin_module

    monkeypatch.setattr(plugin_module.QImageReader, "supportedImageFormats", staticmethod(lambda: [b"png", b"webp"]))


def body(aerial=(VIENNA, PARIS), imagery=True):
    b = current_body()
    if imagery:
        b["tiles"]["imagery"] = "/tiles/imagery/s2-2026q2/{z}/{x}/{y}"
    b["aerial"] = list(aerial)
    return b


def test_current_lists_only_aerial_archives_it_can_draw_and_credit():
    from airdress_qgis.maps import current

    uncredited = dict(VIENNA, attribution=None)
    no_tiles = {k: v for k, v in PARIS.items() if k != "tiles"}
    bad_bounds = dict(PARIS, bounds=[1, 2])
    elsewhere = dict(PARIS, tiles="/tiles/basemap/x/{z}/{x}/{y}.mvt")
    c = current.parse(body((VIENNA, uncredited, no_tiles, bad_bounds, elsewhere, "junk", PARIS)))
    assert [a.id for a in c.aerial] == ["aerial-at-vienna-2026-09", "aerial-fr-paris-2024"]
    vienna = c.aerial[0]
    assert vienna.tiles == ORIGIN + "/tiles/aerial/aerial-at-vienna-2026-09/{z}/{x}/{y}"
    assert (vienna.minzoom, vienna.maxzoom, vienna.bounds) == (12, 17, (16.18, 48.11, 16.58, 48.33))
    assert vienna.line_url == "https://basemap.at/" and c.aerial[1].line_url is None
    assert c.template("imagery") == ORIGIN + "/tiles/imagery/s2-2026q2/{z}/{x}/{y}"
    assert current.parse(current_body()).aerial == []
    assert current.parse(dict(current_body(), aerial="nope")).aerial == []


def test_places_and_families_of_the_live_archive_ids():
    from airdress_qgis.maps.current import Aerial, family_of

    def a(i):
        return Aerial(i, "", (0, 0, 0, 0), 12, 19, "", "", None, "", "", False)

    assert [
        a(i).place
        for i in (
            "aerial-de-by-munich-2024",
            "aerial-de-be-berlin-2025",
            "aerial-de-hh-hamburg-2026",
            "aerial-at-vienna-2026-09",
            "aerial-fr-paris-2024",
            "aerial-us-new-york-2023",
        )
    ] == ["Munich", "Berlin", "Hamburg", "Vienna", "Paris", "New York"]
    assert family_of("aerial-at-vienna-2026-09") == family_of("aerial-at-vienna-2027") == "aerial-at-vienna"


def test_an_archive_is_found_by_id_then_by_place():
    from airdress_qgis.maps import current

    c = current.parse(body())
    assert c.aerial_for("aerial-fr-paris-2024").id == "aerial-fr-paris-2024"
    assert c.aerial_for("aerial-fr-paris-2019").id == "aerial-fr-paris-2024"
    assert c.aerial_for("aerial-de-be-berlin-2025") is None


def test_aerial_credits_read_as_the_page_writes_them():
    from airdress_qgis import attribution
    from airdress_qgis.maps import current

    vienna, paris = current.parse(body()).aerial
    assert attribution.aerial(vienna) == "Imagery: Data source: basemap.at (CC BY 4.0), 2024–2025, changed"
    assert attribution.aerial(vienna, "de_DE") == "Luftbild: Data source: basemap.at (CC BY 4.0), 2024–2025, verändert"
    # IGN's own words end with the year: it is not said twice.
    assert attribution.aerial(paris) == "Imagery: IGN – BD ORTHO®, mise à jour 2024"
    line = attribution.line(["imagery", "basemap"], [attribution.aerial(paris), "", attribution.aerial(paris)])
    assert line.count("IGN") == 1
    assert "Contains modified Copernicus Sentinel data" in line
    assert line.endswith("maps.airdress.co/licenses")


def test_raster_layers_name_their_template_zooms_and_credit(qgis_app):
    from airdress_qgis.maps import current, layers

    c = current.parse(body())
    sat = layers.imagery(c)
    assert sat.providerType() == "wms" and sat.name() == "Airdress satellite"
    assert layers.template_of(sat.source()) == ORIGIN + "/tiles/imagery/s2-2026q2/{z}/{x}/{y}"
    assert "zmax=14" in sat.source() and layers.kind_of(sat) == "imagery"
    assert layers.credit_of(sat) == ["Contains modified Copernicus Sentinel data"]

    vienna = layers.aerial(c.aerial[0])
    assert vienna.name() == "Airdress aerial — Vienna"
    assert "zmin=12" in vienna.source() and "zmax=17" in vienna.source()
    assert layers.kind_of(vienna) == "aerial" and layers.aerial_id_of(vienna) == "aerial-at-vienna-2026-09"
    assert layers.credit_of(vienna) == ["Imagery: Data source: basemap.at (CC BY 4.0), 2024–2025, changed"]
    assert vienna.metadata().rights() == layers.credit_of(vienna)
    assert vienna.customProperty(layers.BOUNDS_PROPERTY) == "16.18,48.11,16.58,48.33"


def _serve(plugin, b=None):
    plugin.answers[ORIGIN + "/current.json"] = (200, b or body())
    plugin.answers[f"{ORIGIN}/static/styles/s1/a.json"] = (200, STYLE)


def _tree():
    from qgis.core import QgsProject

    from airdress_qgis.plugin import _kind_of_node

    return [_kind_of_node(n) for n in QgsProject.instance().layerTreeRoot().children()]


def test_layers_keep_their_order_whichever_is_added_first(wired):
    sign_in(wired)
    _serve(wired)
    wired.add_layer("boundaries")
    wired.add_aerial()
    wired.add_layer("imagery")
    wired.add_layer("basemap")
    # Top to bottom: boundaries over the photos over the mosaic over the map.
    assert _tree() == ["boundaries", "aerial", "imagery", "basemap"]


def test_aerial_photos_come_as_one_group_of_one_layer_per_place(wired):
    from qgis.core import QgsProject

    sign_in(wired)
    _serve(wired)
    wired.add_aerial()
    (group,) = QgsProject.instance().layerTreeRoot().children()
    assert group.name() == "Airdress aerial"
    assert [n.layer().name() for n in group.findLayers()] == ["Airdress aerial — Vienna", "Airdress aerial — Paris"]


def test_a_map_without_imagery_says_so_and_adds_nothing(wired):
    from qgis.core import QgsProject

    sign_in(wired)
    _serve(wired, body(aerial=(), imagery=False))
    wired.add_layer("imagery")
    wired.add_aerial()
    assert QgsProject.instance().mapLayers() == {}
    assert messages(wired) == [
        "The Airdress map has no satellite imagery right now.",
        "The Airdress map has no aerial photos right now.",
    ]


def test_without_webp_nothing_is_added_and_the_package_is_named(wired, monkeypatch):
    from qgis.core import QgsProject

    from airdress_qgis import plugin as plugin_module

    monkeypatch.setattr(plugin_module.QImageReader, "supportedImageFormats", staticmethod(lambda: [b"png", b"jpeg"]))
    sign_in(wired)
    _serve(wired)
    wired.add_layer("imagery")
    wired.add_aerial()
    assert QgsProject.instance().mapLayers() == {}
    (said,) = messages(wired)
    assert "WebP" in said and "qt6-image-formats-plugins" in said


def test_an_aerial_credit_is_named_only_while_its_photos_are_in_view(wired):
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    sign_in(wired)
    _serve(wired)
    wired.add_layer("imagery")
    wired.add_aerial()
    canvas = wired.iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    canvas.setExtent(QgsRectangle(16.30, 48.15, 16.45, 48.25))  # Vienna
    text = wired.attribution_text()
    assert "basemap.at" in text and "IGN" not in text
    assert "Copernicus" in text
    canvas.setExtent(QgsRectangle(9.9, 53.5, 10.1, 53.6))  # Hamburg: no photos held here
    assert "Imagery:" not in wired.attribution_text()


def test_projects_follow_a_new_flight_of_the_same_place(wired, tmp_path):
    from qgis.core import QgsProject

    from airdress_qgis.maps import layers

    sign_in(wired)
    _serve(wired, body(aerial=(dict(VIENNA, tiles="/tiles/aerial/aerial-at-vienna-2025/{z}/{x}/{y}"), PARIS)))
    wired.add_aerial()
    wired.add_layer("imagery")
    project = QgsProject.instance()
    path = str(tmp_path / "p.qgz")
    assert project.write(path)

    # A quarter later: a new mosaic and a new flight of Vienna; Paris is gone.
    newer = body(aerial=(VIENNA,))
    newer["tiles"]["imagery"] = "/tiles/imagery/s2-2026q3/{z}/{x}/{y}"
    _serve(wired, newer)
    project.clear()
    assert project.read(path)
    wired.on_project_read()  # what QGIS's readProject signal calls once initGui ran
    by_name = {layer.name(): layer for layer in project.mapLayers().values()}
    vienna = by_name["Airdress aerial — Vienna"]
    assert layers.aerial_id_of(vienna) == "aerial-at-vienna-2026-09"
    assert layers.template_of(vienna.source()) == ORIGIN + "/tiles/aerial/aerial-at-vienna-2026-09/{z}/{x}/{y}"
    assert layers.template_of(by_name["Airdress satellite"].source()).endswith("/s2-2026q3/{z}/{x}/{y}")
    # Paris's archive is kept as it was: nothing to move it to.
    assert layers.template_of(by_name["Airdress aerial — Paris"].source()).endswith("/aerial-fr-paris-2024/{z}/{x}/{y}")

import pytest

from airdress_qgis import attribution
from airdress_qgis.maps import current, style

STYLE = {
    "version": 8,
    "glyphs": "/static/fonts/{fontstack}/{range}.pbf",
    "sprite": "/static/sprites/v4/light",
    "sources": {
        "protomaps": {
            "type": "vector",
            "url": "pmtiles:///basemap/s1/x.pmtiles",
            "attribution": '<a href="x">© OpenStreetMap</a>',
        },
        "terrain": {"type": "raster-dem", "url": "pmtiles:///terrain/t.pmtiles"},
    },
    "layers": [
        {"id": "bg", "type": "background"},
        {"id": "water", "type": "fill", "source": "protomaps", "source-layer": "water"},
        {"id": "hills", "type": "hillshade", "source": "terrain"},
    ],
}

T = "https://maps.airdress.co/tiles/basemap/s1/{z}/{x}/{y}.mvt"


def test_vector_source_points_at_xyz_and_others_are_dropped():
    out = style.for_qgis(STYLE, T, "https://maps.airdress.co")
    assert out["sources"]["protomaps"]["tiles"] == [T]
    assert "url" not in out["sources"]["protomaps"]
    assert "terrain" not in out["sources"]
    assert [l["id"] for l in out["layers"]] == ["bg", "water"]
    assert out["sprite"] == "https://maps.airdress.co/static/sprites/v4/light"
    assert out["glyphs"].startswith("https://maps.airdress.co/static/fonts/")
    assert STYLE["sources"]["protomaps"]["url"].startswith("pmtiles://")  # input untouched


def test_source_attribution_is_plain_text():
    assert style.source_attributions(STYLE) == ["© OpenStreetMap"]


def test_current_json_gives_absolute_urls_and_refuses_foreign_hosts():
    c = current.parse(
        {
            "style": "/static/styles/s1/a.json",
            "snapshot": "s1",
            "tiles": {"basemap": "/tiles/basemap/s1/{z}/{x}/{y}.mvt"},
        },
        "https://maps.airdress.co",
    )
    assert c.template("basemap") == T and c.template("boundaries") is None
    with pytest.raises(ValueError):
        current.parse({"style": "https://evil.example/s.json", "tiles": {"basemap": "/t"}}, "https://maps.airdress.co")
    with pytest.raises(current.NoTileRoute):
        current.parse({"style": "/s.json"}, "https://maps.airdress.co")


def test_attribution_line_covers_each_kind_once_and_names_the_licences():
    line = attribution.line(["boundaries", "basemap"])
    assert line.startswith("© OpenStreetMap")
    assert "Boundaries: Overture Maps Foundation" in line
    assert line.count("Protomaps") == 1
    assert line.endswith("maps.airdress.co/licenses")
    assert attribution.line([]) == ""

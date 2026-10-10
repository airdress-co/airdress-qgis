from airdress_qgis.search import geocode


def test_short_queries_are_not_sent():
    assert geocode.forward_body("ab", None, None, "en") is None
    assert geocode.forward_body("  ab  ", None, None, "en") is None


def test_forward_body_coarsens_focus_and_keeps_known_language():
    body = geocode.forward_body(" munich ", (13.40495, 52.52001), 11, "de")
    assert body == {
        "text": "munich",
        "autocomplete": True,
        "limit": 8,
        "focus": [13.4, 52.52],
        "zoom": 11,
        "lang": "de",
    }
    assert "lang" not in geocode.forward_body("munich", None, None, "pt")


def test_zoom_for_width():
    assert geocode.zoom_for_width(360) == 3
    assert geocode.zoom_for_width(0.05) == 14
    assert geocode.zoom_for_width(1e-9) == 18


def test_hits_and_address_format():
    body = {
        "results": [
            {
                "name": "München",
                "address": {"state": "Bayern", "country": "Deutschland"},
                "point": [11.57, 48.13],
                "layer": "locality",
                "credit": "GeoNames",
            },
            {"name": "broken", "point": None},
        ]
    }
    (hit,) = geocode.hits(body)
    assert hit.address == "Bayern, Deutschland" and hit.lon == 11.57
    assert (
        geocode.format_address({"street": "Marienplatz", "housenumber": "1", "city": "München"})
        == "Marienplatz 1, München"
    )

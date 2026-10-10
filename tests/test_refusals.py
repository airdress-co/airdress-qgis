from airdress_qgis import refusals


def test_every_code_has_both_languages():
    assert set(refusals.MESSAGES["en"]) == set(refusals.MESSAGES["de"])


def test_unknown_codes_never_leak_raw():
    assert refusals.sentence("weird_code") == refusals.MESSAGES["en"]["generic"]
    assert refusals.sentence("geocoder_starting", "de_DE", seconds=15).endswith("15 Sekunden noch einmal.")


def test_status_mapping():
    assert refusals.code_for(429, None) == "rate_limited"
    assert refusals.code_for(503, "maps_paused") == "maps_paused"
    assert refusals.code_for(403, "not_allowed") == "not_allowed"

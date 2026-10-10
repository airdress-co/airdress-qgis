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


def test_a_waitlisted_account_is_told_so_not_asked_to_sign_in():
    # The hub answers 403 not_admitted at /api/maps/token for an account that
    # is signed in but not past the waitlist.
    assert refusals.code_for(403, "not_admitted") == "not_admitted"
    assert "waitlist" in refusals.sentence("not_admitted", "en")
    assert "Warteliste" in refusals.sentence("not_admitted", "de_DE")

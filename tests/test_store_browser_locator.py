"""The auth-DB store, the browser panel and the locator filter."""

import uuid

import pytest

pytest.importorskip("qgis.core")

from .conftest_plugin import sign_in


def test_the_refresh_token_round_trips_through_the_encrypted_auth_db(qgis_app):
    from qgis.core import QgsApplication

    from airdress_qgis.auth.store import AuthDbStore

    manager = QgsApplication.authManager()
    if not manager.masterPasswordIsSet():
        assert manager.setMasterPassword("test-master-password", True)
    store = AuthDbStore("airdress/test-" + uuid.uuid4().hex)
    assert store.load() is None
    assert store.save("rt-secret")
    assert store.load() == "rt-secret"
    store.delete()
    assert store.load() is None
    store.delete()  # deleting nothing is fine


def test_the_browser_root_offers_both_layers_and_adds_on_double_click(wired):
    from airdress_qgis.browser import AirdressItemProvider

    added = []
    wired.add_layer = added.append
    provider = AirdressItemProvider(wired)
    assert provider.name() == "Airdress" and provider.dataProviderKey() == "airdress"
    assert provider.createDataItem("somewhere/else", None) is None
    root = provider.createDataItem("", None)
    children = root.createChildren()
    assert [c.name() for c in children] == ["Basemap", "Boundaries"]
    assert all(not c.hasDragEnabled() for c in children)
    assert children[1].handleDoubleClick() is True
    assert added == ["boundaries"]


def _run(filt, text):
    from qgis.core import QgsFeedback, QgsLocatorContext

    found = []
    filt.resultFetched.connect(found.append)
    filt.fetchResults(text, QgsLocatorContext(), QgsFeedback())
    return found


def test_the_locator_lists_results_with_their_credit(wired):
    from airdress_qgis.search.locator import ADD_TO_SCRATCH, AirdressLocatorFilter

    sign_in(wired)
    asked = []
    wired.call_json = lambda url, body, feedback=None: (
        asked.append(body)
        or (
            200,
            {
                "results": [
                    {
                        "name": "München",
                        "address": {"state": "Bayern"},
                        "point": [11.57, 48.13],
                        "layer": "locality",
                        "credit": "GeoNames",
                    }
                ]
            },
        )
    )
    filt = AirdressLocatorFilter(wired)
    assert (filt.name(), filt.prefix(), filt.displayName()) == ("airdress", "ad", "Airdress search")
    assert isinstance(filt.clone(), AirdressLocatorFilter)
    (result,) = _run(filt, "munich")
    assert result.displayString == "München" and result.description == "Bayern — GeoNames"
    assert asked == [{"text": "munich", "autocomplete": True, "limit": 8, "lang": "en"}]

    went, scratched = [], []
    wired.go_to, wired.add_to_scratch = went.append, scratched.append
    filt.triggerResult(result)
    filt.triggerResultFromAction(result, ADD_TO_SCRATCH)
    assert went[0]["name"] == "München" and scratched[0]["lon"] == 11.57


def test_the_locator_asks_nothing_when_signed_out_or_too_short(wired):
    from airdress_qgis.search.locator import AirdressLocatorFilter

    asked = []
    wired.call_json = lambda *a, **k: asked.append(a) or (200, {"results": []})
    filt = AirdressLocatorFilter(wired)
    assert _run(filt, "munich") == []
    sign_in(wired)
    assert _run(filt, "mu") == []
    assert asked == []

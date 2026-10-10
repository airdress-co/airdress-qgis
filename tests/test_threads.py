"""The GUI is touched only on the main thread.

QGIS runs locator searches on a worker thread. A message pushed from there
creates a message-bar widget off the main thread, and QGIS 3.40 then died
in the bar's animation (signal 11, 2026-10-10). Every message the plugin
shows goes through `report_answer`, which hands an off-thread call to the
main thread.
"""

import threading

import pytest

pytest.importorskip("qgis.core")


def _plugin(qgis_app):
    from qgis.testing.mocked import get_iface

    import airdress_qgis

    iface = get_iface()
    shown = []
    iface.messageBar().pushMessage.side_effect = lambda *a, **k: shown.append(threading.current_thread())
    plugin = airdress_qgis.classFactory(iface)
    return plugin, shown


def test_a_refusal_reported_from_a_worker_thread_is_shown_on_the_main_thread(qgis_app):
    from qgis.PyQt.QtCore import QCoreApplication

    plugin, shown = _plugin(qgis_app)
    worker = threading.Thread(
        target=plugin.report_answer, args=(503, {"error": "geocoder_starting", "retry_after": 15})
    )
    worker.start()
    worker.join(5)
    assert shown == [], "the worker thread touched the message bar"
    for _ in range(20):
        QCoreApplication.processEvents()
    assert shown == [threading.main_thread()]


def test_a_search_that_is_refused_never_touches_the_gui_from_its_thread(qgis_app):
    from qgis.core import QgsFeedback, QgsLocatorContext
    from qgis.PyQt.QtCore import QCoreApplication

    from airdress_qgis.search.locator import AirdressLocatorFilter

    plugin, shown = _plugin(qgis_app)
    plugin.session._restored = True
    plugin.session._refresh = "rt"  # signed in, as far as the filter can tell
    plugin.call_json = lambda url, body, feedback=None: (503, {"error": "geocoder_starting", "retry_after": 15})
    filt = AirdressLocatorFilter(plugin)
    worker = threading.Thread(target=filt.fetchResults, args=("munich", QgsLocatorContext(), QgsFeedback()))
    worker.start()
    worker.join(5)
    assert shown == []
    for _ in range(20):
        QCoreApplication.processEvents()
    assert shown == [threading.main_thread()]


def test_no_python_callback_rides_on_qgis_network_replies(qgis_app):
    plugin, _ = _plugin(qgis_app)
    plugin.initGui()
    try:
        assert not hasattr(plugin, "watcher")
    finally:
        plugin.unload()

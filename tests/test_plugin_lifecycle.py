"""Load and unload the plugin against QGIS's mocked iface."""

import pytest

pytest.importorskip("qgis.core")


def test_init_and_unload_leave_nothing_behind(qgis_app):
    from qgis.core import QgsApplication
    from qgis.testing.mocked import get_iface

    import airdress_qgis

    iface = get_iface()
    processing_before = len(QgsApplication.processingRegistry().providers())
    providers_before = [p.name() for p in QgsApplication.dataItemProviderRegistry().providers()]

    plugin = airdress_qgis.classFactory(iface)
    plugin.initGui()
    assert "Airdress" in [p.name() for p in QgsApplication.dataItemProviderRegistry().providers()]
    assert plugin.attacher._id is not None
    iface.registerLocatorFilter.assert_called_once()
    # Loading touched neither the network nor the auth database.
    assert plugin.session._restored is False

    plugin.unload()
    assert [p.name() for p in QgsApplication.dataItemProviderRegistry().providers()] == providers_before
    assert plugin.attacher._id is None
    assert len(QgsApplication.processingRegistry().providers()) == processing_before
    assert plugin.credentials.hosts() == []

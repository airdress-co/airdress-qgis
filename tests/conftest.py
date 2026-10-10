import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qgis_app():
    # A throwaway profile, so tests never read or write the developer's own
    # QGIS settings or auth database.
    profile = tempfile.mkdtemp(prefix="airdress-qgis-test-")
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = profile
    from qgis.core import QgsApplication

    app = QgsApplication([], False, profile)
    app.initQgis()
    yield app
    app.exitQgis()

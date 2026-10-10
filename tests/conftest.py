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
    # No exitQgis(): QGIS's teardown under Python segfaults at interpreter
    # exit (measured in the 3.44 and 4.2 images: 34 passed, then exit 139).
    # pytest_unconfigure below ends the process with pytest's own status.


_status = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    # The last hook, after the summary and every failure report are printed.
    if "qgis.core" in __import__("sys").modules:
        import os
        import sys

        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_status["code"])


from .conftest_plugin import wired  # noqa: F401

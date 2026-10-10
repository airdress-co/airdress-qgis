"""Layers, the preprocessor and projects, inside a real (headless) QGIS."""

import glob
import os
import pathlib
import zipfile

import pytest

pytest.importorskip("qgis.core")

from .test_style import STYLE

SECRET = "maps-SECRET-TOKEN-1234567890"


@pytest.fixture
def current():
    from airdress_qgis.maps.current import parse

    return lambda snap: parse(
        {
            "style": f"/static/styles/{snap}/a.json",
            "snapshot": snap,
            "tiles": {
                "basemap": f"/tiles/basemap/{snap}/{{z}}/{{x}}/{{y}}.mvt",
                "boundaries": "/tiles/boundaries/overture-1/{z}/{x}/{y}.mvt",
            },
        },
        "https://maps.airdress.co",
    )


def test_basemap_converts_and_carries_no_credential(qgis_app, current):
    from airdress_qgis.maps import layers

    layer, _warnings = layers.basemap(current("s1"), STYLE, lambda url: (404, b""))
    assert layer.isValid()
    assert layer.renderer() is not None
    assert "/s1/" in layers.template_of(layer.source())
    assert "Authorization" not in layer.source() and "http-header" not in layer.source()
    assert layers.kind_of(layer) == "basemap"
    assert "OpenStreetMap" in " ".join(layer.metadata().rights())


def test_boundaries_layer_draws_counties_and_municipalities(qgis_app, current):
    from airdress_qgis.maps import layers

    layer = layers.boundaries(current("s1"))
    assert layer.isValid()
    names = [s.styleName() for s in layer.renderer().styles()]
    assert names == ["county", "municipality"]
    assert layers.kind_of(layer) == "boundaries"


def test_preprocessor_attaches_only_for_the_exact_host(qgis_app):
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    from airdress_qgis.auth.credentials import Credentials
    from airdress_qgis.net import Attacher

    creds = Credentials()
    creds.set("https://maps.airdress.co", SECRET)
    attach = Attacher(creds)

    ours = QNetworkRequest(QUrl("https://maps.airdress.co/tiles/basemap/s1/1/0/0.mvt"))
    attach(ours)
    assert bytes(ours.rawHeader(b"Authorization")) == b"Bearer " + SECRET.encode()

    theirs = QNetworkRequest(QUrl("https://tile.example.org/1/0/0.png"))
    attach(theirs)
    assert not theirs.hasRawHeader(b"Authorization")

    preset = QNetworkRequest(QUrl("https://maps.airdress.co/x"))
    preset.setRawHeader(b"Authorization", b"Bearer other")
    attach(preset)
    assert bytes(preset.rawHeader(b"Authorization")) == b"Bearer other"

    attach.install()
    attach.install()  # idempotent
    attach.remove()


def test_saved_project_reopens_on_the_current_snapshot_and_holds_no_token(qgis_app, current, tmp_path):
    from qgis.core import QgsApplication, QgsProject, QgsSettings

    from airdress_qgis.auth.credentials import Credentials
    from airdress_qgis.maps import layers
    from airdress_qgis.project import airdress_layers, repoint

    logged = []
    QgsApplication.messageLog().messageReceived.connect(lambda m, t, l: logged.append(m))

    Credentials().set("https://maps.airdress.co", SECRET)  # a token is live in the process
    project = QgsProject.instance()
    project.clear()
    base, _ = layers.basemap(current("s1"), STYLE, lambda url: (404, b""))
    project.addMapLayer(base)
    project.addMapLayer(layers.boundaries(current("s1")))
    path = str(tmp_path / "p.qgz")
    assert project.write(path)

    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            assert SECRET.encode() not in z.read(name), name

    project.clear()
    assert project.read(path)
    found = airdress_layers(project)
    assert sorted(layers.kind_of(l) for l in found) == ["basemap", "boundaries"]
    assert repoint(found, current("s2")) == 1  # the basemap moved, boundaries did not
    assert all("/s1/" not in layers.template_of(l.source()) for l in found if layers.kind_of(l) == "basemap")
    assert repoint(found, current("s2")) == 0
    # Re-pointing kept the converted style.
    assert next(l for l in found if layers.kind_of(l) == "basemap").renderer() is not None

    QgsSettings().sync()
    for ini in glob.glob(os.path.join(os.environ["QGIS_CUSTOM_CONFIG_PATH"], "**", "*.ini"), recursive=True):
        assert SECRET not in pathlib.Path(ini).read_text(encoding="utf-8", errors="replace"), ini
    assert not any(SECRET in m for m in logged)
    project.clear()


def test_no_processing_provider_is_registered(qgis_app):
    import pathlib

    import airdress_qgis

    package = pathlib.Path(airdress_qgis.__file__).parent
    for source in package.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "QgsProcessingProvider" not in text, source
        assert "processingRegistry" not in text, source


def test_template_of_decodes_the_source_on_every_qgis(qgis_app):
    from airdress_qgis.maps import layers

    template = "https://maps.airdress.co/tiles/basemap/s1/{z}/{x}/{y}.mvt"
    assert layers.template_of(layers.source_uri(template, "basemap")) == template

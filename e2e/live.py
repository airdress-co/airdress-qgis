"""The plugin against the live service, in a real QGIS with no window.

Signs in through the plugin's own dialog, adds the basemap and draws it,
searches, saves and reopens a project, signs out, and proves the grant is
gone. Each step prints one line:

    STEP <name> ok|fail <detail>

and the process exits 0 only when every step passed.

Run it from the repository root inside a QGIS install or image:

    QT_QPA_PLATFORM=offscreen python3 e2e/live.py

By default the sign-in opens your browser, as the plugin does for anyone.
With `--print-authorize-url` it prints `AUTHORIZE <url>` instead and
waits, so a browser automation can complete the sign-in: the redirect
comes back to the plugin's own loopback listener either way.

`AIRDRESS_LIVE_OUT=<dir>` keeps the rendered map images there.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Munich, searched for from a map showing Berlin: the answer must not lean on
# where the map is looking.
MUNICH = (11.5755, 48.1372)
BERLIN = (13.4050, 52.5200)
HAMBURG = (9.9937, 53.5511)
VIENNA = (16.3725, 48.2085)
SEARCH = "air munich"
NEAR_KM = 25.0

SIGN_IN_TIMEOUT_S = 180
SEARCH_TIMEOUT_S = 45

# A map drawn on this background shows the background only where nothing
# was drawn. No basemap style uses it.
BLANK = (255, 0, 255)


class Failed(Exception):
    pass


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"STEP {name} {'ok' if ok else 'fail'} {detail}".rstrip(), flush=True)
    if not ok:
        raise Failed(f"{name}: {detail}")


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def start_qgis():
    profile = tempfile.mkdtemp(prefix="airdress-qgis-live-")
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = profile
    from qgis.core import QgsApplication
    from qgis.testing import start_app

    # Through start_app, not a QgsApplication of our own: the mocked iface
    # calls start_app too, and a second application resets the auth manager
    # (the master password set below was lost, measured on 3.44).
    app = start_app(cleanup=False)
    # A master password on the throwaway profile, so the refresh token is
    # stored encrypted the way it is for a person who set one.
    QgsApplication.authManager().setMasterPassword("live-check-throwaway", True)
    return app


class TileCounter:
    """Every reply from the map service's tile route, by HTTP status. QGIS
    relays replies from its render threads to the main-thread manager."""

    def __init__(self, origin: str):
        from qgis.core import QgsNetworkAccessManager

        self.prefix = origin + "/tiles/"
        self.statuses: dict[int, int] = {}
        QgsNetworkAccessManager.instance().finished.connect(self._finished)

    def _finished(self, content) -> None:
        from qgis.PyQt.QtNetwork import QNetworkRequest

        if not content.request().url().toString().startswith(self.prefix):
            return
        status = content.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        key = int(status) if status is not None else 0
        self.statuses[key] = self.statuses.get(key, 0) + 1

    def reset(self) -> None:
        self.statuses = {}

    def text(self) -> str:
        return ",".join(f"{k}x{v}" for k, v in sorted(self.statuses.items())) or "none"


def render(layer, centre: tuple[float, float], zoom: int, size: int = 512):
    """Draw one layer the way a print or an export would."""
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsMapRendererSequentialJob,
        QgsMapSettings,
        QgsPointXY,
        QgsProject,
        QgsRectangle,
    )
    from qgis.PyQt.QtCore import QCoreApplication, QSize
    from qgis.PyQt.QtGui import QColor

    mercator = QgsCoordinateReferenceSystem("EPSG:3857")
    to_mercator = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), mercator, QgsProject.instance())
    point = to_mercator.transform(QgsPointXY(*centre))
    half = 40075016.686 / (2**zoom) * (size / 256) / 2
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(mercator)
    settings.setOutputSize(QSize(size, size))
    settings.setExtent(QgsRectangle(point.x() - half, point.y() - half, point.x() + half, point.y() + half))
    settings.setBackgroundColor(QColor(*BLANK))
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    QCoreApplication.processEvents()
    return job.renderedImage()


def drawn(image) -> tuple[float, int]:
    """(share of pixels drawn on, distinct colours among them), sampled."""
    from qgis.PyQt.QtGui import QColor

    blank = QColor(*BLANK).rgb() & 0xFFFFFF
    total = painted = 0
    colours = set()
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            rgb = image.pixel(x, y) & 0xFFFFFF
            total += 1
            if rgb != blank:
                painted += 1
                colours.add(rgb)
    return (painted / total if total else 0.0), len(colours)


def keep(image, name: str) -> None:
    out = os.environ.get("AIRDRESS_LIVE_OUT")
    if out:
        os.makedirs(out, exist_ok=True)
        image.save(os.path.join(out, name))


def search(plugin, text: str, near: tuple[float, float]) -> list:
    """Run the plugin's filter through QGIS's own locator, which runs it on
    a worker thread exactly as the locator bar does."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsLocator, QgsLocatorContext, QgsLocatorResult, QgsRectangle
    from qgis.PyQt.QtCore import QEventLoop, QTimer

    from airdress_qgis.search.locator import AirdressLocatorFilter

    locator = QgsLocator()
    locator.registerFilter(AirdressLocatorFilter(plugin))
    context = QgsLocatorContext()
    context.targetExtent = QgsRectangle(near[0] - 0.3, near[1] - 0.2, near[0] + 0.3, near[1] + 0.2)
    context.targetExtentCrs = QgsCoordinateReferenceSystem("EPSG:4326")
    results: list = []
    loop = QEventLoop()
    ended = {"finished": False}
    locator.finished.connect(lambda: ended.update(finished=True))
    # Copy each result inside the slot: the signal hands over a temporary,
    # and keeping that reference reads freed memory afterwards (empty data on
    # 3.44, a crash on 4.2). QGIS's own locator model copies the same way.
    locator.foundResult.connect(lambda result: results.append(QgsLocatorResult(result)))
    locator.finished.connect(loop.quit)
    QTimer.singleShot(SEARCH_TIMEOUT_S * 1000, loop.quit)
    locator.fetchResults(text, context)
    started = time.monotonic()
    if not ended["finished"]:  # a filter run on the main thread is done already
        loop.exec()
    if not ended["finished"]:
        print(f"search: no finished signal after {time.monotonic() - started:.0f}s", flush=True)
    locator.cancelWithoutBlocking()
    return results


def messages(iface) -> list[str]:
    return [str(c.args[1]) for c in iface.messageBar().pushMessage.call_args_list]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print-authorize-url", action="store_true")
    args = parser.parse_args()

    start_qgis()

    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
    from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSlot
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QApplication
    from qgis.testing.mocked import get_iface

    import airdress_qgis
    from airdress_qgis import config
    from airdress_qgis.auth.oauth import OAuthError
    from airdress_qgis.auth.store import AuthDbStore
    from airdress_qgis.maps import layers

    class Handoff(QObject):
        """Where the plugin's 'open the browser' goes in an automated run."""

        @pyqtSlot(QUrl)
        def open(self, url: QUrl) -> None:
            print("AUTHORIZE " + url.toString(QUrl.ComponentFormattingOption.FullyEncoded), flush=True)

    handoff = Handoff()
    if args.print_authorize_url:
        QDesktopServices.setUrlHandler("https", handoff, "open")

    iface = get_iface()
    # The canvas a person has: a CRS, a size, and a view (Berlin). Without an
    # extent a canvas has no scale, and "go to" lands on infinity.
    canvas = iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    iface.mainWindow().resize(1000, 700)
    canvas.resize(800, 600)
    canvas.setExtent(
        QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), canvas.mapSettings().destinationCrs(), QgsProject.instance()
        ).transformBoundingBox(QgsRectangle(BERLIN[0] - 0.3, BERLIN[1] - 0.2, BERLIN[0] + 0.3, BERLIN[1] + 0.2))
    )
    plugin = airdress_qgis.classFactory(iface)
    plugin.initGui()
    tiles = TileCounter(config.MAPS_ORIGIN)
    project = QgsProject.instance()
    refresh = None

    try:
        # 1. Sign in, through the plugin's own dialog and loopback listener.
        def give_up() -> None:
            dialog = QApplication.activeModalWidget()
            if dialog is not None:
                dialog.reject()

        QTimer.singleShot(SIGN_IN_TIMEOUT_S * 1000, give_up)
        started = time.monotonic()
        signed_in = plugin.sign_in()
        refresh = plugin.session._refresh
        step(
            "sign-in",
            signed_in and plugin.credentials.for_url(config.MAPS_ORIGIN + "/current.json") is not None,
            f"{time.monotonic() - started:.1f}s maps-token={'held' if plugin.credentials.for_url(config.MAPS_ORIGIN + '/x') else 'none'} "
            f"messages={messages(iface)}",
        )
        step(
            "refresh-token-stored",
            plugin.session.persisted and AuthDbStore().load() == refresh,
            "encrypted in the QGIS auth database",
        )

        # 2. The basemap, drawn.
        plugin.add_layer("basemap")
        found = [l for l in project.mapLayers().values() if layers.kind_of(l) == "basemap"]
        step("basemap-added", len(found) == 1 and found[0].isValid(), f"layers={len(found)} messages={messages(iface)}")
        basemap = found[0]
        tiles.reset()
        image = render(basemap, MUNICH, 12)
        keep(image, "basemap-munich-z12.png")
        share, colours = drawn(image)
        step(
            "basemap-drawn",
            share > 0.95 and colours >= 8 and tiles.statuses.get(200, 0) > 0 and set(tiles.statuses) == {200},
            f"painted={share:.0%} colours={colours} tiles={tiles.text()}",
        )

        # 2b. The Satellite mosaic and the aerial photos, drawn (WebP tiles).
        plugin.add_layer("imagery")
        found = [l for l in project.mapLayers().values() if layers.kind_of(l) == "imagery"]
        step(
            "satellite-added", len(found) == 1 and found[0].isValid(), f"layers={len(found)} messages={messages(iface)}"
        )
        tiles.reset()
        image = render(found[0], BERLIN, 11)
        keep(image, "satellite-berlin-z11.png")
        share, colours = drawn(image)
        step(
            "satellite-drawn",
            share > 0.95 and colours >= 50 and tiles.statuses.get(200, 0) > 0 and set(tiles.statuses) == {200},
            f"painted={share:.0%} colours={colours} tiles={tiles.text()}",
        )
        plugin.add_aerial()
        aerial = {l.name(): l for l in project.mapLayers().values() if layers.kind_of(l) == "aerial"}
        vienna = aerial.get("Airdress aerial — Vienna")
        step(
            "aerial-added",
            vienna is not None and vienna.isValid(),
            f"layers={sorted(aerial)} messages={messages(iface)}",
        )
        tiles.reset()
        image = render(vienna, VIENNA, 15)
        keep(image, "aerial-vienna-z15.png")
        share, colours = drawn(image)
        canvas.setExtent(
            QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), canvas.mapSettings().destinationCrs(), project
            ).transformBoundingBox(QgsRectangle(VIENNA[0] - 0.02, VIENNA[1] - 0.01, VIENNA[0] + 0.02, VIENNA[1] + 0.01))
        )
        credited = "basemap.at" in plugin.attribution_text()
        step(
            "aerial-drawn",
            share > 0.95
            and colours >= 50
            and tiles.statuses.get(200, 0) > 0
            and set(tiles.statuses) == {200}
            and credited,
            f"painted={share:.0%} colours={colours} tiles={tiles.text()} credited={credited}",
        )

        # 3. Search, from a map looking at Berlin, then go to the top answer.
        results = search(plugin, SEARCH, BERLIN)
        points = [((r.userData() if callable(r.userData) else r.userData) or {}) for r in results]
        near = [i for i, p in enumerate(points[:3]) if km_between((p["lon"], p["lat"]), MUNICH) < NEAR_KM]
        step(
            "search",
            bool(near),
            f"results={len(results)} top={[r.displayString for r in results[:3]]} messages={messages(iface)}",
        )
        plugin.locator.triggerResult(results[near[0]])
        centre = QgsCoordinateTransform(
            canvas.mapSettings().destinationCrs(), QgsCoordinateReferenceSystem("EPSG:4326"), project
        ).transform(canvas.center())
        step("go-to-result", km_between((centre.x(), centre.y()), MUNICH) < NEAR_KM, f"centre={centre.toString(4)}")

        # 4. A saved project reopens with its Airdress layer working.
        path = os.path.join(tempfile.mkdtemp(prefix="airdress-live-project-"), "live.qgz")
        step("project-saved", project.write(path), path)
        source = basemap.source()
        project.clear()
        step("project-read", project.read(path), "")
        reopened = [l for l in project.mapLayers().values() if layers.kind_of(l) == "basemap"]
        step(
            "project-reopened",
            len(reopened) == 1
            and reopened[0].isValid()
            and layers.template_of(reopened[0].source()) == layers.template_of(source),
            f"layers={len(reopened)} messages={messages(iface)}",
        )
        tiles.reset()
        image = render(reopened[0], HAMBURG, 11)
        keep(image, "reopened-hamburg-z11.png")
        share, colours = drawn(image)
        step("reopened-drawn", share > 0.95 and colours >= 8, f"painted={share:.0%} tiles={tiles.text()}")

        # 5. Sign out: the grant is revoked at the hub, not only forgotten.
        plugin.sign_out()
        step(
            "signed-out-locally",
            not plugin.session.signed_in and AuthDbStore().load() is None,
            "",
        )
        try:
            plugin.server.refresh(refresh, config.HUB_RESOURCE)
            revoked, detail = False, "the hub still honours the refresh token"
        except OAuthError as err:
            revoked, detail = True, err.code
        refresh = None
        step("grant-revoked", revoked, detail)

        # 6. Signed out, the map service draws nothing (a place not drawn
        # before, so no cache can answer).
        tiles.reset()
        image = render(reopened[0], (2.3522, 48.8566), 12)
        keep(image, "signed-out-paris-z12.png")
        # The style's background still paints, so "nothing drawn" means no
        # second colour: no tile content reached the map.
        share, colours = drawn(image)
        step(
            "refused-when-signed-out",
            colours <= 1 and tiles.statuses.get(200, 0) == 0 and tiles.statuses.get(403, 0) > 0,
            f"colours={colours} tiles={tiles.text()}",
        )
        return 0
    except Failed:
        return 1
    except Exception as err:  # noqa: BLE001 - any crash in the driver is a failed run, said plainly
        print(f"STEP driver fail {type(err).__name__}: {err}", flush=True)
        return 1
    finally:
        # Never leave a grant behind, whatever failed.
        if plugin.session.signed_in:
            plugin.session.sign_out()
        sys.stdout.flush()


if __name__ == "__main__":
    # QGIS's teardown under Python can crash at interpreter exit; the verdict
    # is already printed, so leave with it.
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)

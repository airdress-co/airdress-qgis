"""The Airdress plugin: sign in, the map, search, attribution.

Lifecycle: nothing touches the network or the auth database at load. The
first sign-in, or opening a project with Airdress layers, starts the
session; a main-thread timer keeps the maps token fresh; the request
preprocessor only ever reads what the timer left behind.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLayoutItemLabel,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgsMapToolEmitPoint, QgsVertexMarker
from qgis.PyQt.QtCore import QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QIcon
from qgis.PyQt.QtWidgets import QMenu, QToolButton

try:  # Qt6 (QGIS 4) moved QAction to QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 (QGIS 3)
    from qgis.PyQt.QtWidgets import QAction

from . import attribution, config, net, refusals
from .auth.credentials import Credentials
from .auth.oauth import AuthorizationServer, NetworkError
from .auth.session import MintRefused, Session, SignedOut
from .auth.store import AuthDbStore
from .browser import AirdressItemProvider
from .maps import current as current_json
from .maps import layers
from .project import airdress_layers, repoint
from .search import geocode
from .search.locator import WGS84, AirdressLocatorFilter, point_in
from .signin import SignInDialog

LOG_TAG = "Airdress"
RETRY_SECONDS = 30
NOTICE_COOLDOWN_SECONDS = 60


def _text_field(name: str) -> QgsField:
    """A string field on Qt5 and Qt6 alike."""
    try:
        from qgis.PyQt.QtCore import QMetaType

        return QgsField(name, QMetaType.Type.QString)
    except (AttributeError, TypeError):
        from qgis.PyQt.QtCore import QVariant

        return QgsField(name, QVariant.String)


class AirdressPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.locale = str(QgsSettings().value("locale/userLocale", "en") or "en")
        self.credentials = Credentials()
        self.server = AuthorizationServer(config.HUB_ISSUER, config.CLIENT_ID, net.post_form)
        self.session = Session(self.server, net.post_form, AuthDbStore(), self.credentials)
        self.attacher = net.Attacher(self.credentials)
        self.watcher = net.Watcher({config.MAPS_ORIGIN.split("://", 1)[1]})
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.renew)
        self._notices: "dict[str, float]" = {}
        self._marker: Optional[QgsVertexMarker] = None
        self._actions: "list[QAction]" = []

    # --- QGIS plugin API --------------------------------------------------

    def initGui(self) -> None:
        self.attacher.install()
        self.watcher.install()
        self.watcher.refused.connect(self.on_refused)

        menu = QMenu("Airdress")
        self.sign_in_action = self._action(menu, "Sign in…", self.sign_in)
        self.sign_out_action = self._action(menu, "Sign out", self.sign_out)
        menu.addSeparator()
        self._action(menu, "Add basemap", lambda: self.add_layer("basemap"))
        self._action(menu, "Add boundaries", lambda: self.add_layer("boundaries"))
        self.whats_here_action = self._action(menu, "What's here?", self.whats_here)
        self.whats_here_action.setCheckable(True)
        self._action(menu, "Add attribution to layout", self.add_layout_attribution)
        menu.addSeparator()
        self._action(menu, "Data and licences", lambda: QDesktopServices.openUrl(QUrl(config.LICENSES_URL)))
        menu.aboutToShow.connect(self._refresh_menu)
        self.menu = menu

        self.button = QToolButton()
        self.button.setIcon(self.icon)
        self.button.setToolTip("Airdress")
        self.button.setMenu(menu)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar_action = self.iface.addToolBarWidget(self.button)
        self.iface.webMenu().addMenu(menu)

        self.locator = AirdressLocatorFilter(self)
        self.iface.registerLocatorFilter(self.locator)
        self.browser = AirdressItemProvider(self)
        QgsApplication.dataItemProviderRegistry().addProvider(self.browser)

        self.tool = QgsMapToolEmitPoint(self.iface.mapCanvas())
        self.tool.canvasClicked.connect(self._reverse)
        self.tool.deactivated.connect(lambda: self.whats_here_action.setChecked(False))

        self.iface.mapCanvas().renderComplete.connect(self._draw_attribution)
        QgsProject.instance().readProject.connect(self.on_project_read)

    def unload(self) -> None:
        self.timer.stop()
        QgsProject.instance().readProject.disconnect(self.on_project_read)
        self.iface.mapCanvas().renderComplete.disconnect(self._draw_attribution)
        self.iface.deregisterLocatorFilter(self.locator)
        QgsApplication.dataItemProviderRegistry().removeProvider(self.browser)
        self.iface.removeToolBarIcon(self.toolbar_action)
        self.iface.webMenu().removeAction(self.menu.menuAction())
        if self.iface.mapCanvas().mapTool() is self.tool:
            self.iface.mapCanvas().unsetMapTool(self.tool)
        self._clear_marker()
        self.watcher.remove()
        self.attacher.remove()
        self.credentials.clear()

    def _action(self, menu: QMenu, text: str, slot) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(slot)
        menu.addAction(action)
        self._actions.append(action)
        return action

    def _refresh_menu(self) -> None:
        signed_in = self.session.signed_in
        self.sign_in_action.setVisible(not signed_in)
        self.sign_out_action.setVisible(signed_in)

    # --- messages -----------------------------------------------------------

    def say(self, code: str, level=Qgis.MessageLevel.Warning, **values) -> None:
        """One sentence, at most once a minute per code."""
        now = time.monotonic()
        if now - self._notices.get(code, -1e9) < NOTICE_COOLDOWN_SECONDS:
            return
        self._notices[code] = now
        self.iface.messageBar().pushMessage("Airdress", refusals.sentence(code, self.locale, **values), level, 8)

    def log(self, text: str) -> None:
        # Never a token, a URL query or a body here.
        QgsMessageLog.logMessage(text, LOG_TAG, Qgis.MessageLevel.Info)

    def report_answer(self, status: int, body) -> None:
        error = body.get("error") if isinstance(body, dict) else None
        code = refusals.code_for(status, error)
        if code == "geocoder_starting":
            self.say(code, seconds=int((body or {}).get("retry_after", 15)))
        else:
            self.say(code)

    # --- session ------------------------------------------------------------

    def sign_in(self) -> bool:
        dialog = SignInDialog(self.server, self.iface.mainWindow())
        dialog.start_browser()
        if not dialog.exec() or dialog.tokens is None:
            return False
        self.session.adopt(dialog.tokens)
        if not self.session.persisted:
            self.say("session_only", Qgis.MessageLevel.Info)
        return self.renew()

    def sign_out(self) -> None:
        self.timer.stop()
        failure = self.session.sign_out()
        if failure is not None:
            self.log("revocation at the hub did not complete; the local session was ended")
        self.iface.messageBar().pushMessage("Airdress", "Signed out.", Qgis.MessageLevel.Info, 4)
        self._repaint()

    def renew(self) -> bool:
        """Make sure a maps token is held; schedule the next renewal."""
        try:
            next_at = self.session.ensure_fresh()
        except SignedOut:
            self.say("signed_out")
            return False
        except MintRefused as err:
            self.report_answer(err.status, {"error": err.code})
            self._schedule(time.time() + RETRY_SECONDS * 10)
            return False
        except NetworkError:
            self.say("network")
            self._schedule(time.time() + RETRY_SECONDS)
            return False
        self._schedule(next_at)
        return True

    def _schedule(self, at: Optional[float]) -> None:
        if at is None:
            return
        self.timer.start(int(max(5.0, at - time.time()) * 1000))

    def ensure_signed_in(self) -> bool:
        if self.session.signed_in and self.renew():
            return True
        return self.sign_in()

    def on_refused(self, status: int, host: str) -> None:
        """A tile or style request from QGIS was refused. Find out why with
        one request of our own (we read the body; QGIS's own replies we never
        touch), then repaint or say so."""
        if status == 403:
            self.session.expire_maps()
            if not self.renew():
                return
        code_status, body = net.get_json(config.MAPS_ORIGIN + "/current.json")
        if code_status == 200:
            if status == 403:
                self._repaint()
            elif status == 429:
                self.say("rate_limited")
            return
        self.report_answer(code_status, body)

    # --- layers -------------------------------------------------------------

    def current(self) -> Optional[current_json.Current]:
        status, body = net.get_json(config.MAPS_ORIGIN + "/current.json")
        if status != 200 or not isinstance(body, dict):
            self.report_answer(status, body)
            return None
        try:
            return current_json.parse(body)
        except current_json.NoTileRoute:
            self.say("generic")
            self.log("/current.json names no tile route: the map service is older than this plugin")
            return None

    def add_layer(self, kind: str) -> None:
        if not self.ensure_signed_in():
            return
        current = self.current()
        if current is None or current.template(kind) is None:
            return
        if kind == "basemap":
            status, published = net.get_json(current.style)
            if status != 200:
                self.report_answer(status, published)
                return
            layer, warnings = layers.basemap(current, published, net.get_bytes)
            self.log(f"style converted with {len(warnings)} warnings")
        else:
            layer = layers.boundaries(current)
        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        root = project.layerTreeRoot()
        if kind == "basemap":
            root.addLayer(layer)  # at the bottom, under the person's data
        else:
            basemap_nodes = [n for n in root.findLayers() if layers.kind_of(n.layer()) == "basemap"]
            index = root.children().index(basemap_nodes[0]) if basemap_nodes else len(root.children())
            root.insertLayer(index, layer)

    def on_project_read(self, *args) -> None:
        found = airdress_layers(QgsProject.instance())
        if not found:
            return
        if not self.session.signed_in:
            self.iface.messageBar().pushMessage(
                "Airdress",
                f"Sign in to Airdress to show {len(found)} layer(s) in this project.",
                Qgis.MessageLevel.Info,
                10,
            )
            return
        if not self.renew():
            return
        current = self.current()
        if current is not None and repoint(found, current):
            self.log("project layers re-pointed at the current map snapshot")

    def _repaint(self) -> None:
        for layer in airdress_layers(QgsProject.instance()):
            layer.triggerRepaint()

    # --- search ---------------------------------------------------------------

    def call_json(self, url: str, body: dict, feedback=None):
        return net.post_json(url, body, None, feedback)

    def _clear_marker(self) -> None:
        if self._marker is not None:
            self.iface.mapCanvas().scene().removeItem(self._marker)
            self._marker = None

    def go_to(self, hit: dict) -> None:
        canvas = self.iface.mapCanvas()
        point = point_in(canvas.mapSettings().destinationCrs(), hit["lon"], hit["lat"])
        canvas.setCenter(point)
        canvas.zoomScale(geocode.scale_for(hit.get("layer", "")))
        self._clear_marker()
        self._marker = QgsVertexMarker(canvas)
        self._marker.setCenter(point)
        self._marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self._marker.setColor(QColor("#e11d48"))
        self._marker.setIconSize(14)
        self._marker.setPenWidth(3)
        QTimer.singleShot(8000, self._clear_marker)

    def add_to_scratch(self, hit: dict) -> None:
        """Explicitly, one result at a time, into a memory layer."""
        project = QgsProject.instance()
        found = [l for l in project.mapLayersByName("Airdress search results") if l.providerType() == "memory"]
        if found:
            layer = found[0]
        else:
            layer = QgsVectorLayer("Point?crs=EPSG:4326", "Airdress search results", "memory")
            layer.dataProvider().addAttributes([_text_field("name"), _text_field("address")])
            layer.updateFields()
            project.addMapLayer(layer)
        feature = QgsFeature(layer.fields())
        feature.setAttributes([hit["name"], hit["address"]])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(hit["lon"], hit["lat"])))
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        layer.triggerRepaint()

    def whats_here(self, checked: bool = True) -> None:
        canvas = self.iface.mapCanvas()
        if checked:
            canvas.setMapTool(self.tool)
        elif canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)

    def _reverse(self, point, button) -> None:
        if not self.ensure_signed_in():
            return
        from qgis.core import QgsCoordinateTransform

        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        wgs = QgsCoordinateTransform(crs, WGS84, QgsProject.instance()).transform(point)
        status, body = self.call_json(config.MAPS_ORIGIN + "/reverse", geocode.reverse_body(wgs.x(), wgs.y()))
        if status != 200:
            self.report_answer(status, body)
            return
        hits = geocode.hits(body)
        text = " — ".join(p for p in (hits[0].name, hits[0].address) if p) if hits else "Nothing found here."
        self.iface.messageBar().pushMessage("Airdress", text, Qgis.MessageLevel.Info, 8)

    # --- attribution ------------------------------------------------------------

    def visible_kinds(self) -> "list[str]":
        root = QgsProject.instance().layerTreeRoot()
        kinds = []
        for node in root.findLayers():
            kind = layers.kind_of(node.layer()) if node.layer() else None
            if kind and node.isVisible() and kind not in kinds:
                kinds.append(kind)
        return kinds

    def _draw_attribution(self, painter) -> None:
        text = attribution.line(self.visible_kinds())
        if not text:
            return
        font = QFont()
        font.setPointSizeF(7.5)
        painter.save()
        painter.setFont(font)
        metrics = painter.fontMetrics()
        device = painter.device()
        width = metrics.horizontalAdvance(text) + 10
        height = metrics.height() + 4
        x = device.width() - width
        y = device.height() - height
        painter.fillRect(x, y, width, height, QColor(255, 255, 255, 200))
        painter.setPen(QColor("#1f2937"))
        painter.drawText(x + 5, y + height - metrics.descent() - 2, text)
        painter.restore()

    def add_layout_attribution(self) -> None:
        designers = self.iface.openLayoutDesigners()
        if not designers:
            self.iface.messageBar().pushMessage(
                "Airdress", "Open a print layout first, then add the attribution.", Qgis.MessageLevel.Info, 6
            )
            return
        layout = designers[-1].layout()
        kinds = self.visible_kinds() or ["basemap"]
        label = QgsLayoutItemLabel(layout)
        label.setText(attribution.line(kinds))
        label.setId("Airdress attribution")
        font = QFont()
        font.setPointSizeF(6)
        try:
            from qgis.core import QgsTextFormat

            text_format = QgsTextFormat.fromQFont(font)
            label.setTextFormat(text_format)
        except (ImportError, AttributeError):  # pragma: no cover
            label.setFont(font)
        label.adjustSizeToText()
        layout.addLayoutItem(label)

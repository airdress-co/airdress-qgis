"""Airdress search in the QGIS locator bar (prefix `ad`)."""

from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsLocatorFilter,
    QgsLocatorResult,
    QgsPointXY,
    QgsProject,
)

from .. import config, refusals
from . import geocode

ADD_TO_SCRATCH = 1
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


class AirdressLocatorFilter(QgsLocatorFilter):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.setFetchResultsDelay(geocode.DEBOUNCE_MS)

    def clone(self):
        return AirdressLocatorFilter(self.plugin)

    def name(self):
        return "airdress"

    def displayName(self):
        return "Airdress search"

    def prefix(self):
        return "ad"

    def flags(self):
        return QgsLocatorFilter.Flag.FlagFast if hasattr(QgsLocatorFilter, "Flag") else 0

    def fetchResults(self, string, context, feedback):
        if not self.plugin.session.signed_in:
            return
        focus = zoom = None
        extent = context.targetExtent
        if not extent.isEmpty():
            to_wgs = QgsCoordinateTransform(context.targetExtentCrs, WGS84, QgsProject.instance())
            wgs = to_wgs.transformBoundingBox(extent)
            centre = wgs.center()
            focus = (centre.x(), centre.y())
            zoom = geocode.zoom_for_width(wgs.width())
        body = geocode.forward_body(string, focus, zoom, refusals.language(self.plugin.locale))
        if body is None or feedback.isCanceled():
            return
        status, answer = self.plugin.call_json(config.MAPS_ORIGIN + "/geocode", body, feedback)
        if feedback.isCanceled():
            return
        if status != 200:
            self.plugin.report_answer(status, answer)
            return
        for hit in geocode.hits(answer):
            result = QgsLocatorResult(self, hit.name, {"name": hit.name, "address": hit.address,
                                                       "lon": hit.lon, "lat": hit.lat, "layer": hit.layer})
            result.description = " — ".join(p for p in (hit.address, hit.credit) if p)
            result.actions = [QgsLocatorResult.ResultAction(ADD_TO_SCRATCH, "Add to scratch layer")]
            self.resultFetched.emit(result)

    def triggerResult(self, result):
        self.plugin.go_to(result.userData())

    def triggerResultFromAction(self, result, action_id):
        if action_id == ADD_TO_SCRATCH:
            self.plugin.add_to_scratch(result.userData())


def point_in(crs, lon: float, lat: float) -> QgsPointXY:
    return QgsCoordinateTransform(WGS84, crs, QgsProject.instance()).transform(QgsPointXY(lon, lat))

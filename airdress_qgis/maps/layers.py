"""Airdress layers as QGIS vector tile layers.

A layer's source names an XYZ template on the map service and nothing
else — no token, no header. The token is attached per request by the
preprocessor, so a saved project holds no secret.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from qgis.core import (
    QgsDataSourceUri,
    QgsFillSymbol,
    QgsLayerMetadata,
    QgsMapBoxGlStyleConversionContext,
    QgsMapBoxGlStyleConverter,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsVectorTileBasicLabeling,
    QgsVectorTileBasicLabelingStyle,
    QgsVectorTileBasicRenderer,
    QgsVectorTileBasicRendererStyle,
    QgsVectorTileLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor, QImage

from .. import attribution, config
from . import style as style_rewrite
from .current import Current

NAMES = {"basemap": "Airdress basemap", "boundaries": "Airdress boundaries"}
MAX_ZOOM = {"basemap": 15, "boundaries": 12}

GetBytes = Callable[[str], "tuple[int, bytes]"]


def source_uri(template: str, kind: str) -> str:
    uri = QgsDataSourceUri()
    uri.setParam("type", "xyz")
    uri.setParam("url", template)
    uri.setParam("zmin", "0")
    uri.setParam("zmax", str(MAX_ZOOM[kind]))
    return bytes(uri.encodedUri()).decode("utf-8")


def kind_of(layer) -> Optional[str]:
    value = layer.customProperty(config.LAYER_PROPERTY)
    return str(value) if value in NAMES else None


def _mark(layer: QgsVectorTileLayer, kind: str) -> None:
    layer.setCustomProperty(config.LAYER_PROPERTY, kind)
    credit = " · ".join(attribution.BY_KIND[kind])
    metadata = QgsLayerMetadata()
    metadata.setRights([credit])
    metadata.setLicenses([config.LICENSES_URL])
    metadata.setAbstract(f"{NAMES[kind]} from {config.MAPS_ORIGIN}. Credits and licences: {config.LICENSES_URL}")
    layer.setMetadata(metadata)
    try:  # QGIS ≥ 3.22: what QGIS Server and layouts read
        layer.serverProperties().setAttribution(credit)
        layer.serverProperties().setAttributionUrl(config.LICENSES_URL)
    except AttributeError:  # pragma: no cover
        pass


def basemap(current: Current, published_style: dict, get_bytes: GetBytes) -> "tuple[QgsVectorTileLayer, list[str]]":
    """The basemap, converted from the live style. Returns the layer and the
    converter's warnings (kept for the debug view, never shown as errors)."""
    template = current.template("basemap")
    layer = QgsVectorTileLayer(source_uri(template, "basemap"), NAMES["basemap"])
    rewritten = style_rewrite.for_qgis(published_style, template)
    converter = QgsMapBoxGlStyleConverter()
    context = QgsMapBoxGlStyleConversionContext()
    _load_sprites(context, rewritten, get_bytes)
    converter.convert(rewritten, context)
    if converter.renderer() is not None:
        layer.setRenderer(converter.renderer())
    if converter.labeling() is not None:
        layer.setLabeling(converter.labeling())
    _mark(layer, "basemap")
    return layer, list(converter.warnings())


def _load_sprites(context, style: dict, get_bytes: GetBytes) -> None:
    for json_url, png_url in style_rewrite.sprite_urls(style):
        status, raw = get_bytes(json_url)
        if status != 200:
            continue
        status_png, png = get_bytes(png_url)
        if status_png != 200:
            continue
        image = QImage()
        if image.loadFromData(png) and not image.isNull():
            context.setSprites(image, json.loads(raw.decode("utf-8")))
            return


# Counties and municipalities: the lines the basemap does not draw. Country
# and region lines stay the basemap's own (as on the page).
_LINES = [
    # (style name, subtypes, min zoom, colour, width mm)
    ("county", ("county", "macrocounty"), 6, "#6b7280", 0.35),
    ("municipality", ("localadmin", "locality"), 9, "#9ca3af", 0.25),
]


def boundaries(current: Current) -> QgsVectorTileLayer:
    template = current.template("boundaries")
    layer = QgsVectorTileLayer(source_uri(template, "boundaries"), NAMES["boundaries"])
    renderer = QgsVectorTileBasicRenderer()
    styles = []
    for name, subtypes, min_zoom, colour, width in _LINES:
        s = QgsVectorTileBasicRendererStyle(name, "areas", QgsWkbTypes.GeometryType.PolygonGeometry)
        s.setFilterExpression("\"subtype\" IN (%s)" % ", ".join(f"'{t}'" for t in subtypes))
        s.setMinZoomLevel(min_zoom)
        s.setSymbol(
            QgsFillSymbol.createSimple(
                {"style": "no", "outline_color": colour, "outline_width": str(width), "outline_style": "dash"}
            )
        )
        styles.append(s)
    renderer.setStyles(styles)
    layer.setRenderer(renderer)

    labeling = QgsVectorTileBasicLabeling()
    settings = QgsPalLayerSettings()
    settings.fieldName = "name"
    text = QgsTextFormat()
    text.setColor(QColor("#4b5563"))
    text.setSize(8)
    settings.setFormat(text)
    label = QgsVectorTileBasicLabelingStyle()
    label.setStyleName("area names")
    label.setLayerName("labels")
    label.setGeometryType(QgsWkbTypes.GeometryType.PointGeometry)
    label.setMinZoomLevel(9)
    label.setLabelSettings(settings)
    labeling.setStyles([label])
    layer.setLabeling(labeling)

    _mark(layer, "boundaries")
    return layer

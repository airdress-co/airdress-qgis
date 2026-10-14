"""Airdress layers: vector tile layers for the map, XYZ raster layers for
the Satellite mosaic and the aerial photos.

A layer's source names an XYZ template on the map service and nothing
else — no token, no header. The token is attached per request by the
preprocessor, so a saved project holds no secret.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from qgis.core import (
    QgsDataSourceUri,
    QgsFillSymbol,
    QgsLayerMetadata,
    QgsMapBoxGlStyleConversionContext,
    QgsMapBoxGlStyleConverter,
    QgsPalLayerSettings,
    QgsRasterLayer,
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
from .current import Aerial, Current

NAMES = {
    "basemap": "Airdress basemap",
    "boundaries": "Airdress boundaries",
    "imagery": "Airdress satellite",
    "aerial": "Airdress aerial",
}
MAX_ZOOM = {"basemap": 15, "boundaries": 12, "imagery": 14}
RASTER = ("imagery", "aerial")
# Which aerial archive a layer draws, beside its kind.
AERIAL_PROPERTY = config.PREFIX + "aerial"
# The layer's own credit, for the kinds whose credit is not a constant.
CREDIT_PROPERTY = config.PREFIX + "credit"
# An aerial layer's photo box, `w,s,e,n` in degrees: its credit is named
# only while the box is in view.
BOUNDS_PROPERTY = config.PREFIX + "bounds"

GetBytes = Callable[[str], "tuple[int, bytes]"]


def source_uri(template: str, kind: str, zmin: int = 0, zmax: int | None = None) -> str:
    uri = QgsDataSourceUri()
    uri.setParam("type", "xyz")
    uri.setParam("url", template)
    uri.setParam("zmin", str(zmin))
    uri.setParam("zmax", str(MAX_ZOOM[kind] if zmax is None else zmax))
    return bytes(uri.encodedUri()).decode("utf-8")


def template_of(source: str) -> str:
    """The XYZ template a vector tile source names, decoded."""
    uri = QgsDataSourceUri()
    uri.setEncodedUri(source)
    return uri.param("url")


def kind_of(layer) -> str | None:
    value = layer.customProperty(config.LAYER_PROPERTY)
    return str(value) if value in NAMES else None


def aerial_id_of(layer) -> str | None:
    value = layer.customProperty(AERIAL_PROPERTY)
    return str(value) if value else None


def credit_of(layer) -> list[str]:
    """What this layer must credit, one item per source."""
    kind = kind_of(layer)
    if kind == "aerial":
        value = layer.customProperty(CREDIT_PROPERTY)
        return [str(value)] if value else []
    return list(attribution.BY_KIND.get(kind, []))


def _mark(layer, kind: str, credit_items: list[str] | None = None) -> None:
    layer.setCustomProperty(config.LAYER_PROPERTY, kind)
    credit = " · ".join(credit_items if credit_items is not None else attribution.BY_KIND[kind])
    metadata = QgsLayerMetadata()
    metadata.setRights([credit])
    metadata.setLicenses([config.LICENSES_URL])
    metadata.setAbstract(f"{layer.name()} from {config.MAPS_ORIGIN}. Credits and licences: {config.LICENSES_URL}")
    layer.setMetadata(metadata)
    try:  # QGIS ≥ 3.22: what QGIS Server and layouts read
        layer.serverProperties().setAttribution(credit)
        layer.serverProperties().setAttributionUrl(config.LICENSES_URL)
    except AttributeError:  # pragma: no cover
        pass


def basemap(current: Current, published_style: dict, get_bytes: GetBytes) -> tuple[QgsVectorTileLayer, list[str]]:
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
        s.setFilterExpression('"subtype" IN ({})'.format(", ".join(f"'{t}'" for t in subtypes)))
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


def imagery(current: Current) -> QgsRasterLayer:
    """The Satellite mosaic, drawn to its last zoom and enlarged past it."""
    template = current.template("imagery")
    layer = QgsRasterLayer(source_uri(template, "imagery"), NAMES["imagery"], "wms")
    _mark(layer, "imagery")
    return layer


def aerial(entry: Aerial, locale: str = "en") -> QgsRasterLayer:
    """One aerial archive: only from its first zoom, so a zoomed-out map
    asks for none of its tiles, and enlarged past its last."""
    layer = QgsRasterLayer(
        source_uri(entry.tiles, "aerial", entry.minzoom, entry.maxzoom),
        f"{NAMES['aerial']} — {entry.place}",
        "wms",
    )
    credit = attribution.aerial(entry, locale)
    layer.setCustomProperty(AERIAL_PROPERTY, entry.id)
    layer.setCustomProperty(CREDIT_PROPERTY, credit)
    layer.setCustomProperty(BOUNDS_PROPERTY, ",".join(str(b) for b in entry.bounds))
    _mark(layer, "aerial", [credit])
    return layer

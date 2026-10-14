"""Projects survive a snapshot change.

Saved layer sources carry the snapshot that was current when they were
saved; the front serves only today's, so on project load every Airdress
layer is pointed at today's template from /current.json. The person's own
style edits are kept: only the source changes. An aerial layer moves to
today's archive of the same place (a newer flight of the same city); one
whose place the map no longer has is left as it is, and draws nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

from qgis.core import QgsDataProvider, QgsProject

from .maps import layers
from .maps.current import Current


def airdress_layers(project: QgsProject) -> list:
    return [layer for layer in project.mapLayers().values() if layers.kind_of(layer)]


def _target(layer, kind: str, current: Current) -> str | None:
    """The source this layer should have today, or None to leave it."""
    if kind == "aerial":
        archive = layers.aerial_id_of(layer)
        entry = current.aerial_for(archive) if archive else None
        if entry is None:
            return None
        if entry.id != archive:
            layer.setCustomProperty(layers.AERIAL_PROPERTY, entry.id)
        return layers.source_uri(entry.tiles, "aerial", entry.minzoom, entry.maxzoom)
    template = current.template(kind)
    return layers.source_uri(template, kind) if template else None


def repoint(project_layers: Iterable, current: Current) -> int:
    """Re-source each Airdress layer whose template moved. Returns how many."""
    moved = 0
    for layer in project_layers:
        kind = layers.kind_of(layer)
        uri = _target(layer, kind, current) if kind else None
        if uri is None:
            continue
        # Compare the decoded tile URL: QGIS 4 percent-encodes it inside the
        # source string and QGIS 3 does not, so raw strings never match on 4.
        if layers.template_of(layer.source()) == layers.template_of(uri):
            continue
        layer.setDataSource(uri, layer.name(), layer.providerType(), QgsDataProvider.ProviderOptions())
        moved += 1
    return moved

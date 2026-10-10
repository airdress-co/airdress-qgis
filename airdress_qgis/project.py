"""Projects survive a snapshot change.

Saved layer sources carry the snapshot that was current when they were
saved; the front serves only today's, so on project load every Airdress
layer is pointed at today's template from /current.json. The person's own
style edits are kept: only the source changes.
"""

from __future__ import annotations

from collections.abc import Iterable

from qgis.core import QgsDataProvider, QgsProject

from .maps import layers
from .maps.current import Current


def airdress_layers(project: QgsProject) -> list:
    return [layer for layer in project.mapLayers().values() if layers.kind_of(layer)]


def repoint(project_layers: Iterable, current: Current) -> int:
    """Re-source each Airdress layer whose template moved. Returns how many."""
    moved = 0
    for layer in project_layers:
        kind = layers.kind_of(layer)
        template = current.template(kind) if kind else None
        if template is None:
            continue
        uri = layers.source_uri(template, kind)
        if layer.source() == uri:
            continue
        layer.setDataSource(uri, layer.name(), layer.providerType(), QgsDataProvider.ProviderOptions())
        moved += 1
    return moved

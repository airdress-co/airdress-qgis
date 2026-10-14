"""The "Airdress" root in the QGIS Browser panel."""

from __future__ import annotations

from qgis.core import Qgis, QgsDataCollectionItem, QgsDataItem, QgsDataItemProvider

from .maps.layers import NAMES

LABELS = {"aerial": "Aerial photos"}


class _Leaf(QgsDataItem):
    def __init__(self, parent, plugin, kind: str):
        super().__init__(
            Qgis.BrowserItemType.Custom,
            parent,
            LABELS.get(kind, NAMES[kind].replace("Airdress ", "").capitalize()),
            "airdress:/" + kind,
            "airdress",
        )
        self.plugin = plugin
        self.kind = kind
        self.setState(Qgis.BrowserItemState.Populated)
        self.setIcon(plugin.icon)

    def hasDragEnabled(self):
        return False

    def handleDoubleClick(self):
        if self.kind == "aerial":
            self.plugin.add_aerial()
        else:
            self.plugin.add_layer(self.kind)
        return True


class _Root(QgsDataCollectionItem):
    def __init__(self, parent, plugin):
        super().__init__(parent, "Airdress", "airdress:", "airdress")
        self.plugin = plugin
        self.setIcon(plugin.icon)

    def createChildren(self):
        return [_Leaf(self, self.plugin, kind) for kind in ("basemap", "boundaries", "imagery", "aerial")]


class AirdressItemProvider(QgsDataItemProvider):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def name(self):
        return "Airdress"

    def dataProviderKey(self):
        return "airdress"

    def capabilities(self):
        return Qgis.DataItemProviderCapability.NetworkSources

    def createDataItem(self, path, parent):
        if not path:
            return _Root(parent, self.plugin)
        return None

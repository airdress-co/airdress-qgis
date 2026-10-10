"""Airdress for QGIS."""


def classFactory(iface):  # noqa: N802 - QGIS plugin entry point
    from .plugin import AirdressPlugin

    return AirdressPlugin(iface)

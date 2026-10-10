"""Airdress for QGIS."""


def classFactory(iface):
    from .plugin import AirdressPlugin

    return AirdressPlugin(iface)

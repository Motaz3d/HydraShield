"""Talaix Climate Intelligence — QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 — QGIS-required name
    from .hydrashield_plugin import TalaixPlugin

    return TalaixPlugin(iface)

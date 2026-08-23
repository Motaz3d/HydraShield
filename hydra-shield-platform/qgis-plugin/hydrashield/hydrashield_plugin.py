"""Talaix Climate Intelligence — plugin class.

Registers the Processing provider (the engine) and the hazard-browser
dock (the interactive surface). All API traffic goes through
QgsNetworkAccessManager inside QgsTask workers — never the GUI thread.
Credentials, when used, live only in the QGIS Authentication System
(authcfg id in settings; never tokens in code or project files).
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication


class TalaixPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.dock = None
        self.action = None

    def initProcessing(self):
        from .processing.provider import TalaixProcessingProvider

        self.provider = TalaixProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        self.action = QAction("Talaix — hazard browser", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addPluginToMenu("Talaix", self.action)
        self.iface.addToolBarIcon(self.action)

    def toggle_dock(self):
        if self.dock is None:
            from .dock import TalaixDock

            self.dock = TalaixDock(self.iface)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.setVisible(not self.dock.isVisible())

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.action is not None:
            self.iface.removePluginMenu("Talaix", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

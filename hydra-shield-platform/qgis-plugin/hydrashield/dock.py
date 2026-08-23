"""Talaix dock — hazard registry browser + analyze-clicked-point.

Loads GET /api/v2/hazards in a QgsTask (never the GUI thread) and shows
per hazard: enabled, analysis availability, events availability, official
sources with URLs, and provenance. "Analyze clicked point" activates a
map tool; the click runs hydrashield:analyze_point through the Processing
framework (background task).

The optional API key is referenced only by a QGIS authcfg id read from
QgsSettings — the plugin never sees or stores a token.
"""

from __future__ import annotations

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsTask,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsMapToolEmitPoint

from .api_client import hazards_url, http_get_json, normalize_hazard


class _RegistryTask(QgsTask):
    """Fetch + normalize the hazard registry off the GUI thread."""

    def __init__(self, authcfg=""):
        super().__init__("Talaix: load hazard registry")
        self.authcfg = authcfg
        self.hazards = []
        self.error = None

    def run(self):
        payload, error = http_get_json(hazards_url(), self.authcfg)
        if error:
            self.error = error
            return False
        self.hazards = [normalize_hazard(h)
                        for h in (payload or {}).get("hazards", [])]
        return True


class _PointTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self._callback = callback

    def canvasPressEvent(self, event):
        self._callback(self.toMapCoordinates(event.pos()))


class TalaixDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("Talaix — Climate Extreme Intelligence")
        self.iface = iface
        self.setObjectName("TalaixDock")
        self._tool = None

        body = QWidget(self)
        layout = QVBoxLayout(body)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh registry", body)
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        self.analyze_btn = QPushButton("Analyze clicked point", body)
        self.analyze_btn.setCheckable(True)
        self.analyze_btn.toggled.connect(self._toggle_tool)
        row.addWidget(self.analyze_btn)
        layout.addLayout(row)

        self.status = QLabel("Loading hazard registry…", body)
        layout.addWidget(self.status)
        self.tree = QTreeWidget(body)
        self.tree.setHeaderLabels(["Hazard", "Enabled", "Analysis", "Events"])
        self.tree.itemSelectionChanged.connect(self._show_details)
        layout.addWidget(self.tree)
        self.details = QTextBrowser(body)
        self.details.setOpenExternalLinks(True)
        layout.addWidget(self.details)
        self.setWidget(body)
        self.refresh()

    # -- registry ------------------------------------------------------

    def refresh(self):
        self.status.setText("Loading hazard registry…")
        task = _RegistryTask()
        task.taskCompleted.connect(lambda: self._loaded(task))
        task.taskTerminated.connect(
            lambda: self.status.setText("Registry load failed or was cancelled."))
        QgsApplication.taskManager().addTask(task)

    def _loaded(self, task):
        self.tree.clear()
        if task.error:
            self.status.setText(f"Registry unavailable: {task.error}")
            return
        self.status.setText(
            f"{len(task.hazards)} hazards — talaix.com registry. "
            "Levels are screening indicators, not validated predictions.")
        for h in task.hazards:
            item = QTreeWidgetItem([
                h["name"],
                "yes" if h["enabled"] else "no",
                "available" if h["analysis_available"] else (h["analysis_reason"] or "unavailable"),
                "available" if h["events_available"] else (h["events_reason"] or "unavailable"),
            ])
            item.setData(0, Qt.UserRole, h)
            self.tree.addTopLevelItem(item)

    def _show_details(self):
        items = self.tree.selectedItems()
        if not items:
            return
        h = items[0].data(0, Qt.UserRole)
        if not h:
            return
        sources = "".join(
            f'<li><a href="{url}">{name}</a></li>' for name, url in h["sources"])
        self.details.setHtml(
            f"<b>{h['name']}</b> ({h['id']})<br>"
            f"enabled: {h['enabled']} · analysis: {h['analysis_available']} · "
            f"events: {h['events_available']}<br>"
            f"<i>{h['indicator_status']}</i><br>"
            f"module: <code>{h['provenance_module']}</code>"
            f"<ul>{sources}</ul>")

    # -- analyze clicked point -----------------------------------------

    def _toggle_tool(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self._tool = _PointTool(canvas, self._analyze_at)
            canvas.setMapTool(self._tool)
        else:
            canvas.unsetMapTool(self._tool)
            self._tool = None

    def _analyze_at(self, point):
        canvas = self.iface.mapCanvas()
        src = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if src != wgs84:
            transform = QgsCoordinateTransform(
                src, wgs84, QgsProject.instance().transformContext())
            point = transform.transform(point)
        self.analyze_btn.setChecked(False)
        from processing.tools import general  # QGIS processing entry point

        general.run(
            "hydrashield:analyze_point",
            {"POINT": f"{point.x()},{point.y()} [EPSG:4326]",
             "HAZARD": 0, "NAME": ""})

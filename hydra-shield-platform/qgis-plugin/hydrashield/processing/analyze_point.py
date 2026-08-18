"""hydrashield:analyze_point — point analysis against the HydraShield API.

Input: a point (any CRS — transformed to EPSG:4326), a hazard id, an
optional place name. Output: a one-feature memory layer whose attributes
carry the analysis level, the honesty fields (validated, basis,
unavailable_reason) and the summary; layer metadata carries the full
provenance block. Runs through QgsNetworkAccessManager on the Processing
worker thread.

The API's honest states are preserved: an unavailable/key_required
analysis produces a feature with status set — never a fabricated level.
"""

from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingParameterEnum,
    QgsProcessingParameterPoint,
    QgsProcessingParameterString,
    QgsProcessingParameterFeatureSink,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from ..api_client import analyze_url, http_get_json, normalize_analysis

HAZARDS = ["wildfire", "flood", "drought", "heat", "wind", "coastal"]


class AnalyzePointAlgorithm(QgsProcessingAlgorithm):
    INPUT_POINT = "POINT"
    INPUT_HAZARD = "HAZARD"
    INPUT_NAME = "NAME"
    OUTPUT = "OUTPUT"

    def name(self):
        return "analyze_point"

    def displayName(self):
        return "Analyze point (HydraShield)"

    def group(self):
        return "Analysis"

    def groupId(self):
        return "analysis"

    def shortHelpString(self):
        return ("Analyze a point against the HydraShield API "
                "(GET /api/v2/analyze). Results are screening indicators "
                "with provenance — not validated predictions. Unavailable "
                "data is reported, never invented.")

    def createInstance(self):
        return AnalyzePointAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterPoint(
            self.INPUT_POINT, "Point to analyze"))
        self.addParameter(QgsProcessingParameterEnum(
            self.INPUT_HAZARD, "Hazard", options=HAZARDS,
            defaultValue=0))
        self.addParameter(QgsProcessingParameterString(
            self.INPUT_NAME, "Place name (optional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "HydraShield analysis"))

    def processAlgorithm(self, parameters, context, feedback):
        point = self.parameterAsPoint(
            parameters, self.INPUT_POINT, context,
            QgsCoordinateReferenceSystem("EPSG:4326"))
        hazard = HAZARDS[self.parameterAsEnum(parameters, self.INPUT_HAZARD,
                                              context)]
        name = self.parameterAsString(parameters, self.INPUT_NAME,
                                      context) or None

        fields = QgsFields()
        for fname, ftype in (("hazard", QVariant.String),
                             ("status", QVariant.String),
                             ("level", QVariant.String),
                             ("score", QVariant.Double),
                             ("summary", QVariant.String),
                             ("basis", QVariant.String),
                             ("validated", QVariant.Bool),
                             ("unavailable_reason", QVariant.String),
                             ("place", QVariant.String)):
            fields.append(QgsField(fname, ftype))
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point,
            QgsCoordinateReferenceSystem("EPSG:4326"))

        url = analyze_url(hazard, point.y(), point.x(), name)
        feedback.pushInfo(f"HydraShield request: {url}")
        payload, error = http_get_json(url)
        if error:
            raise Exception(
                f"HydraShield analysis failed: {error}. The API reports "
                "unavailable data honestly — check the message and retry.")

        norm = normalize_analysis(payload)
        rec = norm["record"]
        feature = QgsFeature(fields)
        feature.setGeometry(QgsGeometry.fromPointXY(
            QgsPointXY(point.x(), point.y())))
        feature.setAttributes([
            rec.get("hazard"), rec.get("status"), rec.get("level_label"),
            rec.get("level_score"), rec.get("summary"), rec.get("level_basis"),
            bool(rec.get("validated")), rec.get("unavailable_reason"),
            rec.get("name"),
        ])
        sink.addFeature(feature)

        # Provenance surfaces in the algorithm log; the level attributes
        # carry the honesty fields (basis, validated) on the feature.
        provenance = payload.get("provenance") or {}
        feedback.pushInfo(
            "Provenance components: " + ", ".join(sorted(provenance)[:12])
            if provenance else "No provenance block returned.")
        feedback.pushInfo(
            "HydraShield levels are screening indicators, not validated "
            "predictions (see basis/validated attributes).")
        return {self.OUTPUT: dest_id}

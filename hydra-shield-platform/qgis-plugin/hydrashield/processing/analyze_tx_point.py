"""hydrashield:analyze_tx_point — point analysis against the TX Engine API.

Input: a point (any CRS — transformed to EPSG:4326), zero or more hazard
ids (default: all registered), a TX depth preset, an optional place name.
Output: a memory layer with ONE FEATURE PER HAZARD RESULT whose attributes
carry the TX level, the honesty fields (status, basis, validated,
unavailable_reason) and the envelope stamps (analysis_id, depth,
engine_version). Runs through QgsNetworkAccessManager on the Processing
worker thread (GET /api/tx/analyze).

The TX honesty contract is preserved: an unavailable hazard produces a
feature with status="unavailable" and its reason — never a fabricated
level. For deep analyses that outgrow a request, the TX Job Object
(POST /api/tx/run) is the next surface; this algorithm consumes the
synchronous endpoint only.
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

from ..api_client import http_get_json
from ..tx_client import (
    TX_DEPTHS,
    TX_HAZARDS,
    TX_PRODUCTS,
    normalize_tx_result,
    tx_analyze_url,
)


class AnalyzeTxPointAlgorithm(QgsProcessingAlgorithm):
    INPUT_POINT = "POINT"
    INPUT_HAZARDS = "HAZARDS"
    INPUT_ANALYSES = "ANALYSES"
    INPUT_DEPTH = "DEPTH"
    INPUT_NAME = "NAME"
    OUTPUT = "OUTPUT"

    def name(self):
        return "analyze_tx_point"

    def displayName(self):
        return "Analyze point (Talaix TX Engine)"

    def group(self):
        return "Analysis"

    def groupId(self):
        return "analysis"

    def shortHelpString(self):
        return ("Analyze a point against the Talaix TX Engine "
                "(GET /api/tx/analyze) — one uniform envelope, one feature "
                "per hazard, engine versions stamped for reproducibility. "
                "Select no hazards to run all registered ones. Levels are "
                "screening indicators with provenance — not validated "
                "predictions. Unavailable data is reported, never invented.")

    def createInstance(self):
        return AnalyzeTxPointAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterPoint(
            self.INPUT_POINT, "Point to analyze"))
        self.addParameter(QgsProcessingParameterEnum(
            self.INPUT_HAZARDS, "Hazards (none selected = all)",
            options=TX_HAZARDS, allowMultiple=True, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.INPUT_ANALYSES, "Product analyses (TX-2+ engines)",
            options=TX_PRODUCTS, allowMultiple=True, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.INPUT_DEPTH, "Depth", options=TX_DEPTHS, defaultValue=1))
        self.addParameter(QgsProcessingParameterString(
            self.INPUT_NAME, "Place name (optional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "TX analysis"))

    def processAlgorithm(self, parameters, context, feedback):
        point = self.parameterAsPoint(
            parameters, self.INPUT_POINT, context,
            QgsCoordinateReferenceSystem("EPSG:4326"))
        selected = self.parameterAsEnums(parameters, self.INPUT_HAZARDS,
                                         context)
        hazards = [TX_HAZARDS[i] for i in selected] or None
        selected_analyses = self.parameterAsEnums(parameters,
                                                  self.INPUT_ANALYSES, context)
        analyses = [TX_PRODUCTS[i] for i in selected_analyses] or None
        depth = TX_DEPTHS[self.parameterAsEnum(parameters, self.INPUT_DEPTH,
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
                             ("place", QVariant.String),
                             ("analysis_id", QVariant.String),
                             ("depth", QVariant.String),
                             ("engine_version", QVariant.String),
                             ("tx_level", QVariant.Int)):
            fields.append(QgsField(fname, ftype))
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point,
            QgsCoordinateReferenceSystem("EPSG:4326"))

        url = tx_analyze_url(point.y(), point.x(), hazards, depth, name,
                             analyses)
        feedback.pushInfo(f"Talaix TX request: {url}")
        payload, error = http_get_json(url)
        if error:
            raise Exception(
                f"Talaix TX analysis failed: {error}. The API reports "
                "unavailable data honestly — check the message and retry.")

        norm = normalize_tx_result(payload)
        records = norm["records"]
        if not records:
            feedback.pushInfo(
                "TX returned no hazard results for this location — the "
                "envelope's status/summary rows explain why.")
        for rec in records:
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(point.x(), point.y())))
            feature.setAttributes([
                rec.get("hazard"), rec.get("status"), rec.get("level_label"),
                rec.get("level_score"), rec.get("summary"),
                rec.get("level_basis"), bool(rec.get("validated")),
                rec.get("unavailable_reason"), rec.get("name"),
                rec.get("analysis_id"), rec.get("depth"),
                rec.get("engine_version"), rec.get("tx_level"),
            ])
            sink.addFeature(feature)

        for key, value in norm["rows"][:16]:
            feedback.pushInfo(f"TX {key}: {value}")
        feedback.pushInfo(
            "Talaix TX levels are screening indicators, not validated "
            "predictions (see basis/validated attributes).")
        return {self.OUTPUT: dest_id}

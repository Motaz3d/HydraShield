"""Talaix Processing provider — registers the analysis algorithms."""

from __future__ import annotations

from qgis.core import QgsProcessingProvider

from .analyze_point import AnalyzePointAlgorithm
from .analyze_tx_point import AnalyzeTxPointAlgorithm


class TalaixProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(AnalyzePointAlgorithm())
        self.addAlgorithm(AnalyzeTxPointAlgorithm())

    def id(self):
        return "hydrashield"

    def name(self):
        return "Talaix Climate Intelligence"

    def longName(self):
        return "Talaix Climate Intelligence (talaix.com)"

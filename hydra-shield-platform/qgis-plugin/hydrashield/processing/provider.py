"""Talaix Processing provider — registers the analysis algorithms."""

from __future__ import annotations

from qgis.core import QgsProcessingProvider

from .analyze_point import AnalyzePointAlgorithm


class TalaixProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(AnalyzePointAlgorithm())

    def id(self):
        return "hydrashield"

    def name(self):
        return "Talaix Climate Intelligence"

    def longName(self):
        return "Talaix Climate Intelligence (talaix.com)"

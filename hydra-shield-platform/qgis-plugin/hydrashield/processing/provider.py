"""HydraShield Processing provider — registers the analysis algorithms."""

from __future__ import annotations

from qgis.core import QgsProcessingProvider

from .analyze_point import AnalyzePointAlgorithm


class HydraShieldProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(AnalyzePointAlgorithm())

    def id(self):
        return "hydrashield"

    def name(self):
        return "HydraShield Climate Intelligence"

    def longName(self):
        return "HydraShield Climate Intelligence (hydrashield.earth)"

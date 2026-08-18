"""
Dust / sandstorm hazard plugin — registered with an honest unavailable
state until a real pipeline is wired in.

Candidate real sources (documented, live-checked 2026-08-18):

- **CAMS** (Copernicus Atmosphere Monitoring Service) — dust aerosol
  optical depth / particulate forecasts; requires free ADS credentials
  (``CAMS_ADS_URL`` / ``CAMS_ADS_KEY`` — see .env.example). Not wired
  until those credentials exist.
- **WMO SDS-WAS** (Sand and Dust Storm Warning Advisory and Assessment
  System, Barcelona Dust Centre) — regional dust model evaluation and
  guidance; reference source, not an integrated fetch path.

Terminology discipline: "dust storm", "sandstorm", "Sirocco",
"Khamseen/Khamsin" and "desert dust transport" are regional/technical
terms for related but not identical phenomena — any future pipeline must
classify events by the terminology of the underlying source, not merge
them.

No medical claims are ever made; air-quality relevance is reported only
from authoritative measurements when a source is integrated.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from ..ontology import TemporalClass
from .base import HazardAnalysis, HazardModule, LayerSpec


class DustModule(HazardModule):
    id = "dust"
    name = "Dust / sandstorm"
    tagline = ("Desert dust transport, dust storms and sandstorms — "
               "transport, exposure and historical context. ")

    # -- availability (honest) ------------------------------------------

    def availability(self) -> Tuple[bool, Optional[str]]:
        if not (os.environ.get("CAMS_ADS_URL") and os.environ.get("CAMS_ADS_KEY")):
            return False, ("Dust analysis requires CAMS (Copernicus Atmosphere "
                           "Monitoring Service) credentials (CAMS_ADS_URL / "
                           "CAMS_ADS_KEY) — not configured. No dust values are "
                           "produced without a real source.")
        # Credentials present but the fetch path is not implemented yet.
        return False, ("CAMS credentials detected but the dust fetch pipeline "
                       "is not yet integrated — dust analysis remains "
                       "unavailable rather than simulated.")

    def events_availability(self) -> Tuple[bool, Optional[str]]:
        return False, ("No integrated historical dust-event dataset — WMO "
                       "SDS-WAS / regional dust records are candidate sources, "
                       "not wired in. No events are invented.")

    def temporal_coverage(self) -> Dict[str, Dict[str, str]]:
        return {
            "CAMS dust forecasts (candidate)": {
                "start": "per CAMS documentation", "end": "present"},
            "WMO SDS-WAS model guidance (candidate)": {
                "start": "per SDS-WAS documentation", "end": "present"},
        }

    # -- core operations (honest unavailable) ----------------------------

    def analyze(self, lat: float, lon: float, name: Optional[str] = None, **kw: Any) -> HazardAnalysis:
        available, reason = self.availability()
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="unavailable",
            summary="Dust analysis is not available yet.",
            unavailable_reason=reason,
        )

    # -- map layers (declared, not wired) --------------------------------

    def map_layers(self, **kw: Any) -> list:
        _ok, reason = self.availability()
        return [
            LayerSpec(
                layer_id="dust.forecast",
                label="Dust aerosol forecast (CAMS)",
                group="HAZARD",
                kind="raster",
                source="CAMS — Copernicus Atmosphere Monitoring Service",
                url="https://ads.atmosphere.copernicus.eu/",
                status="unavailable",
                temporal=TemporalClass.FORECAST.value,
                provenance={"note": reason},
            ).to_dict(),
            LayerSpec(
                layer_id="dust.sds_was",
                label="Dust model guidance (WMO SDS-WAS)",
                group="EVIDENCE",
                kind="raster",
                source="WMO SDS-WAS — Barcelona Dust Centre",
                url="https://dust.aemet.es/",
                status="unavailable",
                temporal=TemporalClass.FORECAST.value,
                provenance={"note": "Candidate source — not integrated."},
            ).to_dict(),
        ]

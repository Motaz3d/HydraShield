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

Wired source (2026-09, gradual engine wiring):

- **NASA EONET ``dustHaze``** — open dust & haze incidents worldwide (free,
  no key). Powers the ``events`` layer — current incident monitoring
  context only. Analysis stays unavailable until CAMS credentials exist.

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
        return True, None

    def temporal_coverage(self) -> Dict[str, Dict[str, str]]:
        return {
            "NASA EONET dust & haze incidents (live)": {
                "start": "current/ongoing incidents", "end": "present (live)"},
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

    # -- events (live: NASA EONET dustHaze incidents) ---------------------

    def events(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50.0,
        year: Optional[int] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Current NASA EONET dust & haze incidents near a point.

        A ``year`` query asks for a historical dust-event archive — honestly
        unavailable (EONET covers open incidents; SDS-WAS archives are a
        candidate, not wired)."""
        if year is not None:
            return {
                "hazard": self.id,
                "status": "unavailable",
                "reason": ("A historical dust-event archive is not wired in — "
                           "EONET covers open incidents only and WMO SDS-WAS "
                           "records are a candidate source. No per-year history "
                           "is invented."),
                "events": [],
            }
        from ...dashboard import real_data as rd
        from ._gdacs import haversine_km

        feed = rd.fetch_eonet_dust_haze()
        if "error" in feed:
            return {"hazard": self.id, "status": "unavailable",
                    "reason": feed["error"], "events": []}
        radius = min(max(float(radius_km), 50.0), 3000.0)
        incidents = []
        for ev in feed["events"]:
            d = haversine_km(lat, lon, ev["lat"], ev["lon"])
            if d > radius:
                continue
            incidents.append({
                "id": ev["id"],
                "name": ev["title"],
                "lat": ev["lat"],
                "lon": ev["lon"],
                "latest_report_date": ev.get("date"),
                "magnitude_value": ev.get("magnitude_value"),
                "magnitude_unit": ev.get("magnitude_unit"),
                "distance_km": round(d, 1),
                "link": ev.get("link"),
            })
        incidents.sort(key=lambda e: e["distance_km"])
        return {
            "hazard": self.id,
            "status": "ok",
            "radius_km": radius,
            "coverage": "NASA EONET open dust & haze incidents (worldwide, live)",
            "note": ("Incident-report monitoring context — not a dust-forecast "
                     "or air-quality measurement."),
            "source": feed["source"],
            "events": incidents,
        }

    # -- map layers -------------------------------------------------------

    def map_layers(self, **kw: Any) -> list:
        _ok, reason = self.availability()
        return [
            LayerSpec(
                layer_id="dust.eonet",
                label="Dust & haze incidents (NASA EONET)",
                group="HAZARD",
                kind="points",
                endpoint="/api/v2/events?hazard=dust&lat={lat}&lon={lon}&radius_km=3000",
                source="NASA EONET — Earth Observatory Natural Event Tracker",
                url="https://eonet.gsfc.nasa.gov/",
                resolution="Latest reported position per incident",
                status="available",
                temporal=TemporalClass.OBSERVED.value,
                provenance={"note": ("Open dust & haze incident monitoring — not a "
                                     "dust forecast or air-quality measurement.")},
            ).to_dict(),
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

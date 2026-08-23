"""
Volcanic hazard plugin — registered with an honest unavailable state.

Authoritative source (documented, live-checked 2026-08-18):

- **Smithsonian / USGS Global Volcanism Program (GVP)** — the canonical
  database of Holocene and Pleistocene volcanoes and their documented
  eruptive history, plus weekly activity reports. The GVP site is
  bot-protected for automated clients (HTTP 403 to non-browser agents at
  check time); a manual/exported dataset path is required before
  integration, so no live fetch is wired in.

Discipline: Talaix does not predict eruptions. Any future volcanic
intelligence is monitoring / historical evidence / exposure / scenario —
never a probability of eruption invented from nothing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..ontology import TemporalClass
from .base import HazardAnalysis, HazardModule, LayerSpec


class VolcanicModule(HazardModule):
    id = "volcanic"
    name = "Volcanic activity"
    tagline = ("Documented volcanic activity and exposure — historical "
               "evidence and monitoring context; never eruption prediction.")

    # -- availability (honest) ------------------------------------------

    def availability(self) -> Tuple[bool, Optional[str]]:
        return False, ("Volcanic analysis is not yet integrated: the "
                       "authoritative source (Smithsonian GVP) requires a "
                       "manual/exported dataset path — automated access is "
                       "bot-protected. No volcanic values are produced "
                       "without a real source.")

    def events_availability(self) -> Tuple[bool, Optional[str]]:
        return False, ("Historical eruption events require the Smithsonian "
                       "GVP database export — not yet integrated. No events "
                       "are invented.")

    def temporal_coverage(self) -> Dict[str, Dict[str, str]]:
        return {
            "Smithsonian GVP — documented eruptions (candidate)": {
                "start": "Holocene record", "end": "present (weekly reports)"},
        }

    # -- core operations (honest unavailable) ----------------------------

    def analyze(self, lat: float, lon: float, name: Optional[str] = None, **kw: Any) -> HazardAnalysis:
        _available, reason = self.availability()
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="unavailable",
            summary="Volcanic analysis is not available yet.",
            unavailable_reason=reason,
        )

    # -- map layers (declared, not wired) --------------------------------

    def map_layers(self, **kw: Any) -> list:
        _ok, reason = self.availability()
        return [
            LayerSpec(
                layer_id="volcanic.gvp_events",
                label="Documented eruptions (Smithsonian GVP)",
                group="EVIDENCE",
                kind="points",
                source="Smithsonian Institution / USGS — Global Volcanism Program",
                url="https://volcano.si.edu/",
                status="unavailable",
                temporal=TemporalClass.HISTORICAL.value,
                provenance={"note": reason},
            ).to_dict(),
        ]

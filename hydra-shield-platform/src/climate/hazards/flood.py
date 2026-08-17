"""
Flood hazard plugin (Stage 4 foundation).

Real-data analyses only:

- **River discharge intelligence** — daily GloFAS river discharge via the
  Open-Meteo Flood API (Copernicus EMS / EC JRC): current value (model
  nowcast), percentile within the location's own multi-year series, and
  high-discharge spell detection (declared threshold).
- **Extreme precipitation** — ERA5 daily precipitation via the Open-Meteo
  archive: event totals (rolling sums), antecedent precipitation index
  (declared decay), percentile vs the location's own record.
- **Terrain context** — DEM elevation/slope (OpenTopoData). Terrain context
  only — NOT a hydraulic flood model.
- **Exposure** — mapped OSM waterways/water features/buildings/critical
  facilities in the analysis radius.

Explicitly NOT claimed: flood-extent maps, flood forecasts, depth grids.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..ontology import ClaimStatus, EvidenceClass, TemporalClass
from ..evidence import EvidenceRecord, content_hash
from .base import HazardAnalysis, HazardLevel, HazardModule, LayerSpec
from . import _series

_HISTORY_DAYS = 365 * 10        # percentile context: the location's own ~10-year series
_SPELL_Q = 95.0                 # high-discharge threshold: 95th percentile of own series
_SPELL_MIN_DAYS = 2             # >= 2 consecutive days above threshold = one spell
_API_DECAY = 0.85               # antecedent precipitation index decay (Kohler–Linsley style)
_ARCHIVE_LAG_DAYS = 5           # ERA5 archive lag behind real time
_OSM_RADIUS_M = 2000


class FloodModule(HazardModule):
    id = "flood"
    name = "River flood"
    tagline = "River discharge, extreme precipitation, terrain context and exposure."

    def temporal_coverage(self) -> Dict[str, Dict[str, str]]:
        return {
            "GloFAS river discharge (Open-Meteo Flood API)": {
                "start": "1984",
                "end": "near-present (model nowcast)",
            },
            "ERA5 daily precipitation (Open-Meteo archive)": {
                "start": "1940",
                "end": "~5 days ago (archive lag)",
            },
        }

    # -- analysis ------------------------------------------------------

    def analyze(self, lat: float, lon: float, name: Optional[str] = None, **kw: Any) -> HazardAnalysis:
        from ...dashboard import real_data as rd
        from ...dashboard import exposure as osm

        today = date.today()
        hist_start = (today - timedelta(days=_HISTORY_DAYS)).isoformat()
        archive_end = (today - timedelta(days=_ARCHIVE_LAG_DAYS)).isoformat()
        location = {"lat": lat, "lon": lon, "name": name}

        discharge = rd.fetch_flood_discharge(lat, lon, hist_start, today.isoformat())
        precip = rd.fetch_daily_climate(
            lat, lon, hist_start, archive_end, ["precipitation_sum"]
        )
        terrain = rd.fetch_terrain(lat, lon)
        osm_ctx = osm.fetch_osm_context(lat, lon, _OSM_RADIUS_M)

        blocks: Dict[str, Any] = {}
        evidence: List[Dict[str, Any]] = []
        provenance: Dict[str, Any] = {}
        reasons: List[str] = []
        core_ok = 0

        # -- river discharge ------------------------------------------
        dis_block, dis_level_input = self._discharge_block(discharge, hist_start, today)
        blocks["river_discharge"] = dis_block
        if dis_block.get("status") == "ok":
            core_ok += 1
            rec = EvidenceRecord(
                EvidenceClass.OPEN_DATA_OFFICIAL.value,
                ClaimStatus.MODELLED.value,
                TemporalClass.HISTORICAL.value,
                discharge["source"],
                dataset="GloFAS daily river discharge",
                provider_url="https://open-meteo.com/en/docs/flood-api",
                link=discharge.get("request_url"),
                location={"lat": lat, "lon": lon},
                reference_period={"start": hist_start, "end": today.isoformat()},
                method=(
                    "Latest value and percentile within the location's own "
                    f"~{_HISTORY_DAYS // 365}-year daily series; latest days are a "
                    "GloFAS model nowcast (temporal OBSERVED window), the rest HISTORICAL."
                ),
                resolution="GloFAS ~0.1° grid",
                limitations="Hydrological model output, not gauge observations.",
                content_hash=content_hash(
                    {"time": discharge["time"], "river_discharge": discharge["river_discharge"]}
                ),
            )
        else:
            reasons.append(dis_block.get("reason") or "river discharge unavailable")
            rec = EvidenceRecord.unknown(
                "Open-Meteo Flood API (GloFAS)",
                why=dis_block.get("reason") or "river discharge unavailable",
            )
        evidence.append(rec.to_dict())
        provenance["river_discharge"] = rec.to_dict()

        # -- extreme precipitation --------------------------------------
        pr_block, pr_level_input = self._precip_block(precip, hist_start, archive_end)
        blocks["extreme_precipitation"] = pr_block
        if pr_block.get("status") == "ok":
            core_ok += 1
            rec = EvidenceRecord(
                EvidenceClass.OPEN_DATA_OFFICIAL.value,
                ClaimStatus.MODELLED.value,
                TemporalClass.HISTORICAL.value,
                precip["source"],
                dataset="ERA5 daily precipitation sum",
                provider_url="https://open-meteo.com/en/docs/historical-weather-api",
                link=precip.get("request_url"),
                location={"lat": lat, "lon": lon},
                reference_period={"start": hist_start, "end": archive_end},
                method=pr_block.get("method"),
                resolution="~11–25 km reanalysis grid",
                limitations="Reanalysis, not a rain-gauge measurement; archive lag ~5 days.",
                content_hash=content_hash(
                    {"time": precip["time"], "precipitation_sum": precip["precipitation_sum"]}
                ),
            )
        else:
            reasons.append(pr_block.get("reason") or "precipitation unavailable")
            rec = EvidenceRecord.unknown(
                "Open-Meteo archive (ERA5)",
                why=pr_block.get("reason") or "precipitation unavailable",
            )
        evidence.append(rec.to_dict())
        provenance["extreme_precipitation"] = rec.to_dict()

        # -- terrain context (NOT a flood model) ------------------------
        blocks["terrain_context"] = self._terrain_block(terrain)
        if blocks["terrain_context"].get("status") == "ok":
            rec = EvidenceRecord.open_data(
                terrain["source"],
                status=ClaimStatus.OBSERVED.value,
                temporal=TemporalClass.OBSERVED.value,
                dataset=terrain.get("dataset"),
                location={"lat": lat, "lon": lon},
                method="3x3 DEM grid slope/aspect derivation (existing terrain fetcher).",
                resolution=terrain.get("resolution"),
                limitations="Static DEM snapshot; terrain context only — not a flood model.",
            )
            evidence.append(rec.to_dict())
            provenance["terrain_context"] = rec.to_dict()

        # -- exposure ----------------------------------------------------
        blocks["exposure"] = self._exposure_block(osm_ctx)
        if blocks["exposure"].get("status") == "ok":
            rec = EvidenceRecord.open_data(
                osm_ctx["source"],
                status=ClaimStatus.OBSERVED.value,
                temporal=TemporalClass.OBSERVED.value,
                location={"lat": lat, "lon": lon},
                method=f"Counts of mapped OSM features within {_OSM_RADIUS_M} m.",
                limitations=osm_ctx.get("note"),
            )
            evidence.append(rec.to_dict())
            provenance["exposure"] = rec.to_dict()

        blocks["declared_limitations"] = (
            "Foundation analysis: NO flood-extent maps, NO flood forecasts, NO depth "
            "grids. Discharge is GloFAS hydrological model output; precipitation is ERA5 "
            "reanalysis; terrain is context only (not a hydraulic model)."
        )

        # -- level + status ----------------------------------------------
        level = self._level(dis_level_input, pr_level_input)
        if core_ok == 0:
            return HazardAnalysis(
                hazard=self.id,
                location=location,
                status="unavailable",
                summary="Flood analysis unavailable for this location.",
                level=None,
                blocks=blocks,
                evidence=evidence,
                provenance=provenance,
                unavailable_reason="; ".join(reasons) or "No flood-relevant data obtained.",
            )

        status = "ok" if core_ok == 2 else "partial"
        summary = self._summary(dis_block, pr_block, level, status)
        return HazardAnalysis(
            hazard=self.id,
            location=location,
            status=status,
            summary=summary,
            level=level,
            blocks=blocks,
            evidence=evidence,
            provenance=provenance,
        )

    # -- blocks ----------------------------------------------------------

    def _discharge_block(
        self, discharge: Dict, hist_start: str, today: date
    ) -> Tuple[Dict[str, Any], Optional[float]]:
        """Discharge block + the percentile used for the level (None if n/a)."""

        if "error" in discharge:
            return {
                "status": "unavailable",
                "reason": discharge["error"],
                "source": discharge.get("source"),
            }, None

        times: List[str] = discharge["time"]
        values: List[Optional[float]] = discharge["river_discharge"]
        valid = [(t, v) for t, v in zip(times, values) if v is not None]
        if not valid:
            return {"status": "unavailable", "reason": "Discharge series is empty."}, None

        latest_date, latest_val = valid[-1]
        pct = _series.percentile_rank(values, latest_val)
        threshold = _series.percentile_value(values, _SPELL_Q)
        record_max_date, record_max = max(valid, key=lambda tv: tv[1])

        # Spells over the most recent year of the series.
        cutoff = (today - timedelta(days=365)).isoformat()
        recent_pairs = [(t, v) for t, v in zip(times, values) if t >= cutoff]
        spells = _series.detect_spells(
            [t for t, _v in recent_pairs],
            [v for _t, v in recent_pairs],
            threshold,
            min_len=_SPELL_MIN_DAYS,
            above=True,
        ) if threshold is not None else []

        block = {
            "status": "ok",
            "claim_status": ClaimStatus.MODELLED.value,
            "labels": {
                "latest": f"{TemporalClass.OBSERVED.value} (GloFAS model nowcast window)",
                "series": TemporalClass.HISTORICAL.value,
            },
            "latest": {
                "date": latest_date,
                "discharge_m3s": round(latest_val, 2),
                "temporal": TemporalClass.OBSERVED.value,
            },
            "percentile_of_latest": pct,
            "days_in_series": len(valid),
            "series_start": valid[0][0],
            "record_max": {"date": record_max_date, "discharge_m3s": round(record_max, 2)},
            "high_discharge_spells_last_year": spells,
            "threshold_method": (
                f"High-discharge threshold = {_SPELL_Q:.0f}th percentile of the location's "
                f"own daily series ({len(valid)} days, since {valid[0][0]}); "
                f"a spell = >= {_SPELL_MIN_DAYS} consecutive days above it. "
                f"Threshold = {threshold:.2f} m³/s here." if threshold is not None else
                "Threshold could not be computed (empty series)."
            ),
            "source": discharge["source"],
            "units": discharge.get("units", "m³/s"),
            "note": discharge.get("note"),
        }
        return block, pct

    def _precip_block(
        self, precip: Dict, hist_start: str, archive_end: str
    ) -> Tuple[Dict[str, Any], Optional[float]]:
        """Extreme-precipitation block + percentile input for the level."""

        if "error" in precip:
            return {
                "status": "unavailable",
                "reason": precip["error"],
                "source": precip.get("source"),
            }, None

        times: List[str] = precip["time"]
        pr: List[Optional[float]] = precip["precipitation_sum"]
        valid = [(t, v) for t, v in zip(times, pr) if v is not None]
        if not valid:
            return {"status": "unavailable", "reason": "Precipitation series is empty."}, None

        last90 = valid[-90:]
        recent_vals = [v for _t, v in last90]
        max_daily = max(recent_vals)

        # Event totals: trailing 3-day / 7-day rolling sums over the last 90 days.
        r3 = _series.rolling_sums(recent_vals, 3)
        r7 = _series.rolling_sums(recent_vals, 7)
        best3 = max(
            ((i, s) for i, s in enumerate(r3) if s is not None),
            key=lambda iv: iv[1], default=None,
        )
        best7 = max(
            ((i, s) for i, s in enumerate(r7) if s is not None),
            key=lambda iv: iv[1], default=None,
        )

        # Antecedent precipitation index over the last year (declared decay).
        last365 = valid[-365:]
        api = _series.antecedent_precipitation_index(
            [v for _t, v in last365], decay=_API_DECAY
        )
        api_latest = next((a for a in reversed(api) if a is not None), None)
        api_pct = _series.percentile_rank(api, api_latest)

        # Percentile of the wettest recent day vs the full record.
        all_vals = [v for _t, v in valid]
        pct_max_daily = _series.percentile_rank(all_vals, max_daily)

        block = {
            "status": "ok",
            "claim_status": ClaimStatus.MODELLED.value,
            "temporal": TemporalClass.HISTORICAL.value,
            "window": {
                "start": last90[0][0],
                "end": last90[-1][0],
                "note": f"ERA5 archive lag: data ends ~{_ARCHIVE_LAG_DAYS} days before today.",
            },
            "max_daily_precip_mm": round(max_daily, 1),
            "percentile_of_max_daily_vs_record": pct_max_daily,
            "max_3day_total_mm": (
                {"total": round(best3[1], 1), "end_date": last90[best3[0]][0]}
                if best3 else None
            ),
            "max_7day_total_mm": (
                {"total": round(best7[1], 1), "end_date": last90[best7[0]][0]}
                if best7 else None
            ),
            "antecedent_precipitation_index": {
                "latest": round(api_latest, 1) if api_latest is not None else None,
                "date": last365[-1][0],
                "percentile_vs_last_year": api_pct,
                "decay": _API_DECAY,
            },
            "method": (
                f"Event totals = trailing 3-/7-day rolling sums over the last 90 days; "
                f"antecedent precipitation index API_t = P_t + {_API_DECAY}·API_(t-1) "
                f"(Kohler–Linsley style decay) over the last 365 days; percentiles are "
                f"against the location's own daily record since {valid[0][0]}."
            ),
            "source": precip["source"],
        }
        return block, pct_max_daily

    @staticmethod
    def _terrain_block(terrain: Dict) -> Dict[str, Any]:
        if "error" in terrain:
            return {"status": "unavailable", "reason": terrain["error"]}
        return {
            "status": "ok",
            "claim_status": ClaimStatus.OBSERVED.value,
            "elevation_m": terrain.get("elevation_m"),
            "slope_degrees": terrain.get("slope_degrees"),
            "dataset": terrain.get("dataset"),
            "resolution": terrain.get("resolution"),
            "caveat": (
                "Terrain context only (elevation/slope from a static DEM) — "
                "NOT a hydraulic flood model; no flow accumulation or depth."
            ),
            "source": terrain.get("source"),
        }

    @staticmethod
    def _exposure_block(osm_ctx: Dict) -> Dict[str, Any]:
        if "error" in osm_ctx:
            return {"status": "unavailable", "reason": osm_ctx["error"]}
        c = osm_ctx.get("counts") or {}
        return {
            "status": "ok",
            "claim_status": ClaimStatus.OBSERVED.value,
            "radius_m": osm_ctx.get("radius_m"),
            "waterways_mapped": c.get("waterways", 0),
            "water_features_mapped": c.get("water_features", 0),
            "buildings_mapped": c.get("buildings", 0),
            "critical_facilities_mapped": {
                "hospitals": c.get("hospitals", 0),
                "schools": c.get("schools", 0),
                "fire_stations": c.get("fire_stations", 0),
                "power_facilities": c.get("power_facilities", 0),
            },
            "note": osm_ctx.get("note"),
            "source": osm_ctx.get("source"),
        }

    @staticmethod
    def _level(dis_pct: Optional[float], pr_pct: Optional[float]) -> Optional[HazardLevel]:
        pct = dis_pct if dis_pct is not None else pr_pct
        if pct is None:
            return None
        basis_input = (
            "river-discharge percentile" if dis_pct is not None
            else "extreme-precipitation percentile (no river discharge available)"
        )
        if pct >= 97:
            label = "Very high"
        elif pct >= 90:
            label = "High"
        elif pct >= 75:
            label = "Moderate"
        else:
            label = "Low"
        return HazardLevel(
            label=label,
            score=round(pct, 1),
            score_max=100.0,
            basis=(
                f"Screening indicator: latest {basis_input} within the location's own "
                f"~{_HISTORY_DAYS // 365}-year series, banded <75 Low / 75–90 Moderate / "
                f"90–97 High / >=97 Very high. NOT a validated flood predictor; "
                f"no extent or depth is modelled."
            ),
            validated=False,
        )

    @staticmethod
    def _summary(dis_block: Dict, pr_block: Dict, level: Optional[HazardLevel], status: str) -> str:
        parts: List[str] = []
        if dis_block.get("status") == "ok":
            latest = dis_block["latest"]
            parts.append(
                f"River discharge {latest['discharge_m3s']:.1f} m³/s on {latest['date']} "
                f"(percentile {dis_block.get('percentile_of_latest')})"
            )
        if pr_block.get("status") == "ok":
            parts.append(
                f"max daily precipitation {pr_block['max_daily_precip_mm']} mm in the last 90 days"
            )
        if level is not None:
            parts.append(f"screening level: {level.label}")
        if status == "partial":
            parts.append("partial: some data sources unavailable")
        return "; ".join(parts) + "." if parts else "Flood analysis complete."

    # -- map layers --------------------------------------------------------

    def map_layers(self, **kw: Any) -> list:
        return [
            LayerSpec(
                layer_id="flood.discharge",
                label="River discharge (GloFAS)",
                group="HAZARD",
                kind="points",
                endpoint="/api/v2/analyze?hazard=flood&lat={lat}&lon={lon}",
                legend={"Low": "#22c55e", "Moderate": "#eab308", "High": "#f97316", "Very high": "#ef4444"},
                source="GloFAS river discharge (Copernicus EMS/JRC via Open-Meteo Flood API)",
                resolution="GloFAS ~0.1° grid",
                status="available",
                temporal=TemporalClass.OBSERVED.value,
                default_on=True,
            ).to_dict(),
            LayerSpec(
                layer_id="flood.precipitation",
                label="Extreme precipitation (ERA5)",
                group="ENVIRONMENT",
                kind="grid",
                endpoint="/api/v2/analyze?hazard=flood&lat={lat}&lon={lon}",
                source="ERA5 daily precipitation (Open-Meteo archive)",
                resolution="~11–25 km reanalysis grid",
                status="available",
                temporal=TemporalClass.HISTORICAL.value,
            ).to_dict(),
            LayerSpec(
                layer_id="flood.exposure",
                label="Waterway & building exposure (OSM)",
                group="EXPOSURE",
                kind="points",
                endpoint="/api/v2/analyze?hazard=flood&lat={lat}&lon={lon}",
                source="OpenStreetMap (ohsome / Overpass)",
                resolution="feature-level",
                status="available",
                temporal=TemporalClass.OBSERVED.value,
            ).to_dict(),
        ]

"""
Compound Risk Engine v1 (docs/PRODUCT_VISION.md, IPCC AR6 WG2 risk framework).

Detects compound-event signals at a point from REAL current hazard signals,
following the four-class typology of Zscheischler et al. (2020) — cited in
``config/research_registry.json`` as ``zscheischler2020typology``. The paper
is a typology, NOT an operational algorithm: what lives here is a declared,
qualitative detector on top of it. The IPCC AR6 WG2 compound/cascading risk
framing is cited as ``ipccar6wg2``.

Signal sources (LIGHT only — the heavy wildfire engine is never called here):

- drought / heat / wind / flood via the registry's per-hazard analyzers
  (ERA5-based, cheap; flood tolerated honestly when no modelled river exists).
- fire danger: computed directly from the ERA5 daily archive fetcher
  (``real_data.fetch_weather_archive``) + the Canadian FWI System
  (``prediction.fwi.compute_fwi_series``, Van Wagner 1987; EFFIS classes).
  Declared as a fire-danger signal, NOT a wildfire risk analysis.

Honesty contract (absolute):

- NO numeric compound score. The output is a qualitative signal list only —
  no invented metric.
- Every signal carries the real values it rests on, evidence records and a
  claim-status label (MODELLED for detections on modelled reanalysis signals,
  INFERRED for preconditioning mechanisms).
- ``spatially_compounding`` is NOT computable at point scale and is returned
  explicitly as ``not_computable`` — never faked.
- A hazard that errors reduces the signal set (recorded in
  ``hazards_unavailable``); it never crashes the assessment.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dashboard.cache import cached
from .evidence import EvidenceRecord
from .hazards import _series
from .ontology import ClaimStatus, Confidence, EvidenceClass, TemporalClass

TTL_COMPOUND = 3600.0  # 1 h

#: Light per-hazard analyzers run via the registry (wildfire is NOT among
#: them — the full wildfire engine is heavy; see _fire_danger_signal).
LIGHT_HAZARDS = ("drought", "heat", "wind", "flood")

#: All hazard ids this engine can signal on. "wildfire" here means the cheap
#: FWI fire-danger signal, never the full wildfire engine.
KNOWN_HAZARDS = LIGHT_HAZARDS + ("wildfire",)

#: Declared elevated thresholds — the only gates the qualitative detector
#: uses. Each is stated again in every signal that rests on it.
ELEVATED_THRESHOLDS = {
    "drought": "elevated when the worst 30/90/180-day standardized precipitation anomaly (z) is <= -1.0",
    "heat": "elevated when the latest Tmax percentile vs the 1991-2020 day-of-year climatology is >= 90",
    "wind": "elevated when the latest gust percentile vs the 1991-2020 day-of-year climatology is >= 90",
    "flood": "elevated when the river-discharge or extreme-precipitation percentile vs the location's own record is >= 90",
    "wildfire": "fire-danger signal elevated when the latest Canadian FWI value is >= 30 (between the EFFIS Moderate and High classes; declared screening threshold)",
}

_FWI_ELEVATED = 30.0          # declared fire-danger threshold (see above)
_FWI_SPELL_MIN_DAYS = 3       # a high-FWI spell = >= 3 consecutive days >= threshold
_DROUGHT_Z_ELEVATED = -1.0
_PCT_ELEVATED = 90.0
_TEMPORAL_WINDOW_DAYS = 90    # trailing window for temporally compounding detection
_FIRE_HISTORY_DAYS = 120      # ERA5 window for the FWI fire-danger signal
_ARCHIVE_LAG_DAYS = 5         # Open-Meteo archive lag behind real time

#: Declared spell-follows-spell pairs for temporally compounding detection.
_TEMPORAL_PAIRS = (
    ("drought", "heat"),
    ("drought", "wildfire"),
    ("heat", "wildfire"),
)

_SPATIALLY_NOT_COMPUTABLE_REASON = (
    "Spatially compounding events (multiple locations connected by shared "
    "impacts or systems) require spatially resolved impact data across "
    "locations; a single-point analysis cannot detect them. Not estimated."
)

_NO_SIGNAL_STATEMENT = (
    "No compound signal detected from the analysed hazards at this location "
    "in the current window. This is a declared qualitative detector over "
    "screening-level signals — absence of a signal is not evidence of "
    "absence of risk."
)

_NO_NUMERIC_SCORE_NOTE = (
    "No numeric compound score is computed: the output is a qualitative "
    "signal list only (no invented metric)."
)

_TYPOLOGY_BASIS = (
    "Declared qualitative detector on top of the four-class compound-event "
    "typology of Zscheischler et al. (2020) — multivariate, temporally "
    "compounding, preconditioned, spatially compounding "
    "(research_registry: zscheischler2020typology). The typology is a "
    "classification framework, not an operational algorithm; thresholds and "
    "windows used here are declared HydraShield screening choices, not "
    "parameters from the paper."
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Light per-hazard signal extraction (shared with cascading.py — do not
# duplicate this logic elsewhere)
# ---------------------------------------------------------------------------


def _signal_skeleton(hazard: str) -> Dict[str, Any]:
    return {
        "hazard": hazard,
        "status": "unavailable",
        "level": None,
        "elevated": False,
        "elevated_basis": None,
        "values": {},
        "spells": [],
        "spell_kind": None,
        "spell_status": None,
        "evidence": [],
        "source": None,
        "summary": "",
        "unavailable_reason": None,
    }


def _drought_signal(analysis) -> Dict[str, Any]:
    sig = _signal_skeleton("drought")
    sig["status"] = analysis.status
    sig["summary"] = analysis.summary
    sig["unavailable_reason"] = analysis.unavailable_reason
    sig["evidence"] = list(analysis.evidence or [])
    if analysis.level is not None:
        sig["level"] = analysis.level.to_dict()
    blocks = analysis.blocks or {}
    deficit = (blocks.get("precipitation_deficit") or {})
    windows = deficit.get("windows") or {}
    w90 = windows.get("90") or {}
    soil = blocks.get("soil_moisture") or {}
    dry = blocks.get("dry_spells") or {}

    min_z = analysis.level.score if analysis.level is not None else None
    sig["values"] = {
        "min_standardized_anomaly": min_z,
        "level_label": analysis.level.label if analysis.level else None,
        "precipitation_90d": {
            "current_sum_mm": w90.get("current_sum_mm"),
            "deficit_mm": w90.get("deficit_mm"),
            "standardized_anomaly": w90.get("standardized_anomaly"),
            "period": w90.get("current_period"),
        } if w90.get("status") == "ok" else None,
        "soil_moisture": {
            "anomaly_m3m3": soil.get("anomaly_m3m3"),
            "percentile_vs_climatology": soil.get("percentile_vs_climatology"),
            "as_of": soil.get("as_of"),
        } if soil.get("status") == "ok" else None,
        "dry_spell_ongoing": dry.get("ongoing"),
    }
    if min_z is not None and min_z <= _DROUGHT_Z_ELEVATED:
        sig["elevated"] = True
        sig["elevated_basis"] = (
            f"worst standardized precipitation anomaly z={min_z} <= "
            f"{_DROUGHT_Z_ELEVATED} (declared threshold)"
        )
    if dry.get("status") == "ok":
        sig["spells"] = list(dry.get("spells_last_year") or [])
        sig["spell_kind"] = "dry_spell"
        sig["spell_status"] = {"ongoing": bool(dry.get("ongoing")),
                               "count_last_year": dry.get("count_last_year")}
    sig["source"] = "ERA5 / ERA5-Land daily (Open-Meteo archive)"
    return sig


def _percentile_signal(analysis, hazard: str, spells_key: str,
                       spell_kind: str, latest_key: str) -> Dict[str, Any]:
    """Shared extraction for heat / wind (same block shape)."""

    sig = _signal_skeleton(hazard)
    sig["status"] = analysis.status
    sig["summary"] = analysis.summary
    sig["unavailable_reason"] = analysis.unavailable_reason
    sig["evidence"] = list(analysis.evidence or [])
    if analysis.level is not None:
        sig["level"] = analysis.level.to_dict()
    blocks = analysis.blocks or {}
    cur = blocks.get("current_vs_climatology") or {}
    spells_block = blocks.get(spells_key) or {}

    pct = cur.get("percentile_vs_doy_climatology") if cur.get("status") == "ok" else None
    sig["values"] = {
        "percentile_vs_doy_climatology": pct,
        "latest": cur.get("latest") if cur.get("status") == "ok" else None,
        "level_label": analysis.level.label if analysis.level else None,
        "spell_ongoing": spells_block.get("ongoing"),
    }
    if pct is not None and pct >= _PCT_ELEVATED:
        sig["elevated"] = True
        sig["elevated_basis"] = (
            f"latest {latest_key} percentile {pct} >= {_PCT_ELEVATED:.0f} "
            f"vs the 1991-2020 day-of-year climatology (declared threshold)"
        )
    if spells_block.get("status") == "ok":
        sig["spells"] = list(spells_block.get("spells") or [])
        sig["spell_kind"] = spell_kind
        sig["spell_status"] = {"ongoing": bool(spells_block.get("ongoing")),
                               "count": spells_block.get("count")}
    sig["source"] = "ERA5 daily (Open-Meteo archive)"
    return sig


def _flood_signal(analysis) -> Dict[str, Any]:
    sig = _signal_skeleton("flood")
    sig["status"] = analysis.status
    sig["summary"] = analysis.summary
    sig["unavailable_reason"] = analysis.unavailable_reason
    sig["evidence"] = list(analysis.evidence or [])
    if analysis.level is not None:
        sig["level"] = analysis.level.to_dict()
    blocks = analysis.blocks or {}
    dis = blocks.get("river_discharge") or {}
    pr = blocks.get("extreme_precipitation") or {}

    dis_pct = dis.get("percentile_of_latest") if dis.get("status") == "ok" else None
    pr_pct = (pr.get("percentile_of_max_daily_vs_record")
              if pr.get("status") == "ok" else None)
    sig["values"] = {
        "discharge_percentile": dis_pct,
        "discharge_latest": dis.get("latest") if dis.get("status") == "ok" else None,
        "precipitation_percentile": pr_pct,
        "max_daily_precip_mm": pr.get("max_daily_precip_mm")
        if pr.get("status") == "ok" else None,
        "level_label": analysis.level.label if analysis.level else None,
    }
    breached = []
    if dis_pct is not None and dis_pct >= _PCT_ELEVATED:
        breached.append(f"river-discharge percentile {dis_pct}")
    if pr_pct is not None and pr_pct >= _PCT_ELEVATED:
        breached.append(f"extreme-precipitation percentile {pr_pct}")
    if breached:
        sig["elevated"] = True
        sig["elevated_basis"] = (
            " and ".join(breached)
            + f" >= {_PCT_ELEVATED:.0f} vs the location's own record (declared threshold)"
        )
    if dis.get("status") == "ok":
        sig["spells"] = list(dis.get("high_discharge_spells_last_year") or [])
        sig["spell_kind"] = "high_discharge"
        sig["spell_status"] = {"count_last_year": len(sig["spells"])}
    sig["source"] = "GloFAS river discharge + ERA5 precipitation (Open-Meteo)"
    return sig


def _fire_danger_signal(lat: float, lon: float) -> Dict[str, Any]:
    """Cheap fire-danger signal: ERA5 daily archive -> Canadian FWI System.

    This is deliberately NOT the full wildfire engine. Declared screening
    approximation: daily T_max / RH_mean / max wind / precipitation sum in
    place of noon-standard FWI inputs (same convention as
    src/dashboard/history.py).
    """

    sig = _signal_skeleton("wildfire")
    sig["spell_kind"] = "high_fwi"
    try:
        from ..dashboard import real_data as rd
        from ..prediction.fwi import compute_fwi_series
    except ImportError as exc:  # pragma: no cover - defensive
        sig["unavailable_reason"] = f"FWI dependencies unavailable: {exc}"
        return sig

    today = date.today()
    start = (today - timedelta(days=_FIRE_HISTORY_DAYS)).isoformat()
    end = (today - timedelta(days=_ARCHIVE_LAG_DAYS)).isoformat()
    try:
        archive = rd.fetch_weather_archive(lat, lon, start, end)
    except Exception as exc:
        sig["unavailable_reason"] = f"ERA5 fire-weather fetch failed: {exc}"
        return sig
    if "error" in archive:
        sig["unavailable_reason"] = archive["error"]
        return sig

    times = archive.get("time") or []
    tmax = archive.get("temperature_2m_max") or []
    rh = archive.get("relative_humidity_2m_mean") or []
    wind = archive.get("wind_speed_10m_max") or []
    rain = archive.get("precipitation_sum") or []
    series_in: List[Dict[str, Any]] = []
    for i, t in enumerate(times):
        if i >= len(tmax) or i >= len(rh) or i >= len(wind):
            break
        if tmax[i] is None or rh[i] is None or wind[i] is None:
            continue
        series_in.append({
            "date": t,
            "temp_c": float(tmax[i]),
            "rh_pct": float(rh[i]),
            "wind_kmh": float(wind[i]),
            "rain_mm": float(rain[i]) if i < len(rain) and rain[i] is not None else 0.0,
        })
    if len(series_in) < 5:
        sig["unavailable_reason"] = (
            "Insufficient ERA5 fire-weather days for an honest FWI series.")
        return sig

    fwi_days = compute_fwi_series(series_in)
    dates = [d.date for d in fwi_days]
    fwi_vals = [round(d.fwi, 1) for d in fwi_days]
    latest = fwi_days[-1]
    spells = _series.detect_spells(
        dates, fwi_vals, _FWI_ELEVATED, min_len=_FWI_SPELL_MIN_DAYS, above=True)

    sig["status"] = "ok"
    sig["summary"] = (
        f"Fire danger (FWI) {round(latest.fwi, 1)} on {latest.date} "
        f"({latest.danger_class}); ERA5 archive lag ~{_ARCHIVE_LAG_DAYS} days.")
    sig["values"] = {
        "fwi_latest": round(latest.fwi, 1),
        "fwi_latest_date": latest.date,
        "fwi_danger_class": latest.danger_class,
        "fwi_max_window": max(fwi_vals),
        "window": {"start": dates[0], "end": dates[-1]},
    }
    sig["level"] = {
        "label": latest.danger_class,
        "score": round(latest.fwi, 1),
        "basis": "Canadian FWI value mapped to EFFIS-style danger classes; "
                 "screening approximation (daily aggregates, not noon-standard "
                 "inputs). NOT the full wildfire engine.",
        "validated": False,
    }
    if latest.fwi >= _FWI_ELEVATED:
        sig["elevated"] = True
        sig["elevated_basis"] = (
            f"latest FWI {round(latest.fwi, 1)} >= {_FWI_ELEVATED:.0f} "
            f"(declared fire-danger threshold)"
        )
    sig["spells"] = spells
    sig["spell_status"] = {"count_window": len(spells),
                           "ongoing": bool(spells and spells[-1]["end"] == dates[-1])}
    sig["source"] = archive.get("source", "Reanalysis (ERA5 via Open-Meteo archive)")
    sig["evidence"] = [EvidenceRecord.modelled(
        sig["source"],
        method=(
            "Canadian Fire Weather Index (Van Wagner 1987; EFFIS danger "
            "classes) over the ERA5 daily archive. Screening approximation: "
            "T_max / RH_mean / max wind / 24 h precipitation in place of "
            "noon-standard inputs; northern-hemisphere day-length tables. "
            f"Archive lag ~{_ARCHIVE_LAG_DAYS} days. Fire danger is not fire "
            "occurrence."
        ),
        temporal=TemporalClass.HISTORICAL.value,
        dataset="ERA5 daily Tmax / RH / wind / precipitation",
        provider_url="https://open-meteo.com/en/docs/historical-weather-api",
        location={"lat": lat, "lon": lon},
        reference_period={"start": dates[0], "end": dates[-1]},
        resolution="~25 km reanalysis grid",
        limitations="Reanalysis, not station measurements; FWI codes seeded "
                    "with conventional startup values at the window start.",
        confidence=Confidence.MEDIUM.value,
    ).to_dict()]
    return sig


_EXTRACTORS = {
    "drought": _drought_signal,
    "heat": lambda a: _percentile_signal(a, "heat", "heatwave_spells", "heatwave", "Tmax"),
    "wind": lambda a: _percentile_signal(a, "wind", "storm_spells", "storm", "gust"),
    "flood": _flood_signal,
}


@cached("compound_light_signals", TTL_COMPOUND)
def extract_light_signals(
    lat: float,
    lon: float,
    hazards: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Run the LIGHT per-hazard analyzers and extract real current signals.

    Shared by the compound engine and the cascading graph — import this, do
    not duplicate. Per-hazard failures are tolerated honestly: the hazard is
    recorded in ``hazards_unavailable`` and dropped from the signal set.
    Cached 1 h.
    """

    from . import registry

    lat, lon = float(lat), float(lon)
    selected = list(hazards) if hazards else list(KNOWN_HAZARDS)
    signals: Dict[str, Any] = {}
    unavailable: List[Dict[str, str]] = []

    for hid in selected:
        if hid not in KNOWN_HAZARDS:
            unavailable.append({"hazard": str(hid),
                                "reason": f"Unknown hazard '{hid}' for compound analysis."})
            continue
        if hid == "wildfire":
            sig = _fire_danger_signal(lat, lon)
        else:
            module = registry.get(hid)
            if module is None:
                unavailable.append({"hazard": hid,
                                    "reason": "Hazard module not registered in this checkout."})
                continue
            try:
                analysis = module.analyze(lat, lon)
            except Exception as exc:  # tolerate hazards that fail
                unavailable.append({"hazard": hid, "reason": str(exc)})
                continue
            try:
                sig = _EXTRACTORS[hid](analysis)
            except Exception as exc:  # pragma: no cover - defensive
                unavailable.append({"hazard": hid,
                                    "reason": f"signal extraction failed: {exc}"})
                continue
        if sig["status"] == "unavailable":
            unavailable.append({
                "hazard": hid,
                "reason": sig.get("unavailable_reason") or "analysis unavailable",
            })
        else:
            signals[hid] = sig

    latest_dates = []
    for sig in signals.values():
        v = sig.get("values") or {}
        cand = v.get("fwi_latest_date")
        if cand is None and isinstance(v.get("latest"), dict):
            cand = v["latest"].get("date")
        if cand is None and isinstance(v.get("discharge_latest"), dict):
            cand = v["discharge_latest"].get("date")
        if cand is None and isinstance(v.get("soil_moisture"), dict):
            cand = v["soil_moisture"].get("as_of")
        if cand:
            latest_dates.append(str(cand))
    as_of = max(latest_dates) if latest_dates else None

    return {
        "location": {"lat": lat, "lon": lon},
        "generated_at": _utcnow_iso(),
        "as_of": as_of,
        "signals": signals,
        "hazards_unavailable": unavailable,
        "thresholds": dict(ELEVATED_THRESHOLDS),
    }


# ---------------------------------------------------------------------------
# Typology detectors (declared, qualitative — zscheischler2020typology)
# ---------------------------------------------------------------------------


def _merged_evidence(signals: Dict[str, Any], hazard_ids: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for hid in hazard_ids:
        sig = signals.get(hid) or {}
        out.extend(sig.get("evidence") or [])
    return out


def _detect_multivariate(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """≥2 hazards simultaneously above their declared elevated thresholds."""

    elevated = {hid: s for hid, s in signals.items() if s.get("elevated")}
    if len(elevated) < 2:
        return []
    ids = sorted(elevated)
    return [{
        "type": "multivariate",
        "hazards": ids,
        "values": {
            hid: {
                "elevated_basis": elevated[hid]["elevated_basis"],
                "level_label": (elevated[hid].get("level") or {}).get("label"),
                "values": elevated[hid].get("values"),
            }
            for hid in ids
        },
        "claim_status": ClaimStatus.MODELLED.value,
        "temporal": TemporalClass.OBSERVED.value,
        "basis": (
            "Multivariate compound signal (zscheischler2020typology): "
            f"{len(ids)} hazards simultaneously above their declared elevated "
            "thresholds at this location in the current analysis window."
        ),
        "method": "Co-occurrence of elevated per-hazard screening signals; "
                  "thresholds declared in the payload.",
        "evidence": _merged_evidence(signals, ids),
        "research": ["zscheischler2020typology", "ipccar6wg2"],
    }]


def _detect_temporal(
    signals: Dict[str, Any],
    as_of: Optional[str],
    window_days: int = _TEMPORAL_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """A hazard spell following another within the trailing window."""

    end = _series.parse_date(as_of) if as_of else None
    if end is None:
        return []
    start = end - timedelta(days=window_days)
    out: List[Dict[str, Any]] = []

    for first, second in _TEMPORAL_PAIRS:
        sig_a = signals.get(first) or {}
        sig_b = signals.get(second) or {}
        spells_a = sig_a.get("spells") or []
        spells_b = sig_b.get("spells") or []
        if not spells_a or not spells_b:
            continue
        sequences: List[Dict[str, Any]] = []
        for sa in spells_a:
            end_a = _series.parse_date(sa.get("end"))
            if end_a is None or end_a < start:
                continue
            for sb in spells_b:
                start_b = _series.parse_date(sb.get("start"))
                end_b = _series.parse_date(sb.get("end"))
                if start_b is None or end_b is None:
                    continue
                if start_b <= end_a or end_b > end:
                    continue
                sequences.append({
                    "preceding": {"hazard": first,
                                  "spell_kind": sig_a.get("spell_kind"),
                                  "spell": sa},
                    "following": {"hazard": second,
                                  "spell_kind": sig_b.get("spell_kind"),
                                  "spell": sb},
                    "gap_days": (start_b - end_a).days,
                })
        if not sequences:
            continue
        sequences.sort(key=lambda s: (s["following"]["spell"].get("start"), s["gap_days"]))
        out.append({
            "type": "temporally_compounding",
            "hazards": [first, second],
            "sequences": sequences[:5],
            "sequence_count": len(sequences),
            "window": {"start": start.isoformat(), "end": end.isoformat(),
                       "days": window_days},
            "claim_status": ClaimStatus.MODELLED.value,
            "temporal": TemporalClass.HISTORICAL.value,
            "basis": (
                "Temporally compounding signal (zscheischler2020typology): a "
                f"{sig_a.get('spell_kind')} spell was followed by a "
                f"{sig_b.get('spell_kind')} spell within the trailing "
                f"{window_days}-day window (real dates reported)."
            ),
            "method": "Spell pairs from the daily series where the following "
                      "spell starts after the preceding spell ends; both "
                      "inside the trailing window.",
            "evidence": _merged_evidence(signals, [first, second]),
            "research": ["zscheischler2020typology", "ipccar6wg2"],
        })
    return out


def _detect_preconditioned(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Antecedent conditions that plausibly amplify a current hazard — always
    labelled INFERRED with the mechanism declared."""

    out: List[Dict[str, Any]] = []
    drought = signals.get("drought") or {}
    fire = signals.get("wildfire") or {}
    heat = signals.get("heat") or {}

    dvals = drought.get("values") or {}
    fvals = fire.get("values") or {}
    hvals = heat.get("values") or {}

    # 90-day precipitation deficit amplifying current fire danger.
    p90 = dvals.get("precipitation_90d") or {}
    deficit_mm = p90.get("deficit_mm")
    fwi_latest = fvals.get("fwi_latest")
    if (deficit_mm is not None and deficit_mm > 0
            and fwi_latest is not None and fwi_latest >= _FWI_ELEVATED):
        out.append({
            "type": "preconditioned",
            "hazards": ["drought", "wildfire"],
            "values": {
                "precipitation_deficit_90d_mm": deficit_mm,
                "deficit_period": p90.get("period"),
                "deficit_standardized_anomaly": p90.get("standardized_anomaly"),
                "fwi_latest": fwi_latest,
                "fwi_latest_date": fvals.get("fwi_latest_date"),
            },
            "claim_status": ClaimStatus.INFERRED.value,
            "temporal": TemporalClass.OBSERVED.value,
            "mechanism": (
                f"Antecedent 90-day precipitation deficit of {deficit_mm} mm "
                f"({p90.get('period', {}).get('start')} to "
                f"{p90.get('period', {}).get('end')}) plausibly amplifies the "
                f"current fire danger (FWI {fwi_latest} >= {_FWI_ELEVATED:.0f}): "
                "sustained deficit dries fuels, raising fire danger for a "
                "given weather day."
            ),
            "basis": "Preconditioned compound signal (zscheischler2020typology): "
                     "an antecedent condition plausibly amplifying a current "
                     "hazard. INFERRED — the amplification pathway is declared, "
                     "not measured.",
            "evidence": _merged_evidence(signals, ["drought", "wildfire"]),
            "research": ["zscheischler2020typology", "ipccar6wg2"],
        })

    # Soil-moisture deficit amplifying an ongoing heat spell.
    soil = dvals.get("soil_moisture") or {}
    soil_anom = soil.get("anomaly_m3m3")
    heat_ongoing = bool(hvals.get("spell_ongoing"))
    if soil_anom is not None and soil_anom < 0 and heat_ongoing:
        out.append({
            "type": "preconditioned",
            "hazards": ["drought", "heat"],
            "values": {
                "soil_moisture_anomaly_m3m3": soil_anom,
                "soil_moisture_percentile": soil.get("percentile_vs_climatology"),
                "soil_moisture_as_of": soil.get("as_of"),
                "heat_spell_ongoing": True,
                "heat_latest": hvals.get("latest"),
            },
            "claim_status": ClaimStatus.INFERRED.value,
            "temporal": TemporalClass.OBSERVED.value,
            "mechanism": (
                f"Soil-moisture deficit ({soil_anom} m³/m³ vs the day-of-year "
                "climatology) during an ongoing heat spell plausibly amplifies "
                "it: dry soils reduce evaporative cooling, so more incoming "
                "energy heats the surface and near-surface air "
                "(land–atmosphere coupling)."
            ),
            "basis": "Preconditioned compound signal (zscheischler2020typology): "
                     "an antecedent condition plausibly amplifying a current "
                     "hazard. INFERRED — the amplification pathway is declared, "
                     "not measured.",
            "evidence": _merged_evidence(signals, ["drought", "heat"]),
            "research": ["zscheischler2020typology", "ipccar6wg2"],
        })
    return out


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@cached("compound_assess", TTL_COMPOUND)
def assess_compound(
    lat: float,
    lon: float,
    *,
    hazards: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Compound-risk assessment for a point. Cached 1 h.

    Returns a qualitative signal list — never a numeric compound score.
    """

    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"error": "Coordinates out of range"}

    extracted = extract_light_signals(lat, lon, hazards=list(hazards) if hazards else None)
    signals: Dict[str, Any] = extracted["signals"]
    unavailable: List[Dict[str, str]] = extracted["hazards_unavailable"]

    compound_signals: List[Dict[str, Any]] = []
    compound_signals.extend(_detect_multivariate(signals))
    compound_signals.extend(_detect_temporal(signals, extracted.get("as_of")))
    compound_signals.extend(_detect_preconditioned(signals))

    analysed = sorted(set(signals) | {u["hazard"] for u in unavailable})
    if not signals:
        status = "unavailable"
    elif unavailable:
        status = "partial"
    else:
        status = "ok"

    per_hazard_sources = {
        hid: sig.get("source") for hid, sig in sorted(signals.items())
    }

    return {
        "status": status,
        "location": {"lat": lat, "lon": lon},
        "generated_at": extracted["generated_at"],
        "as_of": extracted.get("as_of"),
        "hazards_analysed": analysed,
        "hazards_unavailable": unavailable,
        "hazard_signals": signals,
        "thresholds": extracted["thresholds"],
        "compound_signals": compound_signals,
        "no_compound_signal": None if compound_signals else {
            "status": "no_compound_signal",
            "statement": _NO_SIGNAL_STATEMENT,
        },
        "spatially_compounding": {
            "status": "not_computable",
            "reason": _SPATIALLY_NOT_COMPUTABLE_REASON,
        },
        "uncertainty": {
            "confidence": Confidence.LOW.value,
            "note": "Screening-level qualitative detection over reanalysis-based "
                    "hazard signals; not a validated compound-event predictor.",
            "sources_of_uncertainty": [
                "ERA5/ERA5-Land reanalysis (~11-25 km grid), not station measurements",
                f"Open-Meteo archive lag ~{_ARCHIVE_LAG_DAYS} days behind real time",
                "Declared screening thresholds; no calibrated joint-probability model",
                "FWI screening approximation (daily aggregates; northern-hemisphere "
                "day-length tables)",
            ],
        },
        "limitations": [
            _NO_NUMERIC_SCORE_NOTE,
            _SPATIALLY_NOT_COMPUTABLE_REASON,
            "Fire danger is not fire occurrence; high FWI means conditions "
            "favour spread IF an ignition happens.",
            "Preconditioned signals are INFERRED: the amplification mechanism "
            "is declared, not measured.",
        ],
        "provenance": {
            "engine": "compound_risk_v1",
            "typology_basis": _TYPOLOGY_BASIS,
            "research": [
                {"id": "zscheischler2020typology",
                 "role": "four-class compound-event typology (declared detector on top)"},
                {"id": "ipccar6wg2",
                 "role": "risk framework: hazard x exposure x vulnerability; "
                         "compound/cascading risk"},
            ],
            "per_hazard_sources": per_hazard_sources,
            "no_numeric_score": _NO_NUMERIC_SCORE_NOTE,
        },
    }

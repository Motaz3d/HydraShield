"""
Public multi-hazard snapshot ("what is elevated right now — per hazard").

Companion to ``snapshot.py`` (which carries the detailed wildfire ranking).
For every other registered hazard (flood, drought, heat, wind, coastal,
cyclone, …) this computes the current level at each configured monitored
area via the hazard modules' real ``analyze()`` pipeline — the same engine
behind ``/api/v2/analyze`` — and caches the aggregate (30-min TTL; each
underlying analysis is itself cached 15 min, shared with the API).

Honesty rules (docs/EVIDENCE_ARCHITECTURE.md):
    - Only ``ok``/``partial`` analyses produce entries; areas whose real
      analysis is unavailable are omitted and counted — never filled in.
    - Levels stay labelled as screening indicators (``basis``/``validated``
      come straight from the module's HazardLevel).
    - The monitored-area scope is part of the response; the UI can never
      imply global coverage.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .cache import cached, default_cache, TTL_SNAPSHOT
from .snapshot import load_monitored_areas

_CACHE_KEY = "hazard_snapshot:current"
TTL_SNAPSHOT_FAILED = 60.0
_build_lock = threading.Lock()

# Wildfire keeps its own detailed snapshot (snapshot.py); the multi-hazard
# board covers every other registered hazard.
_SKIP_HAZARDS = ("wildfire",)

# Per-hazard top-k within the monitored areas.
_TOP_PER_HAZARD = 3


@cached("hazard_snapshot_analysis", 3600.0)
def cached_hazard_analysis(hazard_id: str, lat: float, lon: float, name: str) -> Dict:
    """Cached per-hazard analysis for a point (1 h TTL — the board rebuilds
    every 30 min, so a longer TTL keeps rebuilds fast and upstreams calm)."""
    from ..climate import registry

    module = registry.get(hazard_id)
    if module is None:
        return {"error": f"unknown hazard {hazard_id}"}
    available, reason = module.availability()
    if not available:
        return {"error": reason or "unavailable"}
    return module.analyze(lat, lon, name=name or None).to_dict(include_raw=False)


def _entry(area: Dict, result: Dict) -> Optional[Dict]:
    """Reduce a HazardAnalysis dict to a compact board entry (None when the
    real analysis was not ok/partial — the area is omitted, never faked)."""
    if not isinstance(result, dict) or result.get("error"):
        return None
    if result.get("status") not in ("ok", "partial"):
        return None
    level = result.get("level") or {}
    return {
        "name": area["name"],
        "latitude": round(float(area["lat"]), 4),
        "longitude": round(float(area["lon"]), 4),
        "status": result.get("status"),
        "level_label": level.get("label"),
        "level_score": level.get("score"),
        "level_score_max": level.get("score_max"),
        "level_basis": level.get("basis"),
        "validated": bool(level.get("validated")),
        "summary": (result.get("summary") or "")[:240],
    }


def compute_hazard_snapshot(
    config_path: Optional[str] = None,
    analyse_fn: Optional[Callable[[str, float, float, str], Dict]] = None,
) -> Dict:
    """Build the multi-hazard board from real analyses of the monitored
    areas. Hazards × areas are analysed concurrently (4 workers); each
    underlying analysis is cached, so warm rebuilds are fast."""
    analyse = analyse_fn or cached_hazard_analysis
    generated_at = datetime.utcnow().isoformat() + "Z"

    from ..climate import registry

    hazards = [d for d in registry.descriptors()
               if d.get("id") not in _SKIP_HAZARDS and d.get("enabled", True)]

    try:
        cfg = load_monitored_areas(config_path)
    except (OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "message": f"Monitored-area configuration problem: {exc}",
            "generated_at": generated_at,
            "hazards": [],
        }

    def _run(job):
        hazard, area = job
        try:
            result = analyse(hazard["id"], round(area["lat"], 4),
                             round(area["lon"], 4), area["name"])
        except Exception:
            return hazard["id"], None
        return hazard["id"], _entry(area, result)

    jobs = [(h, a) for h in hazards for a in cfg.areas]
    per_hazard: Dict[str, List[Dict]] = {h["id"]: [] for h in hazards}
    # Sequential: real analyses can each load heavy context (OSM/Overpass,
    # exposure rasters); two concurrent floods peaked >3.5 GB and the kernel
    # OOM-killed the builder in production. One-at-a-time keeps the peak to
    # a single analysis; the 1 h per-analysis cache keeps rebuilds fast.
    with ThreadPoolExecutor(max_workers=1) as pool:
        for hazard_id, entry in pool.map(_run, jobs):
            if entry is not None:
                per_hazard.setdefault(hazard_id, []).append(entry)

    out_hazards = []
    for h in hazards:
        entries = per_hazard.get(h["id"]) or []
        entries.sort(key=lambda e: (e["level_score"] is None,
                                    -(e["level_score"] or 0)))
        top = entries[:_TOP_PER_HAZARD]
        for rank, entry in enumerate(top, start=1):
            entry["rank"] = rank
        out_hazards.append({
            "hazard": h["id"],
            "name": h.get("name"),
            "tagline": h.get("tagline"),
            "areas_considered": len(cfg.areas),
            "areas_with_data": len(entries),
            "entries": top,
        })

    if not any(hz["entries"] for hz in out_hazards):
        return {
            "status": "unavailable",
            "message": "Multi-hazard snapshot temporarily unavailable — no "
                       "monitored area could be analysed from real data right now.",
            "generated_at": generated_at,
            "scope": cfg.scope,
            "hazards": out_hazards,
        }

    return {
        "status": "ok",
        "scope": cfg.scope,
        "generated_at": generated_at,
        "valid_for_seconds": int(TTL_SNAPSHOT),
        "hazards": out_hazards,
        "model": {
            "note": "Per-hazard levels from the same real analysis engine as "
                    "/api/v2/analyze; levels are screening indicators unless "
                    "explicitly validated.",
        },
        "data_policy": "Real data only; areas without a computable real level "
                       "are omitted, never estimated.",
    }


def get_hazard_snapshot(
    config_path: Optional[str] = None,
    analyse_fn: Optional[Callable[[str, float, float, str], Dict]] = None,
    build: bool = False,
) -> Dict:
    """
    Return the cached multi-hazard snapshot.

    Cold builds are deliberately NOT run on the request path: 8 hazards ×
    10 monitored areas of real upstream analyses can OOM/hang a gunicorn
    worker (observed in production — SIGKILL, 502). The board is built
    periodically by the watch_checker (``scripts/build_risk_snapshot.py``
    passes ``build=True``); on a cache miss the request path reports an
    honest "warming" state and /api/risk-snapshot simply omits the key.
    """
    cache = default_cache()
    hit = cache.get(_CACHE_KEY)
    if hit is not None:
        return hit
    if not build:
        return {
            "status": "unavailable",
            "message": "Multi-hazard snapshot is warming — it is rebuilt "
                       "periodically by the platform (every 30 minutes).",
            "hazards": [],
        }

    with _build_lock:
        hit = cache.get(_CACHE_KEY)
        if hit is not None:
            return hit
        snapshot = compute_hazard_snapshot(config_path=config_path,
                                           analyse_fn=analyse_fn)
        ttl = TTL_SNAPSHOT if snapshot.get("status") == "ok" else TTL_SNAPSHOT_FAILED
        cache.set(_CACHE_KEY, snapshot, ttl)
        return snapshot

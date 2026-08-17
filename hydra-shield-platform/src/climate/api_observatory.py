"""
/api/v2 observatory — source intelligence + reproducible analysis runs.

Read-only API over two audit stores:

- ``source_health`` (src/climate/source_health.py) — health history of the
  integrated data sources, written ONLY by scripts/check_source_health.py.
  Before the first checker run the endpoint answers an honest empty state.
- ``analysis_runs`` (src/dashboard/analysis_runs.py) — reproducible
  analysis-run records written by /api/v2/analyze.

Registered from `src/dashboard/api.py::create_app()` (lead wires it);
keeps the v2 honesty contract: no fabricated health or run data anywhere.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .api_v2 import _err, _parse_latlon, _rate  # shared v2 plumbing

observatory_bp = Blueprint("observatory", __name__, url_prefix="/api/v2")


# ---------------------------------------------------------------------------
# Source health (Source Intelligence layer)
# ---------------------------------------------------------------------------


@observatory_bp.get("/source-health")
def source_health():
    """Latest health of integrated sources: /api/v2/source-health?dataset_id=…

    Health records exist only after scripts/check_source_health.py has run
    (watch_checker loop). Before that, an honest empty state is returned —
    no health is ever assumed.
    """
    if not _rate("v2sourcehealth", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import source_health as source_health_module

    dataset_id = (request.args.get("dataset_id") or "").strip() or None
    body = source_health_module.latest_health(dataset_id=dataset_id)

    if not body["datasets"]:
        body["note"] = (
            "No source-health checks recorded yet. Health records are "
            "created only when scripts/check_source_health.py runs "
            "(watch_checker loop) — nothing is assumed about a source "
            "until it has actually been probed."
        )
    else:
        body["note"] = (
            "Latest recorded probe per integrated source. health is a "
            "screening label: ok (service answered — any status < 500; "
            "http_status keeps the exact answer, e.g. 400 for POST-only "
            "endpoints) | degraded (reachable but slow) | down (5xx, "
            "timeout or unreachable) | unknown (never probed). Candidate "
            "sources are not probed — nothing is wired to them."
        )
    return jsonify(body)


# ---------------------------------------------------------------------------
# Analysis runs (reproducible analysis layer)
# ---------------------------------------------------------------------------


@observatory_bp.get("/analysis-runs")
def analysis_runs_list():
    """Recorded analysis runs: /api/v2/analysis-runs?hazard=…&limit=…"""
    if not _rate("v2analysisruns", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard import analysis_runs

    hazard = (request.args.get("hazard") or "").strip().lower() or None
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return _err("limit must be an integer", 400)
    if not (1 <= limit <= 200):
        return _err("limit must be between 1 and 200", 400)

    runs = analysis_runs.list_runs(limit=limit, hazard=hazard)
    return jsonify({
        "runs": runs,
        "count": len(runs),
        "filters": {"hazard": hazard, "limit": limit},
        "note": ("analysis_id is a content hash over the canonical basis "
                 "(endpoint, hazard, location, params, result hash, "
                 "model/dataset versions, methodology, uncertainty, "
                 "evidence) — volatile request timestamps are excluded, "
                 "so a reproduced analysis maps to the same id."),
    })


@observatory_bp.get("/analysis-runs/<analysis_id>")
def analysis_run_detail(analysis_id: str):
    """One recorded run by id; honest 404 when unknown."""
    if not _rate("v2analysisruns", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard import analysis_runs

    run = analysis_runs.get_run(analysis_id)
    if run is None:
        return _err(f"Unknown analysis run '{analysis_id}'. "
                    "See /api/v2/analysis-runs.", 404)
    return jsonify(run)

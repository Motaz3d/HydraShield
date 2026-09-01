"""
TX Engine API blueprint (``/api/tx/...``) — the website's thin web adapter
over :mod:`tx_core`.

This is the *first* web surface of the TX engine and is strictly additive:
it registers new routes only and does not touch the existing v1/v2 API
contracts, so the live site keeps running exactly as before.

Endpoints:

    GET  /api/tx/health     Engine + registry availability
    GET  /api/tx/version    Engine versions (tx / engine / TAM + levels)
    GET  /api/tx/hazards    Registered TX hazards (descriptors)
    GET  /api/tx/sources    Official data sources behind TX hazards
    GET  /api/tx/registry   TX Registry digest (models/datasets/sources)
    GET  /api/tx/analyze    Run a TX analysis (?lat=..&lon=..[&hazard=..][&analysis=..][&depth=..])
    POST /api/tx/run        Submit an analysis job {lat, lon, [hazards], [analyses], [depth], [name]}
    GET  /api/tx/jobs/<id>  Poll job status + progress
    GET  /api/tx/jobs/<id>/result  Fetch the TxResult envelope (when succeeded)
    GET  /api/tx/products   Registered TX product engines (TX-2+ analyses)

Honesty contract: TX never invents numbers — hazards without real data are
reported as ``status="unavailable"`` with a reason, never as fabricated
scores. Failed jobs report the real error, never a fabricated result.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from tx_core._version import TX_VERSION
from tx_core.engine import DEPTHS, TXEngine
from tx_core.jobs import TxJob, TxJobRunner, TxJobStore
from tx_core.registry import TXRegistry

tx_bp = Blueprint("tx", __name__, url_prefix="/api/tx")

DEPTH_CHOICES = DEPTHS


def _engine() -> TXEngine:
    return TXEngine()


# Phase-1 job backend: one in-process runner per app (thread-safe store +
# bounded thread pool). Tests replace ``_JOB_RUNNER`` with a synchronous
# runner over an injected fake engine. A future Redis/queue backend only
# swaps this factory — the routes and the job contract stay unchanged.
_JOB_RUNNER: Optional[TxJobRunner] = None


def _job_runner() -> TxJobRunner:
    global _JOB_RUNNER
    if _JOB_RUNNER is None:
        _JOB_RUNNER = TxJobRunner(store=TxJobStore(), engine_factory=_engine)
    return _JOB_RUNNER


def _coords() -> Tuple[float, float]:
    raw_lat = request.args.get("lat")
    raw_lon = request.args.get("lon")
    try:
        lat = float(raw_lat) if raw_lat is not None else None
        lon = float(raw_lon) if raw_lon is not None else None
    except (TypeError, ValueError):
        raise ValueError("lat/lon must be numeric")
    if lat is None or lon is None:
        raise ValueError("lat and lon query parameters are required")
    return lat, lon


def _error(message: str, status: int = 400) -> Any:
    return jsonify({"error": message}), status


@tx_bp.get("/health")
def health() -> Any:
    registry = TXRegistry()
    return jsonify(
        {
            "status": "ok",
            "tx_version": TX_VERSION,
            "registry": {
                "hazards": registry.hazard_ids(),
                "models": len(registry.models()),
                "sources_integrated": len(registry.integrated_sources()),
            },
        }
    )


@tx_bp.get("/version")
def version() -> Any:
    return jsonify(_engine().version_info())


@tx_bp.get("/hazards")
def hazards() -> Any:
    return jsonify({"hazards": _engine().hazards()})


@tx_bp.get("/products")
def products() -> Any:
    return jsonify({"products": _engine().products()})


@tx_bp.get("/sources")
def sources() -> Any:
    return jsonify({"sources": _engine().sources()})


@tx_bp.get("/registry")
def registry() -> Any:
    return jsonify(TXRegistry().summary())


@tx_bp.get("/analyze")
def analyze() -> Any:
    try:
        lat, lon = _coords()
    except ValueError as exc:
        return _error(str(exc))

    depth = (request.args.get("depth") or "standard").lower()
    if depth not in DEPTH_CHOICES:
        return _error(f"depth must be one of {DEPTH_CHOICES}")

    hazards_raw = request.args.getlist("hazard") or request.args.get("hazards")
    hazards: Optional[list] = None
    if hazards_raw:
        if isinstance(hazards_raw, str):
            hazards = [h.strip() for h in hazards_raw.split(",") if h.strip()]
        else:
            hazards = [h for h in hazards_raw if h]

    analyses_raw = (request.args.getlist("analysis")
                    or request.args.get("analyses"))
    analyses: Optional[list] = None
    if analyses_raw:
        if isinstance(analyses_raw, str):
            analyses = [a.strip() for a in analyses_raw.split(",") if a.strip()]
        else:
            analyses = [a for a in analyses_raw if a]

    try:
        result = _engine().analyze(
            lat=lat, lon=lon, hazards=hazards, depth=depth,
            name=request.args.get("name"), analyses=analyses,
        )
    except ValueError as exc:
        return _error(str(exc))
    return jsonify(result.to_dict())


# ---------------------------------------------------------------------------
# Standard TX Job Object — async deep analyses (submit → poll → result)
# ---------------------------------------------------------------------------

def _job_payload(job: TxJob) -> Dict[str, Any]:
    """The job status payload plus its hypermedia links."""
    payload = job.to_status_dict()
    payload["poll"] = f"/api/tx/jobs/{job.job_id}"
    payload["result_url"] = f"/api/tx/jobs/{job.job_id}/result"
    return payload


def _run_request_body() -> Tuple[Optional[Dict[str, Any]], Optional[Any]]:
    """Validate the POST /api/tx/run JSON body.

    Returns ``(params, None)`` on success or ``(None, error_response)``.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, _error(
            "JSON body required: {lat, lon, [hazards], [analyses], [depth], [name]}"
        )
    try:
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
    except (TypeError, ValueError):
        return None, _error("lat and lon are required and must be numeric")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None, _error(f"Invalid coordinates: lat={lat}, lon={lon}")

    depth = str(body.get("depth") or "standard").lower()
    if depth not in DEPTH_CHOICES:
        return None, _error(f"depth must be one of {DEPTH_CHOICES}")

    hazards_raw = body.get("hazards")
    hazards: Optional[List[str]] = None
    if isinstance(hazards_raw, str):
        hazards = [h.strip() for h in hazards_raw.split(",") if h.strip()]
    elif isinstance(hazards_raw, list):
        hazards = [str(h) for h in hazards_raw if str(h).strip()]
    elif hazards_raw is not None:
        return None, _error(
            "hazards must be a list of hazard ids or a comma-separated string"
        )

    analyses_raw = body.get("analyses")
    analyses: Optional[List[str]] = None
    if isinstance(analyses_raw, str):
        analyses = [a.strip() for a in analyses_raw.split(",") if a.strip()]
    elif isinstance(analyses_raw, list):
        analyses = [str(a) for a in analyses_raw if str(a).strip()]
    elif analyses_raw is not None:
        return None, _error(
            "analyses must be a list of product ids or a comma-separated string"
        )

    name = body.get("name")
    return (
        {
            "lat": lat,
            "lon": lon,
            "hazards": hazards,
            "analyses": analyses,
            "depth": depth,
            "name": str(name) if name is not None else None,
        },
        None,
    )


@tx_bp.post("/run")
def run() -> Any:
    params, error = _run_request_body()
    if error is not None:
        return error
    assert params is not None
    job, created = _job_runner().submit(**params)
    # 202 = new job accepted; 200 = idempotent resubmission of the same
    # request (deterministic job id) — the client polls either way.
    return jsonify(_job_payload(job)), (202 if created else 200)


@tx_bp.get("/jobs/<job_id>")
def job_status(job_id: str) -> Any:
    job = _job_runner().get(job_id)
    if job is None:
        return _error(f"Unknown job_id: {job_id}", 404)
    return jsonify(_job_payload(job))


@tx_bp.get("/jobs/<job_id>/result")
def job_result(job_id: str) -> Any:
    job = _job_runner().get(job_id)
    if job is None:
        return _error(f"Unknown job_id: {job_id}", 404)
    if job.status != "succeeded":
        # Honest state: not ready yet, or failed with the real error.
        return jsonify(
            {
                "error": (
                    f"Job {job_id} is not finished (status={job.status})."
                    if job.status in ("queued", "running")
                    else f"Job {job_id} failed: {job.error}"
                ),
                "status": job.status,
                "poll": f"/api/tx/jobs/{job.job_id}",
            }
        ), 409
    return jsonify(job.result)

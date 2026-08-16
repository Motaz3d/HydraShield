"""
HydraShield REST API.

Public, honest, real-data endpoints:

    GET  /api/health            Service + cache status
    GET  /api/analyze           Full real-data analysis for a location
                                (?location=...  or  ?lat=...&lon=...)
    GET  /api/risk-grid         n x n fire-danger grid over a bbox (GeoJSON)
    GET  /api/risk-snapshot     Public top-risk ranking over the configured
                                monitored areas (real data, cached)
    GET  /api/history           "Lessons from the Past": recent fire-danger
                                history + observed fires + what HydraShield
                                would have recommended (real ERA5 + FIRMS)
    GET  /api/report            Professional PDF report for a location,
                                built from the same real cached analysis
    POST /api/analysis-jobs     Start a progressive (staged) analysis job
    GET  /api/analysis-jobs/id  Poll honest stage states + final result
    POST /api/watch             Register a threshold alert watch
    DELETE /api/watch/<id>      Remove a watch
    POST /api/spread            Fire-spread model evaluation (caller-supplied inputs)
    POST /api/allocation        Water allocation across caller-supplied zones
    POST /api/risk              DEPRECATED compatibility shim -> real analysis

No endpoint returns simulated data. When an upstream source is unavailable
the corresponding component is reported as unavailable in the provenance
block.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

from flask import Flask, jsonify, request

from ..prediction.fire_spread import FireSpreadModel
from ..hydration_control.water_optimiser import WaterOptimiser
from .cache import default_cache
from .snapshot import cached_analysis as _cached_analysis
from . import grid as grid_module
from . import history as history_module
from . import jobs as jobs_module
from . import snapshot as snapshot_module
from .monitoring import WatchStore


# --------------------------------------------------------------------------
# Rate limiting (per client IP, sliding window)
# --------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, list] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, max_requests: int, window_seconds: float) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, [])
            cutoff = now - window_seconds
            bucket[:] = [t for t in bucket if t >= cutoff]
            if len(bucket) >= max_requests:
                return False
            bucket.append(now)
            return True


_rate_limiter = _RateLimiter()


def _client_key() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _parse_point(args) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Parse & validate lat/lon from request args. Returns (lat, lon, error)."""
    try:
        lat = float(args.get("lat"))
        lon = float(args.get("lon"))
    except (TypeError, ValueError):
        return None, None, "lat and lon must be numbers"
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None, "lat/lon out of range"
    return lat, lon, None


def _error(message: str, status: int):
    return jsonify({"error": message, "status": status}), status


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/watch") else resp.headers.get("Cache-Control", "")
        return resp

    # ------------------------------------------------------------------
    @app.route("/api/health", methods=["GET"])
    def health():
        cache = default_cache()
        try:
            stats = cache.stats()
            cache_ok = True
        except Exception:
            stats = {}
            cache_ok = False
        return jsonify(
            {
                "status": "ok" if cache_ok else "degraded",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "cache": stats,
                "firms_configured": bool(__import__("os").environ.get("FIRMS_MAP_KEY")),
                "version": "1.0.0",
            }
        )

    # ------------------------------------------------------------------
    @app.route("/api/status", methods=["GET"])
    def status():
        return jsonify(
            {
                "status": "running",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "modules": ["prediction", "gis_mapping", "hydration_control", "dashboard"],
                "data_policy": "real data only; unavailable sources are reported, never simulated",
            }
        )

    # ------------------------------------------------------------------
    @app.route("/api/analyze", methods=["GET"])
    def analyze():
        if not _rate_limiter.allow(f"analyze:{_client_key()}", 30, 60.0):
            return _error("Rate limit exceeded (30 requests/minute)", 429)

        location = (request.args.get("location") or "").strip()[:200]
        if location:
            from .real_data import geocode_location

            geo = geocode_location(location)
            if "error" in geo:
                return _error(geo["error"], 404)
            lat, lon, name = geo["lat"], geo["lon"], geo["name"]
        else:
            lat, lon, err = _parse_point(request.args)
            if err:
                return _error("Provide ?location=... or ?lat=...&lon=...", 400)
            name = f"{lat:.4f}, {lon:.4f}"

        try:
            result = _cached_analysis(round(lat, 4), round(lon, 4), name)
        except Exception as exc:
            return _error(f"Analysis failed: {exc}", 502)
        if "error" in result:
            return _error(result["error"], 404)
        if location:
            # Record the geocoding step in the provenance block (the cached
            # point analysis itself only covers the data components).
            result = dict(result)
            result["provenance"] = dict(result.get("provenance") or {})
            result["provenance"]["geocoding"] = {
                "kind": "observed",
                "source": "Nominatim (OpenStreetMap)",
                "acquired": None,
                "resolution": "point",
                "temporal": None,
                "retrieved_at": datetime.utcnow().isoformat() + "Z",
                "quality": "ok",
                "limitations": None,
            }
        return jsonify(result)

    # ------------------------------------------------------------------
    @app.route("/api/risk-grid", methods=["GET"])
    def risk_grid():
        if not _rate_limiter.allow(f"grid:{_client_key()}", 10, 60.0):
            return _error("Rate limit exceeded (10 requests/minute)", 429)
        try:
            south = float(request.args.get("south"))
            west = float(request.args.get("west"))
            north = float(request.args.get("north"))
            east = float(request.args.get("east"))
        except (TypeError, ValueError):
            return _error("Provide numeric south, west, north, east", 400)
        n = request.args.get("n", "5")
        try:
            n = int(n)
        except ValueError:
            return _error("n must be an integer", 400)

        result = grid_module.compute_risk_grid(south, west, north, east, n)
        if "error" in result:
            return _error(result["error"], 400)
        return jsonify(result)

    # ------------------------------------------------------------------
    @app.route("/api/risk-snapshot", methods=["GET"])
    def risk_snapshot():
        """
        Public risk-intelligence snapshot: the highest-risk areas among the
        configured monitored areas, computed from real cached analyses.

        Returns 503 with ``status: unavailable`` when no valid real snapshot
        can be produced — values are never fabricated.
        """
        if not _rate_limiter.allow(f"snapshot:{_client_key()}", 60, 60.0):
            return _error("Rate limit exceeded (60 requests/minute)", 429)
        try:
            snapshot = snapshot_module.get_snapshot()
        except Exception as exc:
            return _error(f"Risk snapshot unavailable: {exc}", 503)
        if snapshot.get("status") != "ok":
            return jsonify(snapshot), 503
        return jsonify(snapshot)

    # ------------------------------------------------------------------
    @app.route("/api/history", methods=["GET"])
    def history():
        """
        "Lessons from the Past" for a location: recent fire-danger history
        reconstructed from real ERA5 reanalysis + FWI, observed fire events
        (FIRMS, when configured) and what HydraShield would have recommended.
        """
        if not _rate_limiter.allow(f"history:{_client_key()}", 20, 60.0):
            return _error("Rate limit exceeded (20 requests/minute)", 429)

        location = (request.args.get("location") or "").strip()[:200]
        if location:
            from .real_data import geocode_location

            geo = geocode_location(location)
            if "error" in geo:
                return _error(geo["error"], 404)
            lat, lon, name = geo["lat"], geo["lon"], geo["name"]
        else:
            lat, lon, err = _parse_point(request.args)
            if err:
                return _error("Provide ?location=... or ?lat=...&lon=...", 400)
            name = f"{lat:.4f}, {lon:.4f}"

        try:
            days = int(request.args.get("days", "90"))
        except ValueError:
            return _error("days must be an integer", 400)

        try:
            result = history_module.compute_history(round(lat, 4), round(lon, 4), name, days)
        except Exception as exc:
            return _error(f"History computation failed: {exc}", 502)
        if "error" in result:
            return _error(result["error"], 502)
        return jsonify(result)

    # ------------------------------------------------------------------
    @app.route("/api/report", methods=["GET"])
    def report():
        """
        Professional PDF report for a location, rendered from the same real
        cached analysis (and optional real history) that backs /api/analyze
        and /api/history. ?history=1 includes the "Lessons from the Past".
        """
        if not _rate_limiter.allow(f"report:{_client_key()}", 10, 60.0):
            return _error("Rate limit exceeded (10 requests/minute)", 429)

        location = (request.args.get("location") or "").strip()[:200]
        if location:
            from .real_data import geocode_location

            geo = geocode_location(location)
            if "error" in geo:
                return _error(geo["error"], 404)
            lat, lon, name = geo["lat"], geo["lon"], geo["name"]
        else:
            lat, lon, err = _parse_point(request.args)
            if err:
                return _error("Provide ?location=... or ?lat=...&lon=...", 400)
            name = f"{lat:.4f}, {lon:.4f}"

        try:
            result = _cached_analysis(round(lat, 4), round(lon, 4), name)
        except Exception as exc:
            return _error(f"Analysis failed: {exc}", 502)
        if "error" in result:
            return _error(result["error"], 404)

        history = None
        if (request.args.get("history") or "") == "1":
            try:
                h = history_module.compute_history(round(lat, 4), round(lon, 4), name, 90)
                if "error" not in h:
                    history = h
            except Exception:
                history = None  # history is optional; never fabricated

        report_type = (request.args.get("type") or "decision").strip().lower()[:20]
        from . import report as report_module

        if report_type not in report_module.REPORT_TYPES:
            return _error(
                "type must be one of: " + ", ".join(report_module.REPORT_TYPES), 400)

        try:
            pdf = report_module.build_report_pdf(result, history=history,
                                                 report_type=report_type)
        except RuntimeError as exc:
            return _error(f"Report generation unavailable: {exc}", 503)
        except Exception as exc:
            return _error(f"Report generation failed: {exc}", 502)

        from flask import Response

        safe = "".join(c if c.isalnum() else "_" for c in str(name))[:40]
        return Response(
            pdf,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="hydrashield_{report_type}_report_{safe}.pdf"',
                "Cache-Control": "no-store",
            },
        )

    # ------------------------------------------------------------------
    @app.route("/api/analysis-jobs", methods=["POST"])
    def create_analysis_job():
        """
        Start a progressive analysis job. Returns 202 with the job id and
        the initial stage list; poll GET /api/analysis-jobs/<id> for honest
        stage transitions and the final real result.
        """
        if not _rate_limiter.allow(f"jobs:{_client_key()}", 20, 60.0):
            return _error("Rate limit exceeded (20 requests/minute)", 429)
        data = request.get_json(silent=True) or request.args

        location = (data.get("location") or "").strip()[:200]
        if location:
            from .real_data import geocode_location

            geo = geocode_location(location)
            if "error" in geo:
                return _error(geo["error"], 404)
            lat, lon, name = geo["lat"], geo["lon"], geo["name"]
        else:
            lat, lon, err = _parse_point(data)
            if err:
                return _error("Provide location or lat/lon", 400)
            name = (data.get("name") or f"{lat:.4f}, {lon:.4f}")[:200]

        job = jobs_module.start_analysis_job(round(lat, 4), round(lon, 4), name)
        return jsonify(jobs_module.public_job_payload(job)), 202

    # ------------------------------------------------------------------
    @app.route("/api/analysis-jobs/<job_id>", methods=["GET"])
    def analysis_job_status(job_id: str):
        job = jobs_module.get_analysis_job(job_id)
        if job is None:
            return _error("Job not found", 404)
        return jsonify(jobs_module.public_job_payload(job))

    # ------------------------------------------------------------------
    @app.route("/api/watch", methods=["POST"])
    def create_watch():
        if not _rate_limiter.allow(f"watch:{_client_key()}", 10, 3600.0):
            return _error("Rate limit exceeded (10 watches/hour)", 429)
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip()[:200]
        threshold = data.get("threshold_risk", 65.0)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return _error("threshold_risk must be a number", 400)

        location = (data.get("location") or "").strip()[:200]
        if location:
            from .real_data import geocode_location

            geo = geocode_location(location)
            if "error" in geo:
                return _error(geo["error"], 404)
            lat, lon, name = geo["lat"], geo["lon"], geo["name"]
        else:
            lat, lon, err = _parse_point(data)
            if err:
                return _error("Provide location or lat/lon", 400)
            name = f"{lat:.4f}, {lon:.4f}"

        store = WatchStore()
        result = store.add_watch(name, lat, lon, email, threshold)
        if "error" in result:
            return _error(result["error"], 400)
        return jsonify(
            {
                "watch": result,
                "note": "Save the watch id to delete the watch later. Alerts are "
                        "evaluated by the periodic checker; email delivery requires "
                        "SMTP configuration on the server.",
            }
        ), 201

    # ------------------------------------------------------------------
    @app.route("/api/watch/<watch_id>", methods=["DELETE"])
    def delete_watch(watch_id: str):
        store = WatchStore()
        if store.remove_watch(watch_id):
            return jsonify({"deleted": True})
        return _error("Watch not found", 404)

    # ------------------------------------------------------------------
    @app.route("/api/spread", methods=["POST"])
    def calculate_spread():
        """Evaluate the fire-spread model for caller-supplied inputs."""
        data = request.get_json(silent=True) or {}
        try:
            fmc = float(data.get("fuel_moisture", 12.0))
            wind_speed = float(data.get("wind_speed", 20.0))
            slope = float(data.get("slope", 10.0))
        except (TypeError, ValueError):
            return _error("fuel_moisture, wind_speed and slope must be numbers", 400)
        fuel_model = str(data.get("fuel_model", "TL3"))[:8]

        spread_model = FireSpreadModel(fuel_model=fuel_model)
        ros = spread_model.compute_ros(fmc, wind_speed, slope)
        return jsonify(
            {
                "baseline_ros": ros.ros_baseline,
                "reduced_ros": ros.ros_reduced,
                "reduction_percent": ros.reduction_percent,
                "horizontal_component": ros.ros_horizontal,
                "crown_component": ros.ros_crown,
                "fuel_model": fuel_model,
                "provenance": {
                    "kind": "modeled",
                    "source": "HydraShield FireSpreadModel (simplified ROS)",
                    "limitations": "Screening model; inputs supplied by the caller.",
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

    # ------------------------------------------------------------------
    @app.route("/api/allocation", methods=["POST"])
    def calculate_allocation():
        """Allocate water across caller-supplied zones by priority."""
        data = request.get_json(silent=True) or {}
        try:
            priorities = [float(p) for p in data.get("zone_priorities", [1.0, 1.0, 1.0])]
            areas = [float(a) for a in data.get("zone_areas", [1000, 1000, 1000])]
            water_available = float(data.get("water_available", 500.0))
        except (TypeError, ValueError):
            return _error("zone_priorities, zone_areas and water_available must be numeric", 400)
        if len(priorities) != len(areas) or not priorities:
            return _error("zone_priorities and zone_areas must be non-empty and equal length", 400)
        if len(priorities) > 100:
            return _error("Too many zones (max 100)", 400)

        optimiser = WaterOptimiser(water_available_m3=water_available)
        allocations = optimiser.allocate_water(priorities, areas)

        response = {
            "allocations": allocations,
            "water_available": water_available,
            "provenance": {
                "kind": "modeled",
                "source": "HydraShield WaterOptimiser (priority allocation)",
                "limitations": "Zones and priorities supplied by the caller.",
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        # WUER only when the caller supplies both risk values.
        if data.get("risk_baseline") is not None and data.get("risk_hydrashield") is not None:
            try:
                wuer = optimiser.compute_wuer(
                    float(data["risk_baseline"]),
                    float(data["risk_hydrashield"]),
                    sum(allocations),
                )
                response["wuer"] = wuer.to_dict()
            except (TypeError, ValueError):
                pass
        return jsonify(response)

    # ------------------------------------------------------------------
    @app.route("/api/risk", methods=["POST"])
    def risk_compat():
        """Deprecated: use GET /api/analyze. Runs the real analysis."""
        data = request.get_json(silent=True) or {}
        lat, lon, err = _parse_point(data)
        if err:
            return _error("Provide numeric latitude and longitude", 400)
        result = _cached_analysis(round(lat, 4), round(lon, 4), f"{lat:.4f}, {lon:.4f}")
        if "error" in result:
            return _error(result["error"], 502)
        return jsonify(
            {
                "deprecated": True,
                "replacement": "GET /api/analyze?lat=..&lon=..",
                "risk": result["analysis"]["risk"],
                "fire_danger": result.get("fire_danger"),
                "fuel_moisture": result["analysis"]["fuel_moisture_baseline_pct"],
                "provenance": result.get("provenance"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

    @app.errorhandler(404)
    def not_found(_e):
        return _error("Not found", 404)

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return _error("Method not allowed", 405)

    @app.errorhandler(500)
    def internal_error(_e):
        return _error("Internal error", 500)

    return app


class DashboardAPI:
    """Backward-compatible wrapper (used by api_server.py)."""

    def __init__(self):
        self.app = create_app()

    def run(self, host: str = "0.0.0.0", port: int = 8051, debug: bool = False):
        self.app.run(host=host, port=port, debug=debug)

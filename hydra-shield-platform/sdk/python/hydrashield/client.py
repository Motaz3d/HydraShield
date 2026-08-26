"""Talaix API client (stdlib only — no dependencies).

Usage::

    from hydrashield import TalaixClient

    client = TalaixClient()                      # https://talaix.com
    analysis = client.analyze("wildfire", 37.6, -6.5)

Error semantics (docs/API_V2.md §1):

- Non-2xx responses carrying the stable error shape ``{"error", "status"}``
  raise :class:`TalaixError`.
- Honest unavailability (e.g. HTTP 503 with
  ``{"status": "unavailable", "unavailable_reason": …}``) is **data**, not an
  exception — callers render it as-is.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_BASE_URL = "https://talaix.com"
_USER_AGENT = "hydrashield-python-sdk/0.1.0 (+https://talaix.com)"


class TalaixError(Exception):
    """Raised on non-2xx API responses that carry the {"error"} shape."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}")


class TalaixClient:
    """Client for the public Talaix REST API.

    ``api_key`` is sent as the ``X-API-Key`` header (read-only metering key;
    see docs/API_V2.md §7). Public GET endpoints work without it.
    """

    def __init__(self, base_url: str = _DEFAULT_BASE_URL,
                 api_key: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _url(self, path: str, params: dict | None = None) -> str:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _get(self, path: str, params: dict | None = None):
        url = self._url(path, params)
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and "error" in payload:
                raise TalaixError(exc.code, str(payload["error"])) from exc
            # Honest unavailable/key-required states are data, not errors.
            return payload

    # ------------------------------------------------------------------
    # v2 — multi-hazard platform API
    # ------------------------------------------------------------------

    def hazards(self):
        """GET /api/v2/hazards — the registered hazards."""
        return self._get("/api/v2/hazards")

    def hazard(self, hazard_id: str):
        """GET /api/v2/hazards/<id> — one hazard descriptor + map layers."""
        return self._get("/api/v2/hazards/" + urllib.parse.quote(str(hazard_id)))

    def analyze(self, hazard: str, lat: float, lon: float):
        """GET /api/v2/analyze?hazard=…&lat=…&lon=…"""
        return self._get("/api/v2/analyze",
                         {"hazard": hazard, "lat": lat, "lon": lon})

    def events(self, hazard: str, lat: float, lon: float,
               radius_km: float = 50, year: int | None = None):
        """GET /api/v2/events — historical events around a point."""
        params = {"hazard": hazard, "lat": lat, "lon": lon,
                  "radius_km": radius_km}
        if year is not None:
            params["year"] = year
        return self._get("/api/v2/events", params)

    def event(self, event_id: str):
        """GET /api/v2/events/<id> — one stored event with its evidence."""
        return self._get("/api/v2/events/" + urllib.parse.quote(str(event_id)))

    def economy(self, lat: float, lon: float, radius_km: float = 5):
        """GET /api/v2/economy — economic exposure profile."""
        return self._get("/api/v2/economy",
                         {"lat": lat, "lon": lon, "radius_km": radius_km})

    def solutions(self, lat: float, lon: float, hazards: list | None = None):
        """GET /api/v2/solutions — site-fitted sustainable solutions."""
        params = {"lat": lat, "lon": lon}
        if hazards:
            params["hazards"] = ",".join(hazards)
        return self._get("/api/v2/solutions", params)

    def sources(self):
        """GET /api/v2/sources — the data-source audit registry."""
        return self._get("/api/v2/sources")

    # ------------------------------------------------------------------
    # v1 — public wildfire/intelligence endpoints
    # ------------------------------------------------------------------

    def health(self):
        """GET /api/health — service + cache status."""
        return self._get("/api/health")

    def risk_grid(self, south: float, west: float, north: float,
                  east: float, n: int = 6):
        """GET /api/risk-grid — n×n fire-danger grid over a bbox (GeoJSON)."""
        return self._get("/api/risk-grid", {
            "south": south, "west": west, "north": north, "east": east,
            "n": n,
        })

    def risk_snapshot(self):
        """GET /api/risk-snapshot — top-risk monitored areas (or an honest
        unavailable payload as data)."""
        return self._get("/api/risk-snapshot")

    def history(self, lat: float, lon: float, days: int = 90):
        """GET /api/history — real fire-danger history + observed fires."""
        return self._get("/api/history",
                         {"lat": lat, "lon": lon, "days": days})

    def report_url(self, lat: float, lon: float,
                   report_type: str = "decision", history: bool = True) -> str:
        """The URL of the PDF report (GET /api/report) for a location.

        Returns the URL string — the response is a PDF, not JSON, so this
        client does not fetch it.
        """
        params = {"lat": lat, "lon": lon, "type": report_type}
        if history:
            params["history"] = "1"
        return self._url("/api/report", params)

    def population_exposure(self, lat: float, lon: float, radius_km: float = 3):
        """GET /api/population-exposure — WorldPop estimate + hazard overlay."""
        return self._get("/api/population-exposure",
                         {"lat": lat, "lon": lon, "radius_km": radius_km})

    def smoke_scenario(self, lat: float, lon: float, hours: int = 24):
        """GET /api/smoke-scenario — SCENARIO smoke transport (MODELLED)."""
        return self._get("/api/smoke-scenario",
                         {"lat": lat, "lon": lon, "hours": hours})

    # ------------------------------------------------------------------
    # v2 — verification / insurance / mapcheck / briefs / sustainability
    # ------------------------------------------------------------------

    def verify_asset(self, lat: float, lon: float, name: str | None = None):
        """GET /api/v2/verification/asset — physical evidence check."""
        params = {"lat": lat, "lon": lon}
        if name:
            params["name"] = name
        return self._get("/api/v2/verification/asset", params)

    def verification_report_url(self, lat: float, lon: float,
                                name: str | None = None) -> str:
        """The URL of the verification PDF report for a location."""
        params = {"lat": lat, "lon": lon}
        if name:
            params["name"] = name
        return self._url("/api/v2/verification/report", params)

    def insurance_profile(self, lat: float, lon: float,
                          name: str | None = None, radius_km: float = 50):
        """GET /api/v2/insurance/profile — environmental risk profile."""
        params = {"lat": lat, "lon": lon, "radius_km": radius_km}
        if name:
            params["name"] = name
        return self._get("/api/v2/insurance/profile", params)

    def mapcheck(self, lat: float, lon: float, radius_m: int = 300):
        """GET /api/v2/mapcheck — map vs satellite cross-verification."""
        return self._get("/api/v2/mapcheck",
                         {"lat": lat, "lon": lon, "radius_m": radius_m})

    def briefs(self, kind: str | None = None):
        """GET /api/v2/briefs — knowledge briefs list."""
        params = {}
        if kind:
            params["kind"] = kind
        return self._get("/api/v2/briefs", params)

    def brief(self, brief_id: str):
        """GET /api/v2/briefs/<id> — one knowledge brief."""
        return self._get("/api/v2/briefs/" + urllib.parse.quote(str(brief_id)))

    def sustainability_frameworks(self):
        """GET /api/v2/sustainability/frameworks — disclosure frameworks."""
        return self._get("/api/v2/sustainability/frameworks")

    # ------------------------------------------------------------------
    # Binary downloads (PDFs)
    # ------------------------------------------------------------------

    def _download(self, url: str) -> bytes:
        """Download raw bytes from a URL using the same auth headers.

        Raises :class:`TalaixError` when the response is JSON with an
        ``error`` field; returns raw bytes otherwise (e.g. for PDFs).
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/pdf,application/octet-stream,*/*",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and "error" in payload:
                raise TalaixError(exc.code, str(payload["error"])) from exc
            # Non-JSON error response: return the bytes we have.
            return raw.encode("utf-8", errors="replace")

"""TX Engine client — the Talaix TX API (``/api/tx/*``), stdlib only.

The TX API is the engine surface of Talaix (docs/TX_ENGINE.md): one
uniform analysis envelope (TxResult), deterministic analysis/job ids, and
honest ``unavailable`` / ``failed`` states — never fabricated numbers.

Surface:

- :meth:`TxClient.analyze` — synchronous analyses (``GET /api/tx/analyze``),
  for quick/standard depths that return within a request.
- :meth:`TxClient.run` / :meth:`TxClient.job` / :meth:`TxClient.result` —
  the standard Job Object for deep analyses
  (``POST /api/tx/run`` → poll ``/api/tx/jobs/<id>`` → ``/result``).
- :meth:`TxClient.wait` — submit/poll to completion and return the
  TxResult envelope (or raise honestly on failure/timeout).

Error semantics mirror the v1/v2 client: non-2xx responses carrying the
stable ``{"error"}`` shape raise :class:`TalaixError`. A job that is not
finished yet makes :meth:`result` raise ``TalaixError`` with HTTP 409 —
poll :meth:`job` (always 200) or use :meth:`wait` instead.

Usage::

    from hydrashield import TxClient

    tx = TxClient()                          # https://talaix.com
    quick = tx.analyze(49.96, 6.03, hazards=["wildfire"], depth="quick")

    job = tx.run(49.96, 6.03, depth="deep")        # 202 Accepted
    result = tx.wait(job["job_id"])                # polls, then fetches
    print(result["analysis_id"], result["status"])
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .client import TalaixError

_DEFAULT_BASE_URL = "https://talaix.com"
_USER_AGENT = "hydrashield-python-sdk/0.2.0 (+https://talaix.com)"


class TxClient:
    """Client for the Talaix TX Engine API (``/api/tx/*``).

    ``api_key`` is sent as the ``X-API-Key`` header when present (the
    public TX endpoints work without it).
    """

    def __init__(self, base_url: str = _DEFAULT_BASE_URL,
                 api_key: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Transport (GET + POST, same error semantics as client.py)
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _open(self, req):
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
            # Honest states without an error shape are data, not errors.
            return payload

    def _get(self, path: str, params: list | None = None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._open(urllib.request.Request(
            url, headers=self._headers(), method="GET"))

    def _post(self, path: str, body: dict):
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST")
        return self._open(req)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def health(self):
        """GET /api/tx/health — engine + registry availability."""
        return self._get("/api/tx/health")

    def version(self):
        """GET /api/tx/version — engine versions + TX levels."""
        return self._get("/api/tx/version")

    def hazards(self):
        """GET /api/tx/hazards — registered TX hazard descriptors."""
        return self._get("/api/tx/hazards")

    def sources(self):
        """GET /api/tx/sources — official data sources behind TX hazards."""
        return self._get("/api/tx/sources")

    def registry(self):
        """GET /api/tx/registry — TX Registry digest."""
        return self._get("/api/tx/registry")

    # ------------------------------------------------------------------
    # Synchronous analysis (quick/standard depths)
    # ------------------------------------------------------------------

    def analyze(self, lat: float, lon: float, hazards: list | None = None,
                depth: str = "standard", name: str | None = None):
        """GET /api/tx/analyze — one TxResult envelope, in-request."""
        params = [("lat", lat), ("lon", lon), ("depth", depth)]
        for hazard in hazards or []:
            params.append(("hazard", hazard))
        if name:
            params.append(("name", name))
        return self._get("/api/tx/analyze", params)

    # ------------------------------------------------------------------
    # Standard Job Object (deep analyses)
    # ------------------------------------------------------------------

    def run(self, lat: float, lon: float, hazards: list | None = None,
            depth: str = "standard", name: str | None = None):
        """POST /api/tx/run — submit an analysis job.

        Returns the job payload (``job_id``, ``status``, ``poll``,
        ``result_url``). Re-submitting an identical request on the same day
        is idempotent server-side — the existing job is returned.
        """
        body = {"lat": lat, "lon": lon, "depth": depth}
        if hazards:
            body["hazards"] = list(hazards)
        if name:
            body["name"] = name
        return self._post("/api/tx/run", body)

    def job(self, job_id: str):
        """GET /api/tx/jobs/<id> — status + progress (always 200 while known)."""
        return self._get("/api/tx/jobs/" + urllib.parse.quote(str(job_id)))

    def result(self, job_id: str):
        """GET /api/tx/jobs/<id>/result — the TxResult envelope.

        Raises :class:`TalaixError` (HTTP 409) when the job is not finished
        or failed, and (HTTP 404) for an unknown id — poll :meth:`job` or
        use :meth:`wait` to avoid handling 409 yourself.
        """
        return self._get(
            "/api/tx/jobs/" + urllib.parse.quote(str(job_id)) + "/result")

    def wait(self, job, timeout: float = 600.0, interval: float = 2.0,
             on_poll=None):
        """Poll a job (payload or id) to completion; return the TxResult.

        Raises :class:`TalaixError` with the job's real error when it fails,
        or with HTTP 408 on timeout — never a fabricated result. ``on_poll``
        is an optional callback invoked with each status payload (for
        progress display).
        """
        job_id = job["job_id"] if isinstance(job, dict) else str(job)
        deadline = time.monotonic() + timeout
        while True:
            status = self.job(job_id)
            if on_poll is not None:
                on_poll(status)
            state = status.get("status")
            if state == "succeeded":
                return self.result(job_id)
            if state == "failed":
                raise TalaixError(
                    409, f"Job {job_id} failed: {status.get('error')}")
            if time.monotonic() >= deadline:
                raise TalaixError(
                    408, f"Job {job_id} not finished after {timeout:.0f}s "
                         f"(last status: {state})")
            time.sleep(interval)

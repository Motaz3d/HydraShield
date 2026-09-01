"""
TX Engine — the orchestrator that turns platform hazard modules into one
uniform, reproducible TX analysis.

``TXEngine`` never computes a hazard itself: it resolves the requested
hazards through the existing platform registry (or an injected fake for
tests), runs each module's ``analyze()`` unchanged, and wraps the results in
the standard :class:`~tx_core.models.TxResult` envelope with provenance and
engine versions.

Analysis levels (docs/TX_ENGINE.md §"Analysis levels") — the engine tracks
which TX layer each hazard result belongs to, but phase-1 hazards are all
``TX-1 DETERMINISTIC`` (platform hazard modules run deterministic screening
on real data). Higher levels are reserved for future statistical/spatial/ML
steps and are advertised, not faked.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ._version import TAM_VERSION, TX_VERSION
from .adapters import climate as adapters  # noqa: F401 — explicit submodule (adapter pkg does not re-export)
from .adapters import legacy_v1 as legacy_adapters  # noqa: F401
from .models import TxHazardResult, TxLocation, TxResult

#: TX analysis levels (advertised; hazards are progressively upgraded).
TX_LEVELS: Dict[int, str] = {
    0: "RETRIEVAL",
    1: "DETERMINISTIC",
    2: "STATISTICAL",
    3: "SPATIAL",
    4: "PREDICTIVE",
    5: "ML",
    6: "RESEARCH",
    7: "REASONING",
    8: "DECISION_INTELLIGENCE",
}

#: Depth presets — deeper analyses may run more hazards/layers later.
DEPTHS = ("quick", "standard", "deep")

VALID_HAZARD_RE = None  # hazard ids are validated against the registry, not a regex


class TXEngine:
    """Run TX analyses over the platform's registered hazard modules.

    :param registry: optional ``callable(hazard_id) -> module|None`` used to
        resolve hazard modules; defaults to the platform registry. Tests
        inject a fake here to stay network-free.
    :param hazard_ids: optional ``callable() -> list[str]`` for the set of
        available hazard ids (defaults to the platform registry ids).
    :param legacy_analysis: optional ``callable(lat, lon, name) -> dict``
        backing the TX-0/TX-1 facade for the legacy v1 /api/analyze pipeline
        (defaults to the real cached pipeline via ``adapters.legacy_v1``).
        Tests inject a fake here to stay network-free.
    :param version: engine version stamped on every result.
    """

    def __init__(
        self,
        registry: Optional[Callable[[str], Optional[Any]]] = None,
        hazard_ids: Optional[Callable[[], List[str]]] = None,
        legacy_analysis: Optional[Callable[[float, float, str], Dict[str, Any]]] = None,
        version: str = TX_VERSION,
    ) -> None:
        self._registry = registry
        self._hazard_ids = hazard_ids
        self._legacy_analysis = legacy_analysis
        self.version = version

    # -- resolution ---------------------------------------------------------

    def _resolve(self, hazard_id: str) -> Optional[Any]:
        if self._registry is not None:
            return self._registry(hazard_id)
        return adapters.get_hazard_module(hazard_id)

    def available_hazard_ids(self) -> List[str]:
        if self._hazard_ids is not None:
            return sorted(self._hazard_ids())
        return sorted(adapters.hazard_ids())

    def resolve_hazards(self, hazards: Optional[List[str]]) -> List[str]:
        """The concrete hazard ids to run (unknown ids are dropped, honestly)."""
        requested = [h.strip().lower() for h in (hazards or []) if h and h.strip()]
        available = set(self.available_hazard_ids())
        if not requested:
            return sorted(available)
        return [h for h in requested if h in available]

    # -- analysis -----------------------------------------------------------

    def analyze(
        self,
        lat: float,
        lon: float,
        hazards: Optional[List[str]] = None,
        depth: str = "standard",
        name: Optional[str] = None,
        on_hazard: Optional[Callable[[TxHazardResult, int, int], None]] = None,
    ) -> TxResult:
        """Run a TX analysis at (lat, lon).

        The returned envelope always stamps engine versions and a
        deterministic ``analysis_id`` (same inputs + day → same id), so any
        TX analysis can be reproduced and audited.

        :param on_hazard: optional progress callback invoked after each
            hazard completes as ``on_hazard(result, completed, total)`` —
            used by the TX job runner to expose per-hazard progress while a
            deep analysis is running. Callback errors are swallowed:
            progress bookkeeping must never break an analysis.
        """
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Invalid coordinates: lat={lat}, lon={lon}")

        depth = (depth or "standard").lower()
        if depth not in DEPTHS:
            raise ValueError(f"Invalid depth {depth!r}; choose from {DEPTHS}")

        location = TxLocation(lat=lat, lon=lon, name=name)
        chosen = self.resolve_hazards(hazards)

        results: List[TxHazardResult] = []
        for index, hid in enumerate(chosen):
            module = self._resolve(hid)
            if module is None:
                results.append(
                    TxHazardResult(
                        hazard=hid,
                        status="unavailable",
                        summary=f"No registered TX module for hazard '{hid}'.",
                        unavailable_reason=(
                            "The hazard registry does not contain a module wired to "
                            "real data for this id — TX reports it honestly as unknown."
                        ),
                    )
                )
            else:
                try:
                    analysis = module.analyze(lat=lat, lon=lon, name=name)
                    results.append(TxHazardResult.from_hazard_analysis(analysis))
                except Exception as exc:  # noqa: BLE001 — never invent numbers
                    results.append(
                        TxHazardResult(
                            hazard=hid,
                            status="unavailable",
                            summary=f"{hid} analysis failed without producing data.",
                            unavailable_reason=str(exc),
                        )
                    )
            if on_hazard is not None:
                try:
                    on_hazard(results[-1], index + 1, len(chosen))
                except Exception:  # noqa: BLE001 — bookkeeping never breaks analysis
                    pass

        overall = self._overall_status(results)
        return TxResult(
            analysis_id=self.analysis_id(lat=lat, lon=lon, hazards=chosen, depth=depth),
            location=location,
            depth=depth,
            results=results,
            engine_version=self.version,
            tx_version=TX_VERSION,
            tam_version=TAM_VERSION,
            status=overall,
            summary=self._summary(overall, len(results)),
            evidence=[e for r in results for e in r.evidence],
            sources=self.sources(hazard_ids=chosen),
        )

    # -- legacy v1 facade (TX-0/TX-1) ----------------------------------------

    def legacy_analyze(self, lat: float, lon: float,
                       name: Optional[str] = None) -> tuple:
        """TX-0/TX-1 facade for the legacy ``GET /api/analyze`` pipeline.

        Runs the existing real-data pipeline (``TalaixRealAnalyser`` through
        its shared 15-minute cache) *unchanged* — TX never re-implements it —
        and returns ``(payload, tx_meta)``:

        - ``payload``: the EXACT legacy v1 dict. It is never mutated, so the
          existing v1 wire contract stays byte-identical for every client.
        - ``tx_meta``: TX envelope metadata as a *separate* side-channel
          (deterministic ``analysis_id``, engine/tx/tam versions, depth and
          the payload's ``generated_at``) — never injected into the legacy
          payload, but available for audit/telemetry.

        Exceptions from the underlying pipeline propagate untouched so the
        route keeps its exact error semantics (502). Invalid coordinates
        raise ``ValueError`` with the same rules as :meth:`analyze`.
        """
        lat, lon = float(lat), float(lon)
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Invalid coordinates: lat={lat}, lon={lon}")

        name = name or f"{lat:.4f}, {lon:.4f}"
        if self._legacy_analysis is not None:
            payload = self._legacy_analysis(lat, lon, name)
        else:
            payload = legacy_adapters.cached_analysis(lat, lon, name)

        tx_meta = {
            "analysis_id": self.analysis_id(
                lat=lat, lon=lon, hazards=["wildfire"], depth="standard"
            ),
            "hazards": ["wildfire"],
            "depth": "standard",
            "engine_version": self.version,
            "tx_version": TX_VERSION,
            "tam_version": TAM_VERSION,
            "generated_at": payload.get("generated_at"),
        }
        return payload, tx_meta

    # -- introspection ------------------------------------------------------

    def hazards(self) -> List[Dict[str, Any]]:
        """Public hazard descriptors (id/name/tagline/availability/sources)."""
        if self._registry is not None:
            out = []
            for hid in self.available_hazard_ids():
                module = self._resolve(hid)
                if module is None:
                    continue
                try:
                    out.append(module.descriptor())
                except Exception:
                    out.append({"id": hid, "name": hid, "enabled": True})
            return out
        return adapters.hazard_descriptors()

    def sources(self, hazard_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """De-duplicated official data sources behind the given hazards."""
        ids = hazard_ids or self.available_hazard_ids()
        seen: List[Dict[str, str]] = []
        for hid in ids:
            module = self._resolve(hid)
            if module is None:
                continue
            try:
                for src in module.sources():
                    if src.get("name") and not any(
                        s.get("name") == src["name"] for s in seen
                    ):
                        seen.append({"name": src["name"], "url": src.get("url", "")})
            except Exception:
                continue
        return seen

    def version_info(self) -> Dict[str, str]:
        """The exact engine versions behind every TX result."""
        return {
            "tx_version": TX_VERSION,
            "engine_version": self.version,
            "tam_version": TAM_VERSION,
            "levels": TX_LEVELS,
        }

    def analysis_id(self, *, lat: float, lon: float, hazards: List[str],
                    depth: str) -> str:
        """Deterministic, day-scoped analysis id: ``TX-YYYYMMDD-<hex8>``.

        Same inputs on the same UTC day → same id (reproducibility).
        """
        basis = {
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
            "hazards": sorted(hazards),
            "depth": depth,
            "engine_version": self.version,
            "tx_version": TX_VERSION,
        }
        digest = hashlib.sha256(
            repr(sorted(basis.items())).encode("utf-8")
        ).hexdigest()[:8]
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"TX-{day}-{digest}"

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _overall_status(results: List[TxHazardResult]) -> str:
        if not results:
            return "unavailable"
        statuses = {r.status for r in results}
        if statuses <= {"ok"}:
            return "ok"
        if statuses <= {"ok", "partial"}:
            return "partial"
        return "partial" if "ok" in statuses or "partial" in statuses else "unavailable"

    @staticmethod
    def _summary(status: str, n: int) -> str:
        if n == 0:
            return "No hazards could be analysed for this location."
        if status == "ok":
            return f"TX analysis complete: {n} hazard(s) produced real-data results."
        if status == "partial":
            return (
                f"TX analysis partially complete: {n} hazard(s) ran; some "
                "components are unavailable and reported honestly."
            )
        return f"TX analysis unavailable: none of the {n} hazard(s) produced data."


#: Convenience alias — ``TX`` is the public entry point (docs/TX_ENGINE.md).
TX = TXEngine

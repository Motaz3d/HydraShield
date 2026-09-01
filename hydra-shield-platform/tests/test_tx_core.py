"""Tests for TX Core (tx_core) and its additive /api/tx web wiring.

Network-free: the engine is tested with an injected fake hazard registry;
the Flask blueprint is tested with a patched engine factory. The "site not
broken" guarantee is asserted by checking pre-existing routes still work
through the same ``create_app()`` that now also registers the TX blueprint.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import tx_core
from tx_core.engine import TXEngine
from tx_core.models import TxHazardResult, TxLocation, TxResult
from tx_core.registry import TXRegistry
from tx_core.reporting import result_to_geojson, result_to_markdown


# ---------------------------------------------------------------------------
# Fakes (network-free hazard modules)
# ---------------------------------------------------------------------------

@dataclass
class FakeLevel:
    label: str = "Moderate"
    score: Optional[float] = 0.5
    score_max: float = 1.0
    basis: str = "fake basis"
    validated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FakeHazardModule:
    def __init__(self, hazard_id: str = "flood", status: str = "ok",
                 summary: str = "real-data summary", level: Any = None,
                 evidence: Optional[List[Dict[str, Any]]] = None,
                 sources: Optional[List[Dict[str, str]]] = None,
                 unavailable_reason: Optional[str] = None,
                 raise_on_analyze: bool = False) -> None:
        self.id = hazard_id
        self._status = status
        self._summary = summary
        self._level = level or FakeLevel()
        self._evidence = evidence or [{"kind": "observed", "source": "fake-source"}]
        self._sources = sources or [{"name": "Fake Open Data", "url": "https://example.test/"}]
        self._unavailable_reason = unavailable_reason
        self._raise_on_analyze = raise_on_analyze

    def analyze(self, lat: float, lon: float, name: Optional[str] = None,
                **kw: Any) -> SimpleNamespace:
        if self._raise_on_analyze:
            raise RuntimeError("upstream exploded")
        return SimpleNamespace(
            hazard=self.id,
            status=self._status,
            summary=self._summary,
            level=self._level,
            blocks={"component": "value"},
            evidence=self._evidence,
            provenance={"kind": "observed", "source": "fake-source"},
            unavailable_reason=self._unavailable_reason,
        )

    def sources(self) -> List[Dict[str, str]]:
        return list(self._sources)

    def descriptor(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": f"Fake {self.id.title()}",
            "tagline": "fake",
            "enabled": True,
            "analysis": {"available": True, "reason": None},
            "events": {"available": False, "reason": "no events in tests"},
            "temporal_coverage": {},
            "sources": self._sources,
        }


def make_engine(modules: Dict[str, FakeHazardModule],
                ghost: Optional[str] = None) -> TXEngine:
    """An engine whose hazard ids include real fakes + an optional 'ghost'."""

    def registry(hazard_id: str) -> Any:
        return None if hazard_id == ghost else modules.get(hazard_id)

    def hazard_ids() -> List[str]:
        ids = list(modules)
        if ghost:
            ids.append(ghost)
        return ids

    return TXEngine(registry=registry, hazard_ids=hazard_ids)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_models_roundtrip():
    loc = TxLocation(lat=41.5, lon=-8.6, name="Peneda")
    hr = TxHazardResult(hazard="flood", status="unavailable",
                        unavailable_reason="no river cell")
    result = TxResult(
        analysis_id="TX-20260901-abcdef12",
        location=loc,
        depth="standard",
        results=[hr],
        engine_version="0.1.0",
        tx_version="0.1.0",
        tam_version="1.0.0",
    )
    d = result.to_dict()
    assert d["analysis_id"] == "TX-20260901-abcdef12"
    assert d["location"] == {"lat": 41.5, "lon": -8.6, "name": "Peneda"}
    assert d["status_counts"] == {"unavailable": 1}
    assert d["results"][0]["unavailable_reason"] == "no river cell"
    for key in ("engine_version", "tx_version", "tam_version", "generated_at"):
        assert key in d


def test_models_adapt_hazard_analysis():
    analysis = FakeHazardModule(hazard_id="heat", status="partial").analyze(40, 3)
    hr = TxHazardResult.from_hazard_analysis(analysis)
    assert hr.hazard == "heat"
    assert hr.status == "partial"
    assert hr.blocks == {"component": "value"}
    assert hr.level.label == "Moderate"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def test_engine_ok_result():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    result = engine.analyze(lat=41.5, lon=-8.6)
    assert result.status == "ok"
    assert len(result.results) == 1
    assert result.results[0].status == "ok"
    assert result.analysis_id.startswith("TX-")
    assert result.tx_version == tx_core.TX_VERSION
    assert result.tam_version == tx_core.TAM_VERSION
    assert result.sources == [{"name": "Fake Open Data", "url": "https://example.test/"}]


def test_engine_unknown_hazard_is_honest():
    engine = make_engine({"flood": FakeHazardModule("flood")}, ghost="ghost")
    result = engine.analyze(lat=0.0, lon=0.0, hazards=["ghost"])
    assert result.status == "unavailable"
    assert result.results[0].status == "unavailable"
    assert result.results[0].unavailable_reason


def test_engine_exception_reported_not_fabricated():
    engine = make_engine({"flood": FakeHazardModule("flood", raise_on_analyze=True)})
    result = engine.analyze(lat=10, lon=20)
    assert result.status == "unavailable"
    assert result.results[0].status == "unavailable"
    assert "upstream exploded" in result.results[0].unavailable_reason


def test_engine_unknown_requested_hazard_dropped():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    result = engine.analyze(lat=1, lon=2, hazards=["flood", "nope"])
    assert [r.hazard for r in result.results] == ["flood"]


def test_engine_validation():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    with pytest.raises(ValueError):
        engine.analyze(lat=95, lon=0)
    with pytest.raises(ValueError):
        engine.analyze(lat=0, lon=-181)
    with pytest.raises(ValueError):
        engine.analyze(lat=0, lon=0, depth="ultra")


def test_analysis_id_deterministic():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    a = engine.analysis_id(lat=40.123456, lon=-8.1, hazards=["flood"], depth="standard")
    b = engine.analysis_id(lat=40.123456, lon=-8.1, hazards=["flood"], depth="standard")
    c = engine.analysis_id(lat=40.2, lon=-8.1, hazards=["flood"], depth="standard")
    assert a == b
    assert a != c


def test_sources_deduplicated_across_hazards():
    shared = {"name": "Shared Source", "url": "https://example.test/"}
    engine = make_engine({
        "flood": FakeHazardModule("flood", sources=[shared]),
        "heat": FakeHazardModule("heat", sources=[shared, {"name": "Other", "url": "u"}]),
    })
    sources = engine.sources()
    names = [s["name"] for s in sources]
    assert names.count("Shared Source") == 1
    assert "Other" in names


def test_hazards_descriptors():
    engine = make_engine({"flood": FakeHazardModule("flood")}, ghost="ghost")
    descriptors = engine.hazards()
    ids = [d["id"] for d in descriptors]
    assert "flood" in ids
    assert "ghost" not in ids  # unresolved modules are honestly absent


def test_version_info():
    engine = TXEngine()
    info = engine.version_info()
    assert info["tx_version"] == tx_core.TX_VERSION
    assert info["tam_version"] == tx_core.TAM_VERSION
    assert info["levels"][1] == "DETERMINISTIC"
    assert info["levels"][8] == "DECISION_INTELLIGENCE"


def test_engine_default_adapter_path_resolves_platform_registry():
    """Regression: the non-injected engine must resolve hazards through
    tx_core.adapters.climate (the adapter package itself only re-exports
    submodules — importing it alone used to raise AttributeError)."""
    engine = TXEngine()  # no injection: default adapter path
    ids = engine.available_hazard_ids()
    assert ids, "default path must resolve the real platform registry"
    assert "wildfire" in ids
    resolved = engine.resolve_hazards(["wildfire", "does-not-exist"])
    assert resolved == ["wildfire"]


# ---------------------------------------------------------------------------
# TX-0/TX-1 legacy v1 facade (GET /api/analyze contract)
# ---------------------------------------------------------------------------

LEGACY_PAYLOAD = {
    "location": {"name": "Fake Place", "latitude": 1.0, "longitude": 2.0},
    "generated_at": "2026-09-01T00:00:00Z",
    "fire_danger": {"available": True, "fwi": 22.5, "class": "High"},
    "analysis": {"risk": {"baseline": 42.0, "class": "Moderate"}},
    "provenance": {"weather": {"kind": "modeled"}},
}


def test_legacy_facade_payload_byte_identical_meta_side_channel():
    engine = TXEngine(legacy_analysis=lambda lat, lon, name: dict(LEGACY_PAYLOAD))
    payload, meta = engine.legacy_analyze(41.5, -8.6, "Fake Place")
    assert payload == LEGACY_PAYLOAD  # contract untouched: no keys added/removed
    assert meta["analysis_id"].startswith("TX-")
    assert meta["hazards"] == ["wildfire"]
    assert meta["depth"] == "standard"
    assert meta["engine_version"] == tx_core.TX_VERSION
    assert meta["tx_version"] == tx_core.TX_VERSION
    assert meta["tam_version"] == tx_core.TAM_VERSION
    assert meta["generated_at"] == LEGACY_PAYLOAD["generated_at"]
    # meta is a side-channel: it must never appear inside the legacy payload
    assert "analysis_id" not in payload
    assert "tx_version" not in payload


def test_legacy_facade_deterministic_analysis_id():
    engine = TXEngine(legacy_analysis=lambda *a: dict(LEGACY_PAYLOAD))
    _, m1 = engine.legacy_analyze(41.5, -8.6)
    _, m2 = engine.legacy_analyze(41.5, -8.6)
    _, m3 = engine.legacy_analyze(41.51, -8.6)
    assert m1["analysis_id"] == m2["analysis_id"]
    assert m1["analysis_id"] != m3["analysis_id"]


def test_legacy_facade_validates_coords():
    engine = TXEngine(legacy_analysis=lambda *a: {})
    with pytest.raises(ValueError):
        engine.legacy_analyze(95, 0)
    with pytest.raises(ValueError):
        engine.legacy_analyze(0, -181)


def test_legacy_facade_default_name():
    engine = TXEngine(legacy_analysis=lambda lat, lon, name: {"name": name})
    payload, _ = engine.legacy_analyze(41.5, -8.6)
    assert payload["name"] == "41.5000, -8.6000"


def test_legacy_facade_default_path_resolves_real_pipeline():
    """Regression guard for the non-injected facade path: the adapter must
    resolve the real legacy analyser (lazy import; no network touched)."""
    from tx_core.adapters import legacy_v1

    cls = legacy_v1.analyser_class()
    assert cls is not None
    assert cls.__name__ == "TalaixRealAnalyser"
    assert callable(legacy_v1.cached_analysis)


# ---------------------------------------------------------------------------
# Registry facade
# ---------------------------------------------------------------------------

def test_registry_reads_platform_configs():
    registry = TXRegistry()
    assert any(m.get("id") == "fwi_system_v1" for m in registry.models())
    assert registry.model("fwi_system_v1")["version"] == "1.0.0"
    assert registry.sources()
    assert any(s.get("status") == "integrated" for s in registry.sources())
    assert registry.datasets()
    assert registry.integrated_sources()
    summary = registry.summary()
    assert summary["datasets_integrated"] > 0
    assert summary["sources_integrated"] > 0
    assert "models" in summary


def test_registry_missing_config_is_honest(tmp_path):
    registry = TXRegistry(config_dir=str(tmp_path))
    assert registry.models() == []
    assert registry.sources() == []
    assert registry.datasets() == []
    assert registry.summary()["sources_integrated"] == 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def test_reporting_geojson():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    result = engine.analyze(lat=40.5, lon=-8.1)
    gj = result_to_geojson(result)
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    feature = gj["features"][0]
    assert feature["geometry"]["coordinates"] == [-8.1, 40.5]
    props = feature["properties"]
    assert props["hazard"] == "flood"
    assert props["analysis_id"] == result.analysis_id
    assert props["level_label"] == "Moderate"
    assert props["level_validated"] is False


def test_reporting_markdown():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    result = engine.analyze(lat=40.5, lon=-8.1)
    md = result_to_markdown(result)
    assert result.analysis_id in md
    assert "## Hazards" in md
    assert "Fake Open Data" in md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_version(capsys):
    from tx_core.cli import main

    assert main(["version"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tx_version"] == tx_core.TX_VERSION


def test_cli_analyze_rejects_bad_coords(capsys):
    from tx_core.cli import main

    assert main(["analyze", "--lat", "999", "--lon", "0"]) == 2
    assert "error" in capsys.readouterr().err


def test_cli_analyze_json(monkeypatch, capsys):
    from tx_core import cli

    fake = make_engine({"flood": FakeHazardModule("flood")})
    monkeypatch.setattr(cli, "TXEngine", lambda: fake)
    assert cli.main(["analyze", "--lat", "40", "--lon", "-8",
                     "--hazard", "flood", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["analysis_id"].startswith("TX-")
    assert out["results"][0]["hazard"] == "flood"


def test_cli_registry(capsys):
    from tx_core.cli import main

    assert main(["registry"]) == 0
    out = capsys.readouterr().out
    assert "TX Registry summary" in out
    assert "sources integrated" in out


def test_cli_hazards_json(monkeypatch, capsys):
    from tx_core import cli

    fake = make_engine({"flood": FakeHazardModule("flood")})
    monkeypatch.setattr(cli, "TXEngine", lambda: fake)
    assert cli.main(["hazards", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["id"] == "flood"


# ---------------------------------------------------------------------------
# Web wiring — the site keeps running (additive blueprint only)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from src.dashboard.api import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_tx_health(client):
    resp = client.get("/api/tx/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["tx_version"] == tx_core.TX_VERSION
    assert "hazards" in body["registry"]


def test_tx_version(client):
    resp = client.get("/api/tx/version")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tx_version"] == tx_core.TX_VERSION
    assert body["levels"]["1"] == "DETERMINISTIC"


def test_tx_analyze_requires_coords(client):
    resp = client.get("/api/tx/analyze")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_tx_analyze_rejects_bad_depth(client):
    resp = client.get("/api/tx/analyze?lat=40&lon=-8&depth=ultra")
    assert resp.status_code == 400


def test_tx_analyze_ok(monkeypatch, client):
    from src.dashboard import tx_api

    fake = make_engine({"flood": FakeHazardModule("flood")})
    monkeypatch.setattr(tx_api, "_engine", lambda: fake)
    resp = client.get("/api/tx/analyze?lat=40&lon=-8&hazard=flood")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["analysis_id"].startswith("TX-")
    assert body["results"][0]["hazard"] == "flood"
    assert body["status"] == "ok"


def test_tx_analyze_unknown_hazard_honest(monkeypatch, client):
    from src.dashboard import tx_api

    fake = make_engine({"flood": FakeHazardModule("flood")}, ghost="ghost")
    monkeypatch.setattr(tx_api, "_engine", lambda: fake)
    resp = client.get("/api/tx/analyze?lat=40&lon=-8&hazard=ghost")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "unavailable"


def test_existing_routes_untouched(client):
    """The site must keep working: pre-existing routes still serve 200."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "running"

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] in ("ok", "degraded")

"""Tests for TX product analyses (TX-2+) — engine, adapters, API, CLI.

Network-free: product engines are injected fakes; the default adapter path
is verified by resolution only (lazy imports, no analyze() calls). The core
contract under test: products run only when explicitly requested, land in
the same results[] envelope stamped tx_level=2, fail honestly, and never
change a hazard-only analysis_id.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import tx_core
from tx_core.adapters import products as product_adapters
from tx_core.engine import TXEngine

from tests.test_tx_core import FakeHazardModule, make_engine


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeProductEngine:
    """A network-free product engine with the hazard-module surface."""

    tx_level = 2

    def __init__(self, product_id: str = "insurance", status: str = "ok",
                 raise_on_analyze: bool = False) -> None:
        self.id = product_id
        self._status = status
        self._raise = raise_on_analyze

    def analyze(self, lat: float, lon: float, name: Optional[str] = None,
                **kw: Any) -> SimpleNamespace:
        if self._raise:
            raise RuntimeError("product exploded")
        return SimpleNamespace(
            hazard=self.id,
            status=self._status,
            summary=f"{self.id} product summary",
            level=None,
            blocks={"profile_id": "prof-1", "perils": []},
            evidence=[{"kind": "modeled", "source": "fake-product"}],
            provenance={"kind": "product_engine", "engine": self.id},
            unavailable_reason=None,
        )

    def sources(self) -> List[Dict[str, str]]:
        return []

    def descriptor(self) -> Dict[str, Any]:
        return {"id": self.id, "name": f"Fake {self.id.title()}",
                "kind": "product", "tx_level": 2, "engine_version": "9.9.9"}


def make_product_engine(
    hazards: Optional[Dict[str, FakeHazardModule]] = None,
    products: Optional[Dict[str, FakeProductEngine]] = None,
    ghost_product: Optional[str] = None,
) -> TXEngine:
    base = make_engine(hazards or {"flood": FakeHazardModule("flood")})
    mods = products or {}

    def product_registry(product_id: str) -> Any:
        return None if product_id == ghost_product else mods.get(product_id)

    def product_ids() -> List[str]:
        ids = list(mods)
        if ghost_product:
            ids.append(ghost_product)
        return ids

    return TXEngine(
        registry=base._registry, hazard_ids=base._hazard_ids,
        products=product_registry, product_ids=product_ids,
    )


# ---------------------------------------------------------------------------
# Engine — request axis + envelope + honesty
# ---------------------------------------------------------------------------

def test_products_never_run_by_default():
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    result = engine.analyze(lat=1, lon=2, hazards=["flood"])
    assert [r.hazard for r in result.results] == ["flood"]


def test_products_run_only_when_requested():
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    result = engine.analyze(lat=1, lon=2, hazards=["flood"],
                            analyses=["insurance"])
    assert [r.hazard for r in result.results] == ["flood", "insurance"]
    product = result.results[1]
    assert product.status == "ok"
    assert product.tx_level == 2
    assert product.blocks["profile_id"] == "prof-1"
    assert result.results[0].tx_level == 1  # hazards are TX-1
    d = result.to_dict()
    assert d["results"][1]["tx_level"] == 2
    assert d["results"][0]["tx_level"] == 1


def test_unknown_analysis_id_dropped_honestly():
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    result = engine.analyze(lat=1, lon=2, hazards=["flood"],
                            analyses=["insurance", "nope"])
    assert [r.hazard for r in result.results] == ["flood", "insurance"]


def test_unresolvable_product_is_honest_unavailable():
    engine = make_product_engine(products={}, ghost_product="ghost")
    # hazards: unknown ids are dropped, so only the ghost product runs.
    result = engine.analyze(lat=1, lon=2, hazards=["does-not-exist"],
                            analyses=["ghost"])
    assert result.status == "unavailable"
    assert result.results[0].status == "unavailable"
    assert result.results[0].tx_level == 2
    assert result.results[0].unavailable_reason


def test_product_exception_reported_not_fabricated():
    engine = make_product_engine(
        products={"insurance": FakeProductEngine(raise_on_analyze=True)})
    result = engine.analyze(lat=1, lon=2, hazards=["does-not-exist"],
                            analyses=["insurance"])
    assert result.status == "unavailable"
    assert "product exploded" in result.results[0].unavailable_reason


def test_analysis_id_stable_for_hazard_only_calls():
    """Adding the analyses axis must not change existing hazard-only ids."""
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    a = engine.analysis_id(lat=40.0, lon=-8.0, hazards=["flood"],
                           depth="standard")
    b = engine.analysis_id(lat=40.0, lon=-8.0, hazards=["flood"],
                           depth="standard", analyses=None)
    c = engine.analysis_id(lat=40.0, lon=-8.0, hazards=["flood"],
                           depth="standard", analyses=[])
    d = engine.analysis_id(lat=40.0, lon=-8.0, hazards=["flood"],
                           depth="standard", analyses=["insurance"])
    assert a == b == c
    assert a != d


def test_full_analyze_id_changes_with_products():
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    without = engine.analyze(lat=1, lon=2, hazards=["flood"])
    with_ = engine.analyze(lat=1, lon=2, hazards=["flood"],
                           analyses=["insurance"])
    assert without.analysis_id != with_.analysis_id


def test_progress_total_covers_hazards_and_products():
    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    seen: List[Any] = []
    engine.analyze(lat=1, lon=2, hazards=["flood"], analyses=["insurance"],
                   on_hazard=lambda r, done, total: seen.append((done, total)))
    assert seen == [(1, 2), (2, 2)]


def test_products_descriptors_and_ghost_absent():
    engine = make_product_engine(
        products={"insurance": FakeProductEngine()}, ghost_product="ghost")
    descriptors = engine.products()
    ids = [d["id"] for d in descriptors]
    assert "insurance" in ids
    assert "ghost" not in ids  # unresolvable products are honestly absent
    assert descriptors[0]["kind"] == "product"
    assert descriptors[0]["tx_level"] == 2


# ---------------------------------------------------------------------------
# Default adapter path (resolution only — no network, no analyze calls)
# ---------------------------------------------------------------------------

def test_default_product_registry_resolves_real_engines():
    engine = TXEngine()  # no injection: default adapter path
    ids = engine.available_product_ids()
    assert ids == ["insurance", "licensing", "sustainability", "verification"]
    assert engine.resolve_products(["insurance", "does-not-exist"]) == ["insurance"]
    for pid in ids:
        module = product_adapters.get_product_module(pid)
        assert module is not None
        assert module.tx_level == 2
        descriptor = module.descriptor()
        assert descriptor["id"] == pid
        assert descriptor["kind"] == "product"
        assert descriptor["engine_version"]


def test_adapter_unknown_product_is_none():
    assert product_adapters.get_product_module("does-not-exist") is None


# ---------------------------------------------------------------------------
# Web wiring
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from src.dashboard.api import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class RecordingEngine:
    """An engine fake that records the analyze() call it received."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def analyze(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return make_engine({"flood": FakeHazardModule("flood")}).analyze(
            lat=kw["lat"], lon=kw["lon"], hazards=kw.get("hazards"),
            depth=kw.get("depth", "standard"), name=kw.get("name"),
            analyses=None,
        )

    def products(self) -> List[Dict[str, Any]]:
        return [{"id": "insurance", "name": "Fake Insurance",
                 "kind": "product", "tx_level": 2, "engine_version": "9.9.9"}]


def test_tx_products_endpoint(monkeypatch, client):
    from src.dashboard import tx_api

    recorder = RecordingEngine()
    monkeypatch.setattr(tx_api, "_engine", lambda: recorder)
    resp = client.get("/api/tx/products")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["products"][0]["id"] == "insurance"
    assert body["products"][0]["tx_level"] == 2


def test_tx_analyze_passes_analyses_param(monkeypatch, client):
    from src.dashboard import tx_api

    recorder = RecordingEngine()
    monkeypatch.setattr(tx_api, "_engine", lambda: recorder)
    resp = client.get("/api/tx/analyze?lat=40&lon=-8&hazard=flood"
                      "&analysis=insurance&analysis=verification")
    assert resp.status_code == 200
    assert recorder.calls[0]["analyses"] == ["insurance", "verification"]
    assert recorder.calls[0]["hazards"] == ["flood"]


def test_tx_analyze_analyses_comma_string(monkeypatch, client):
    from src.dashboard import tx_api

    recorder = RecordingEngine()
    monkeypatch.setattr(tx_api, "_engine", lambda: recorder)
    resp = client.get("/api/tx/analyze?lat=40&lon=-8&analyses=insurance,verification")
    assert resp.status_code == 200
    assert recorder.calls[0]["analyses"] == ["insurance", "verification"]


def test_tx_run_carries_analyses(monkeypatch, client):
    from src.dashboard import tx_api
    from tx_core.jobs import TxJobRunner, TxJobStore

    recorder = RecordingEngine()
    runner = TxJobRunner(store=TxJobStore(), engine_factory=lambda: recorder,
                         synchronous=True)
    monkeypatch.setattr(tx_api, "_JOB_RUNNER", runner)
    resp = client.post("/api/tx/run", json={
        "lat": 40.0, "lon": -8.0, "hazards": ["flood"],
        "analyses": ["insurance"], "depth": "deep",
    })
    assert resp.status_code == 202
    job = runner.get(resp.get_json()["job_id"])
    assert job.request["analyses"] == ["insurance"]
    assert recorder.calls[0]["analyses"] == ["insurance"]


def test_tx_run_analyses_comma_string_and_bad_type(monkeypatch, client):
    from src.dashboard import tx_api
    from tx_core.jobs import TxJobRunner, TxJobStore

    runner = TxJobRunner(store=TxJobStore(),
                         engine_factory=lambda: RecordingEngine(),
                         synchronous=True)
    monkeypatch.setattr(tx_api, "_JOB_RUNNER", runner)
    ok = client.post("/api/tx/run", json={"lat": 1, "lon": 2,
                                          "analyses": "insurance, verification"})
    assert ok.status_code == 202
    job = runner.get(ok.get_json()["job_id"])
    assert job.request["analyses"] == ["insurance", "verification"]
    bad = client.post("/api/tx/run", json={"lat": 1, "lon": 2, "analyses": 42})
    assert bad.status_code == 400


def test_job_id_stable_with_and_without_analyses():
    from tx_core.jobs import make_job_id

    a = make_job_id(lat=1, lon=2, hazards=["flood"], depth="deep")
    b = make_job_id(lat=1, lon=2, hazards=["flood"], depth="deep", analyses=None)
    c = make_job_id(lat=1, lon=2, hazards=["flood"], depth="deep",
                    analyses=["insurance"])
    assert a == b  # hazard-only job ids stay byte-stable
    assert a != c


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_analyze_analysis_flag(monkeypatch, capsys):
    import json as _json

    from tx_core import cli

    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    monkeypatch.setattr(cli, "TXEngine", lambda: engine)
    assert cli.main(["analyze", "--lat", "1", "--lon", "2",
                     "--hazard", "flood", "--analysis", "insurance",
                     "--json"]) == 0
    out = _json.loads(capsys.readouterr().out)
    assert [r["hazard"] for r in out["results"]] == ["flood", "insurance"]
    assert out["results"][1]["tx_level"] == 2


def test_cli_products(monkeypatch, capsys):
    import json as _json

    from tx_core import cli

    engine = make_product_engine(products={"insurance": FakeProductEngine()})
    monkeypatch.setattr(cli, "TXEngine", lambda: engine)
    assert cli.main(["products", "--json"]) == 0
    out = _json.loads(capsys.readouterr().out)
    assert out[0]["id"] == "insurance"
    assert out[0]["kind"] == "product"


def test_cli_products_default_path_resolves(capsys):
    from tx_core import cli

    assert cli.main(["products"]) == 0
    out = capsys.readouterr().out
    assert "insurance" in out
    assert "verification" in out
    assert "sustainability" in out

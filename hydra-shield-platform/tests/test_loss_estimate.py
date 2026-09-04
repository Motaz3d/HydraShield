"""
Unit tests for src/climate/loss_estimate.py — the Talaix loss screening
ESTIMATE (ESTIMATED layer, docs/ECONOMIC_INTELLIGENCE.md §9).

Offline: benchmarks are loaded from the real config; the estimate function
is pure (building counts are supplied, never fetched). The strict
ESTIMATED/DOCUMENTED separation is pinned in the report-section tests.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_loss_est_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from flask import Flask  # noqa: E402

from src.climate import loss_estimate as le  # noqa: E402
from src.climate.api_losses import losses_bp  # noqa: E402


def test_benchmarks_config_validates():
    cfg = le.load_benchmarks()
    assert le.validate_benchmarks(cfg) == []
    assert cfg["countries"]
    blob = json.dumps(cfg)
    assert "€" not in blob and "$" not in blob
    # Every benchmark band carries its declared basis.
    for c in cfg["countries"]:
        assert c["replacement_cost_per_m2"]["basis"]


def test_match_country_smallest_bbox_wins():
    cfg = le.load_benchmarks()
    # Clervaux sits inside both Luxembourg's and Germany's bboxes.
    assert le.match_country(50.0548, 6.0276, cfg)["code"] == "LU"
    assert le.match_country(52.52, 13.405, cfg)["code"] == "DE"
    assert le.match_country(48.8566, 2.3522, cfg)["code"] == "FR"
    assert le.match_country(35.6762, 139.6503, cfg) is None  # Tokyo


def test_estimate_exposed_value_math_is_exact():
    cost = {"low": 1000, "central": 1500, "high": 2500, "basis": "test"}
    area = {"low": 80, "central": 120, "high": 200, "basis": "test"}
    out = le.estimate_exposed_value(100, cost, area)
    assert out["low"] == 100 * 80 * 1000
    assert out["central"] == 100 * 120 * 1500
    assert out["high"] == 100 * 200 * 2500
    assert out["low"] < out["central"] < out["high"]
    assert "EUR" in out["unit"]


def test_loss_screening_estimate_contract_and_separation():
    est = le.loss_screening_estimate(
        50.0548, 6.0276, 775, buildings_source="test buildings", radius_m=2000)
    assert est["status"] == "ok"
    assert est["claim_status"] == "ESTIMATED"
    ev = est["estimate"]["exposed_value_eur"]
    assert ev["low"] == 775 * 80 * 1500       # LU low band
    assert ev["central"] == 775 * 120 * 2200  # LU central band
    assert ev["high"] == 775 * 200 * 3200     # LU high band
    # The expected-loss slot is honestly absent — no damage model pretended.
    assert est["expected_loss"]["status"] == "not_available"
    assert "damage-ratio" in est["expected_loss"]["statement"]
    # Inputs, method and limitations are all printed.
    assert est["inputs"]["buildings_count"]["value"] == 775
    assert est["inputs"]["country_benchmark"]["code"] == "LU"
    assert est["inputs"]["benchmarks"]["config"] == "config/loss_estimate_benchmarks.json"
    assert "mapped_buildings" in est["method"]
    assert est["limitations"]
    assert "never merged with DOCUMENTED" in est["separation_note"]
    blob = json.dumps(est)
    assert "€" not in blob and "$" not in blob


def test_loss_screening_estimate_fallback_country():
    # Madrid matches Spain's benchmark; Tokyo falls back to declared defaults.
    est = le.loss_screening_estimate(40.4168, -3.7038, 50)
    assert est["inputs"]["country_benchmark"]["code"] == "ES"
    est_tokyo = le.loss_screening_estimate(35.6762, 139.6503, 50)
    assert est_tokyo["status"] == "ok"
    assert "fallback" in est_tokyo["inputs"]["country_benchmark"]["name"]


def test_loss_screening_estimate_unavailable_without_buildings():
    for count in (None, 0, -5):
        out = le.loss_screening_estimate(50.0, 6.0, count)
        assert out["status"] == "unavailable"
        assert "building count" in out["reason"]
        assert out["claim_status"] == "ESTIMATED"
    assert le.loss_screening_estimate(95.0, 6.0, 10)["status"] == "unavailable"


# ---------------------------------------------------------------------------
# /api/v2/losses/estimate endpoint
# ---------------------------------------------------------------------------

_SYNTH_EXPOSURE = {
    "location": {"lat": 0.0, "lon": 0.0},
    "radius_km": 5.0,
    "exposure": {
        "buildings": {"status": "mapped", "count": 214,
                      "source": "OpenStreetMap via ohsome API (synthetic)",
                      "completeness_caveat": "varies"},
    },
}


@pytest.fixture()
def client():
    app = Flask("test_loss_estimate")
    app.config["TESTING"] = True
    app.register_blueprint(losses_bp)
    with app.test_client() as c:
        yield c


def test_estimate_endpoint_with_mocked_exposure(client, monkeypatch):
    # The route imports build_economic_exposure lazily from the module, so
    # patching the module attribute is sufficient.
    import src.climate.exposure_econ as ex_mod

    monkeypatch.setattr(ex_mod, "build_economic_exposure",
                        lambda lat, lon, radius_km=5.0: dict(_SYNTH_EXPOSURE))
    resp = client.get("/api/v2/losses/estimate?lat=50.0548&lon=6.0276")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["claim_status"] == "ESTIMATED"
    assert data["inputs"]["buildings_count"]["value"] == 214
    assert data["estimate"]["exposed_value_eur"]["central"] == 214 * 120 * 2200
    assert data["expected_loss"]["status"] == "not_available"
    assert data["location"] == {"lat": 50.0548, "lon": 6.0276}


def test_estimate_endpoint_requires_coords(client):
    assert client.get("/api/v2/losses/estimate").status_code == 400
    assert client.get(
        "/api/v2/losses/estimate?lat=95&lon=0").status_code == 400

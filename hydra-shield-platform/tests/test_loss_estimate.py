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
    # patching the module attribute is sufficient. Cadastre/Eurostat layers
    # are patched out to keep the suite offline with declared values.
    import src.climate.exposure_econ as ex_mod
    import src.climate.cadastre as cad_mod
    import src.climate.eurostat_cci as cci_mod

    monkeypatch.setattr(ex_mod, "build_economic_exposure",
                        lambda lat, lon, radius_km=5.0: dict(_SYNTH_EXPOSURE))
    monkeypatch.setattr(cad_mod, "real_floor_area_m2", lambda *a, **k: None)
    monkeypatch.setattr(cci_mod, "calibration",
                        lambda geo, basis_year=2023: {"status": "unavailable",
                                                      "reason": "offline test"})
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


# ---------------------------------------------------------------------------
# enriched_estimate — cadastre + Eurostat calibration + expected loss
# ---------------------------------------------------------------------------

def test_enriched_estimate_with_real_area_and_calibration(monkeypatch):
    import src.climate.cadastre as cad_mod
    import src.climate.eurostat_cci as cci_mod

    monkeypatch.setattr(cad_mod, "real_floor_area_m2",
                        lambda lat, lon, r=None: {
                            "mean_area_m2": 240.0, "building_count": 7,
                            "source": "BAG test", "method": "m",
                            "licence_note": "l"})
    monkeypatch.setattr(cci_mod, "calibration",
                        lambda geo, basis_year=2023: {
                            "status": "ok", "factor": 1.25, "basis_year": 2023,
                            "basis_value": 100.0, "latest_year": 2026,
                            "latest_value": 125.0, "flags": {},
                            "source": "Eurostat test", "url": "https://x",
                            "method": "m"})
    est = le.enriched_estimate(52.37, 4.90, 100, radius_m=1000)
    assert est["status"] == "ok"
    assert est["inputs"]["area_basis"]["status"] == "real_cadastral"
    ev = est["estimate"]["exposed_value_eur"]
    # Declared NL cost band 1200/1700/2500; declared area shape (80/120/200)
    # scaled to the real mean 240 -> band 160/240/400; factor 1.25 applied.
    assert ev["low"] == round(100 * 160.0 * 1200 * 1.25)
    assert ev["central"] == round(100 * 240.0 * 1700 * 1.25)
    assert ev["high"] == round(100 * 400.0 * 2500 * 1.25)
    assert est["inputs"]["price_calibration"]["factor"] == 1.25
    assert "price-calibrated" in ev["unit"]


def test_enriched_estimate_declared_fallbacks(monkeypatch):
    import src.climate.cadastre as cad_mod
    import src.climate.eurostat_cci as cci_mod

    monkeypatch.setattr(cad_mod, "real_floor_area_m2", lambda *a, **k: None)
    monkeypatch.setattr(cci_mod, "calibration",
                        lambda geo, basis_year=2023: {"status": "unavailable",
                                                      "reason": "offline"})
    est = le.enriched_estimate(50.0548, 6.0276, 775, radius_m=2000)
    assert est["status"] == "ok"
    assert est["inputs"]["area_basis"]["status"] == "declared_assumption"
    assert est["inputs"]["price_calibration"]["status"] == "unavailable"
    ev = est["estimate"]["exposed_value_eur"]
    assert ev["central"] == 775 * 120 * 2200  # pure declared values stand
    assert "price-calibrated" not in ev["unit"]


def test_expected_loss_from_depth_math():
    curve = [[0.0, 0.0], [1.0, 0.4], [2.0, 0.6]]
    ev = {"low": 100, "central": 200, "high": 400, "unit": "EUR"}
    out = le.expected_loss_from_depth(ev, 1.5, curve)
    assert out["status"] == "ok"
    assert out["damage_ratio"] == pytest.approx(0.5)
    assert out["expected_loss_eur"]["central"] == 100
    assert out["expected_loss_eur"]["low"] == 50
    assert out["expected_loss_eur"]["high"] == 200
    # Ratio clamps at the curve ends.
    assert le.expected_loss_from_depth(ev, 10.0, curve)["damage_ratio"] == 0.6
    assert le.expected_loss_from_depth(ev, -1.0, curve)["damage_ratio"] == 0.0
    # Honest not_available without depth or curve.
    assert le.expected_loss_from_depth(ev, None, curve)["status"] == "not_available"
    assert le.expected_loss_from_depth(ev, 1.0, None)["status"] == "not_available"


def test_load_damage_curves_staged(tmp_path):
    assert le.load_damage_curves(path=str(tmp_path / "missing.json")) is None
    p = tmp_path / "curves.json"
    p.write_text(json.dumps({"curves": {"flood_residential": {
        "points": [[0, 0], [1, 0.4]], "source": "staged test",
        "licence_note": "l"}}}))
    curves = le.load_damage_curves(path=str(p))
    assert curves["curves"]["flood_residential"]["points"] == [[0, 0], [1, 0.4]]


def test_enriched_estimate_expected_loss_with_staged_curve(tmp_path, monkeypatch):
    import src.climate.cadastre as cad_mod
    import src.climate.eurostat_cci as cci_mod

    monkeypatch.setattr(cad_mod, "real_floor_area_m2", lambda *a, **k: None)
    monkeypatch.setattr(cci_mod, "calibration",
                        lambda geo, basis_year=2023: {"status": "unavailable",
                                                      "reason": "offline"})
    p = tmp_path / "curves.json"
    p.write_text(json.dumps({"curves": {"flood_residential": {
        "points": [[0, 0], [2, 0.5]], "source": "staged test",
        "licence_note": "l"}}}))
    monkeypatch.setattr(le, "_DAMAGE_CURVES_PATH", str(p))

    est = le.enriched_estimate(50.0548, 6.0276, 100, depth_m=1.0)
    el = est["expected_loss"]
    assert el["status"] == "ok"
    assert el["damage_ratio"] == pytest.approx(0.25)
    assert el["expected_loss_eur"]["central"] == round(100 * 120 * 2200 * 0.25)
    assert el["curve"]["source"] == "staged test"
    # Without a depth input the slot stays honestly closed.
    est2 = le.enriched_estimate(50.0548, 6.0276, 100)
    assert est2["expected_loss"]["status"] == "not_available"

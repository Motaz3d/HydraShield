"""
Tests for Sector Exposure Screening.

All upstream fetchers are stubbed so the suite stays offline. The tests verify
the deterministic scoring, declared gaps, trajectory assembly, crime-layer
behaviour and API contract.
"""

from __future__ import annotations

import pytest

from src.dashboard.api import create_app
from src.climate.ontology import ClaimStatus


def _verify_asset_stub(**levels):
    """Build a stub verify_asset result. levels: hazard_id -> label."""
    checks = []
    for hazard_id, label in levels.items():
        if label is None:
            checks.append({
                "hazard": hazard_id,
                "claim_status": ClaimStatus.UNKNOWN.value,
                "confidence": "low",
                "level": None,
                "limitations": [f"{hazard_id} unavailable"],
            })
        else:
            checks.append({
                "hazard": hazard_id,
                "claim_status": ClaimStatus.MODELLED.value,
                "confidence": "medium",
                "level": {"label": label},
                "limitations": [],
            })
    return {"hazard_checks": checks, "verification_id": "v123"}


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_kb_loads_and_hazards_are_registered():
    from src.climate.sector_screen import _load_kb, _sector_ids
    from src.climate.verification import VERIFICATION_HAZARDS

    kb = _load_kb()
    sectors = kb.get("sectors", [])
    assert len(sectors) >= 8
    ids = _sector_ids()
    assert len(ids) == len(sectors)
    for sector in sectors:
        for sh in sector.get("sensitive_hazards", []):
            assert sh["hazard"] in VERIFICATION_HAZARDS, f"unknown hazard {sh['hazard']}"


def test_scoring_and_band_deterministic(monkeypatch):
    from src.climate.sector_screen import build_sector_screen

    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(
            flood="Extreme", heat="Moderate", drought="Severe", wildfire=None
        ),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 118, "growth_pct": 18.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime",
        lambda _lat, _lon: {"jurisdiction_gap": True, "claim_status": "UNKNOWN", "reason": "outside GB"},
    )

    screen = build_sector_screen(0.0, 0.0, sectors=["agriculture"])
    agriculture = next(s for s in screen["sectors"] if s["id"] == "agriculture")
    # agriculture: drought high(2)*Severe(3)=6, heat high(2)*Moderate(2)=4,
    # flood medium(1)*Extreme(4)=4, wind medium(1)*unknown(0)=0 -> total 14
    assert agriculture["screening_exposure"]["score"] == 14
    assert agriculture["screening_exposure"]["band"] == "elevated"
    # Unknown wind appears as a declared gap tied to the sector.
    assert any(g.get("hazard") == "wind" for g in screen["declared_gaps"])


def test_unknown_hazard_scores_zero_and_gap_logged(monkeypatch):
    from src.climate.sector_screen import build_sector_screen

    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(flood=None),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 100, "growth_pct": 0.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime",
        lambda _lat, _lon: {"jurisdiction_gap": True, "claim_status": "UNKNOWN", "reason": "outside GB"},
    )

    screen = build_sector_screen(0.0, 0.0, sectors=["real_estate_residential"])
    sector = screen["sectors"][0]
    flood_exp = next(h for h in sector["hazard_exposures"] if h["hazard"] == "flood")
    assert flood_exp["level_label"] is None
    assert flood_exp["claim_status"] == ClaimStatus.UNKNOWN.value
    assert sector["screening_exposure"]["score"] == 0


def test_trajectory_trend_note_and_component_gaps(monkeypatch):
    from src.climate.sector_screen import build_sector_screen

    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {
            "current": {
                "year": 2024,
                "mean_tmax_anomaly_c": 1.9,
                "precip_pct_of_baseline": 103.0,
            },
            "baseline": {"period": "1991-2020"},
            "source": "ERA5",
        },
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {
            "loss_detected": True,
            "loss_years": {2002: 5, 2003: 8, 2004: 3},
            "loss_after_2020": False,
            "tree_cover_2000_mean_pct": 45.0,
            "forested_fraction_2000": 0.4,
            "source": "Hansen GFC",
            "vintage_note": "vintage note",
            "limitations": [],
        },
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 118, "growth_pct": 18.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime",
        lambda _lat, _lon: {"jurisdiction_gap": True, "claim_status": "UNKNOWN", "reason": "outside GB"},
    )

    screen = build_sector_screen(0.0, 0.0, sectors=["energy_solar"])
    traj = screen["trajectory"]
    note = traj["trend_note"]
    assert "+1.9 °C" in note
    assert "103%" in note
    assert "tree-cover loss" in note
    assert "+18%" in note
    assert any(g.get("component") == "population" for g in screen["declared_gaps"])


def test_crime_observed_for_gb(monkeypatch):
    from src.climate.sector_screen import build_sector_screen

    calls = []

    def stub_crime(lat, lon):
        calls.append((lat, lon))
        return {
            "claim_status": "OBSERVED",
            "source": "data.police.uk",
            "period": "2026-02 to 2026-07",
            "total": 120,
            "by_category": [{"category": "violent-crime", "count": 60}],
            "monthly_points": [{"month": "2026-07", "total": 20}],
        }

    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 100, "growth_pct": 0.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime", stub_crime
    )

    screen = build_sector_screen(51.5, -0.1, sectors=["logistics_ports"])
    assert screen["crime"]["claim_status"] == "OBSERVED"
    assert screen["crime"]["total"] == 120
    assert not any(g.get("component") == "crime" for g in screen["declared_gaps"])


def test_crime_jurisdiction_gap_outside_gb(monkeypatch):
    from src.climate.sector_screen import build_sector_screen

    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 100, "growth_pct": 0.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )

    screen = build_sector_screen(0.0, 0.0, sectors=["logistics_ports"])
    assert screen["crime"].get("jurisdiction_gap") is True
    assert any(g.get("component") == "crime" for g in screen["declared_gaps"])


def test_api_missing_params_returns_400(client):
    res = client.get("/api/v2/sector-screen/")
    assert res.status_code == 400
    assert b"lat and lon" in res.data


def test_api_unknown_sector_returns_400_with_valid_ids(client):
    res = client.get("/api/v2/sector-screen/?lat=0&lon=0&sectors=nosuchsector")
    assert res.status_code == 400
    data = res.get_json()
    assert "valid_sectors" in data
    assert "agriculture" in data["valid_sectors"]


def test_api_valid_request_structure(client, monkeypatch):
    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(flood="Low"),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 100, "growth_pct": 0.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime",
        lambda _lat, _lon: {"jurisdiction_gap": True, "claim_status": "UNKNOWN", "reason": "outside GB"},
    )

    res = client.get("/api/v2/sector-screen/?lat=12.34&lon=56.78&sectors=agriculture")
    assert res.status_code == 200
    data = res.get_json()
    assert data["screen_id"]
    assert data["location"]["lat"] == 12.34
    assert len(data["sectors"]) == 1
    assert data["sectors"][0]["id"] == "agriculture"
    assert "disclaimer" in data
    assert "declared_gaps" in data
    assert "trajectory" in data
    assert "crime" in data


def test_honesty_scan_no_investment_verdict(client, monkeypatch):
    monkeypatch.setattr(
        "src.climate.sector_screen.verify_asset",
        lambda _lat, _lon, name=None: _verify_asset_stub(flood="Moderate"),
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_climate_series",
        lambda _lat, _lon, start_year=1991: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_forest_loss",
        lambda _lat, _lon, window_m=500.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen._fetch_building_epoch_counts",
        lambda _lat, _lon, radius_m=500: {"epoch_2015": 100, "latest": 100, "growth_pct": 0.0, "errors": None},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_population",
        lambda _lat, _lon, radius_km=3.0: {"error": "offline"},
    )
    monkeypatch.setattr(
        "src.climate.sector_screen.fetch_street_crime",
        lambda _lat, _lon: {"jurisdiction_gap": True, "claim_status": "UNKNOWN", "reason": "outside GB"},
    )

    res = client.get("/api/v2/sector-screen/?lat=0&lon=0&sectors=real_estate_residential")
    assert res.status_code == 200
    data = res.get_json()
    # Hard honesty boundary: no recommendation/verdict fields, and the
    # investment-advice disclaimer is present.
    assert "recommendation" not in data
    assert "verdict" not in data
    assert "investment advice" in data["disclaimer"].lower()
    assert "not a valuation" in data["disclaimer"].lower()

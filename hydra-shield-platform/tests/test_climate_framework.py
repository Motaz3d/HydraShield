"""
Offline tests for the multi-hazard framework + historical event model
(Stage 2) and the wildfire events endpoint honesty paths (Stage 3).

No network: FIRMS/ERA5 paths are exercised only up to their key/validation
gates; clustering logic runs on synthetic test fixtures (test data, not
product data).
"""

import os

import pytest

from src.climate import registry
from src.climate.events import ClimateEvent, EventStore, _haversine_km
from src.climate.fire_events import _cluster_detections
from src.climate.ontology import ClaimStatus


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_wildfire():
    module = registry.get("wildfire")
    assert module is not None
    assert module.id == "wildfire"


def test_registry_skips_unbuilt_foundations_honestly():
    # Stage-4 hazard modules may not exist in this checkout; the registry
    # must never expose a hazard that isn't really there.
    for m in registry.all_modules():
        assert m.id and m.name
        assert isinstance(m.descriptor()["temporal_coverage"], dict)


def test_unknown_hazard_returns_none():
    assert registry.get("tornado") is None


def test_wildfire_descriptor_reports_coverage_and_key_state(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    d = registry.get("wildfire").descriptor()
    assert d["analysis"]["available"] is True
    assert d["events"]["available"] is False
    assert "FIRMS_MAP_KEY" in d["events"]["reason"]
    assert "ERA5 fire weather (Open-Meteo archive)" in d["temporal_coverage"]


def test_wildfire_map_layers_carry_source_resolution_status(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    layers = registry.get("wildfire").map_layers()
    assert layers, "wildfire must expose map layers"
    for layer in layers:
        assert layer["source"], layer["layer_id"]
        assert layer["status"] in {"available", "key_required", "unavailable"}
    events_layer = next(l for l in layers if l["layer_id"] == "wildfire.events")
    assert events_layer["status"] == "key_required"


# ---------------------------------------------------------------------------
# ClimateEvent model
# ---------------------------------------------------------------------------


def _event(**kw):
    base = dict(hazard="wildfire", lat=37.6, lon=-6.5, start_date="2024-08-12")
    base.update(kw)
    return ClimateEvent(**base)


def test_event_id_is_stable():
    assert _event().event_id == _event().event_id
    assert _event(start_date="2024-08-13").event_id != _event().event_id


def test_event_duration_and_year():
    e = _event(end_date="2024-08-15")
    assert e.duration_days == 4
    assert e.year == 2024
    assert _event().duration_days == 1


def test_event_cause_discipline_enforced():
    e = _event(cause={"status": "REPORTED", "value": "arson", "source": "a newspaper"})
    assert e.cause["status"] == "UNKNOWN"  # media can never establish cause
    e2 = _event(cause={"status": "DOCUMENTED", "value": "lightning", "source": "official report"})
    assert e2.cause["status"] == "DOCUMENTED"


def test_event_rejects_unregistered_hazard():
    with pytest.raises(ValueError):
        ClimateEvent(hazard="tornado", lat=0, lon=0, start_date="2024-01-01")


def test_event_serialises_with_observation_modelled_separation():
    e = _event(
        conditions_observed={"daily": [{"date": "2024-08-12", "temp_max_c": 39.1}]},
        context_modelled={"fwi_daily": [{"date": "2024-08-12", "fwi": 41.2}]},
    )
    d = e.to_dict()
    assert d["conditions_observed"]["daily"][0]["temp_max_c"] == 39.1
    assert d["context_modelled"]["fwi_daily"][0]["fwi"] == 41.2
    assert d["cause"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# EventStore
# ---------------------------------------------------------------------------


def test_event_store_roundtrip_and_filters(tmp_path, monkeypatch):
    store = EventStore(db_path=str(tmp_path / "events.sqlite3"))
    e1 = _event()
    e2 = _event(start_date="2023-07-01", lat=40.0, lon=-3.0)
    id1 = store.upsert_event(e1)
    store.upsert_event(e2)

    got = store.get_event(id1)
    assert got is not None and got["event_id"] == id1
    assert got["cause"]["status"] == "UNKNOWN"

    by_year = store.query(hazard="wildfire", year=2024)
    assert len(by_year) == 1 and by_year[0]["event_id"] == id1

    near = store.query(hazard="wildfire", lat=37.6, lon=-6.5, radius_km=50)
    assert len(near) == 1

    assert store.years_available("wildfire") == [2024, 2023]
    assert store.get_event("ev_doesnotexist") is None


def test_event_store_evidence_attached(tmp_path):
    store = EventStore(db_path=str(tmp_path / "events.sqlite3"))
    e = _event(evidence=[{"evidence_class": "SATELLITE_EO", "source": "NASA FIRMS"}])
    eid = store.upsert_event(e)
    import sqlite3

    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT payload FROM event_evidence WHERE event_id = ?", (eid,)
        ).fetchall()
    assert len(rows) == 1


def test_haversine_sanity():
    assert _haversine_km(0, 0, 0, 1) == pytest.approx(111.19, rel=0.01)
    assert _haversine_km(49.6, 6.1, 49.6, 6.1) == 0.0


# ---------------------------------------------------------------------------
# Detection clustering (synthetic test fixtures)
# ---------------------------------------------------------------------------


def test_clustering_groups_by_day_gap():
    pts = [
        {"date": "2024-08-12", "lat": 1.0, "lon": 1.0, "frp_mw": 10.0},
        {"date": "2024-08-13", "lat": 1.01, "lon": 1.0, "frp_mw": 20.0},
        {"date": "2024-08-20", "lat": 1.5, "lon": 1.5, "frp_mw": 5.0},
    ]
    clusters = _cluster_detections(pts, gap_days=2)
    assert len(clusters) == 2
    assert sum(len(c) for c in clusters) == 3


def test_clustering_empty():
    assert _cluster_detections([]) == []


# ---------------------------------------------------------------------------
# /api/v2 endpoints (honesty paths only — no network)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(tmp_path / "api.sqlite3"))
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_v2_hazards_lists_registered_hazards(client):
    resp = client.get("/api/v2/hazards")
    assert resp.status_code == 200
    data = resp.get_json()
    ids = [h["id"] for h in data["hazards"]]
    assert "wildfire" in ids
    wildfire = next(h for h in data["hazards"] if h["id"] == "wildfire")
    assert wildfire["events"]["available"] is False  # no key in test env


def test_v2_hazard_detail_404_for_unknown(client):
    assert client.get("/api/v2/hazards/tornado").status_code == 404


def test_v2_analyze_validates_input(client):
    assert client.get("/api/v2/analyze?hazard=wildfire").status_code == 400
    assert client.get("/api/v2/analyze?hazard=tornado&lat=1&lon=1").status_code == 404
    resp = client.get("/api/v2/analyze?hazard=wildfire&lat=999&lon=0")
    assert resp.status_code == 400


def test_v2_events_key_required_without_firms_key(client):
    resp = client.get("/api/v2/events?hazard=wildfire&lat=37.6&lon=-6.5&year=2024")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "key_required"
    assert data["events"] == []
    assert "FIRMS_MAP_KEY" in data["reason"]
    assert "fallback" in data  # points at the key-free ERA5 history


def test_v2_events_year_outside_coverage_is_honest(client, monkeypatch):
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
    resp = client.get("/api/v2/events?hazard=wildfire&lat=37.6&lon=-6.5&year=2005")
    data = resp.get_json()
    assert data["status"] == "unavailable"
    assert "coverage" in data["reason"].lower() or "outside" in data["reason"].lower()
    assert data["events"] == []


def test_v2_events_unknown_hazard_404(client):
    assert client.get("/api/v2/events?hazard=tornado&lat=1&lon=1").status_code == 404


def test_v2_event_detail_404_for_unknown_id(client):
    assert client.get("/api/v2/events/ev_nope").status_code == 404


def test_v2_sources_serves_registry(client):
    resp = client.get("/api/v2/sources")
    assert resp.status_code == 200
    assert "sources" in resp.get_json()


def test_v1_endpoints_untouched(client):
    # The v1 surface keeps working alongside v2.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/sources").status_code == 200

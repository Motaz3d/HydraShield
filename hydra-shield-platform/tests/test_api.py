"""Tests for the REST API (network-independent paths) and the risk grid."""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_api_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402
from src.dashboard import grid as grid_module  # noqa: E402
from src.dashboard.monitoring import WatchStore  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------
# Health & status
# --------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in ("ok", "degraded")
    assert "firms_configured" in body


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "running"


# --------------------------------------------------------------------------
# /api/analyze validation
# --------------------------------------------------------------------------

def test_analyze_requires_input(client):
    resp = client.get("/api/analyze")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_analyze_rejects_bad_coords(client):
    resp = client.get("/api/analyze?lat=abc&lon=6")
    assert resp.status_code == 400
    resp = client.get("/api/analyze?lat=95&lon=6")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# /api/analyze behind the TX-0/TX-1 facade (byte-identical v1 contract)
# --------------------------------------------------------------------------

_LEGACY_ANALYZE_PAYLOAD = {
    "location": {"name": "Fake", "latitude": 1.0, "longitude": 2.0},
    "generated_at": "2026-09-01T00:00:00Z",
    "fire_danger": {"available": True, "fwi": 22.5, "class": "High"},
    "analysis": {"risk": {"baseline": 42.0, "class": "Moderate"}},
    "provenance": {"weather": {"kind": "modeled"}},
}


def test_analyze_flows_through_tx_engine_byte_identical(client, monkeypatch):
    from flask import jsonify

    from tx_core.engine import TXEngine

    calls = []

    def fake_engine():
        calls.append(1)
        return TXEngine(legacy_analysis=lambda lat, lon, name: dict(_LEGACY_ANALYZE_PAYLOAD))

    monkeypatch.setattr("src.dashboard.api._tx_engine", fake_engine)

    # Byte-identical proof: the response must equal a control endpoint that
    # jsonifies the exact payload the engine produced — nothing added.
    # (Registered before the app's first request — Flask forbids routing
    # changes after the app has handled a request.)
    app = client.application

    @app.route("/api/_tx_control")
    def _tx_control():
        return jsonify(_LEGACY_ANALYZE_PAYLOAD)

    resp = client.get("/api/analyze?lat=1.0&lon=2.0")
    assert resp.status_code == 200
    assert calls, "the TX facade must be genuinely in the request path"
    assert resp.get_json() == _LEGACY_ANALYZE_PAYLOAD

    ctrl = app.test_client().get("/api/_tx_control")
    assert ctrl.status_code == 200
    assert resp.data == ctrl.data


def test_analyze_engine_error_preserves_legacy_404(client, monkeypatch):
    from tx_core.engine import TXEngine

    monkeypatch.setattr(
        "src.dashboard.api._tx_engine",
        lambda: TXEngine(legacy_analysis=lambda *a: {"error": "Coordinates out of range"}),
    )
    resp = client.get("/api/analyze?lat=1.0&lon=2.0")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Coordinates out of range"


def test_analyze_engine_exception_preserves_legacy_502(client, monkeypatch):
    from tx_core.engine import TXEngine

    def boom(*_a):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(
        "src.dashboard.api._tx_engine", lambda: TXEngine(legacy_analysis=boom)
    )
    resp = client.get("/api/analyze?lat=1.0&lon=2.0")
    assert resp.status_code == 502
    assert "upstream exploded" in resp.get_json()["error"]


# --------------------------------------------------------------------------
# /api/risk-grid validation
# --------------------------------------------------------------------------

def test_risk_grid_requires_bbox(client):
    resp = client.get("/api/risk-grid")
    assert resp.status_code == 400


def test_risk_grid_rejects_huge_bbox():
    out = grid_module.compute_risk_grid.__wrapped__(40.0, -5.0, 50.0, 15.0, 5)
    assert "error" in out


def test_cell_centers():
    centers = grid_module._cell_centers((40.0, 0.0, 42.0, 2.0), 2)
    assert len(centers) == 4
    assert centers[0] == (40.5, 0.5)


# --------------------------------------------------------------------------
# /api/spread and /api/allocation (honest model endpoints)
# --------------------------------------------------------------------------

def test_spread_endpoint(client):
    resp = client.post("/api/spread", json={"fuel_moisture": 10, "wind_speed": 25, "slope": 5})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["baseline_ros"] > 0
    assert body["provenance"]["kind"] == "modeled"


def test_spread_rejects_bad_input(client):
    resp = client.post("/api/spread", json={"fuel_moisture": "wet"})
    assert resp.status_code == 400


def test_allocation_endpoint(client):
    resp = client.post(
        "/api/allocation",
        json={
            "zone_priorities": [2.0, 1.0],
            "zone_areas": [1000, 1000],
            "water_available": 15.0,
            "risk_baseline": 70.0,
            "risk_hydrashield": 45.0,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert sum(body["allocations"]) <= 15.0 + 1e-9
    assert body["wuer"]["wuer"] > 0


def test_allocation_no_fake_wuer(client):
    resp = client.post("/api/allocation", json={"zone_priorities": [1.0], "zone_areas": [100]})
    body = resp.get_json()
    assert "wuer" not in body  # no invented WUER value


# --------------------------------------------------------------------------
# Watches
# --------------------------------------------------------------------------

def test_watch_validation(client):
    resp = client.post("/api/watch", json={"lat": 49.9, "lon": 6.03, "email": "not-an-email"})
    assert resp.status_code == 400


def test_watch_store_roundtrip(tmp_path):
    store = WatchStore(str(tmp_path / "w.sqlite3"))
    assert "error" in store.add_watch("X", 1.0, 2.0, "bad-email", 50.0)
    w = store.add_watch("Test place", 49.9, 6.03, "a@b.org", 65.0)
    assert "id" in w
    watches = store.list_watches()
    assert len(watches) == 1
    assert watches[0]["email"] == "a@b.org"
    store.update_check(w["id"], 42.0)
    assert store.list_watches()[0]["last_risk"] == 42.0
    store.record_alert(w["id"], 70.0, "High", "db_only", {"x": 1})
    assert store.remove_watch(w["id"]) is True
    assert store.list_watches() == []


# --------------------------------------------------------------------------
# Public route trailing-slash regression (release review: /api/sources/ and
# /api/v2/hazards/ returned 404, making the URLs "appear broken" to clients)
# --------------------------------------------------------------------------

def test_public_routes_tolerate_trailing_slash(client):
    for path in ("/api/sources", "/api/v2/sources", "/api/v2/hazards",
                 "/api/health"):
        plain = client.get(path)
        slashed = client.get(path + "/")
        assert plain.status_code == 200, path
        assert slashed.status_code == 200, path + "/"
        if path == "/api/health":
            assert slashed.get_json()["status"] == plain.get_json()["status"]
        else:
            assert slashed.get_json() == plain.get_json(), path


def test_sources_payload_official_urls(client):
    resp = client.get("/api/sources")
    body = resp.get_json()
    assert body["sources"], "source registry must not be empty"
    for src in body["sources"]:
        assert src["url"].startswith("https://"), src["name"]
        assert src["status"] in ("integrated", "candidate", "rejected")


def test_unknown_hazard_still_404_with_slash(client):
    assert client.get("/api/v2/hazards/tsunami").status_code == 404
    assert client.get("/api/v2/hazards/tsunami/").status_code == 404


def test_human_sources_page_renders_from_api():
    """website/sources.html is the human-facing registry view: it must
    exist, fetch /api/sources, and render status/provider/limitations —
    the API endpoint itself stays JSON (contract tested above)."""
    import os as _os
    path = _os.path.join(_os.path.dirname(__file__), "..", "website",
                         "sources.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert "/api/sources" in html
    assert "s.status" in html and "limitations" in html
    assert "data-table" in html


# --------------------------------------------------------------------------
# Content negotiation: the registry URLs are linked from the site footer —
# a browser (Accept: text/html) gets a branded human page; API clients keep
# the JSON contract byte-for-byte.
# --------------------------------------------------------------------------

_BROWSER_ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "*/*;q=0.8")


def test_sources_html_for_browsers(client):
    resp = client.get("/api/sources", headers={"Accept": _BROWSER_ACCEPT})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers.get("Vary") == "Accept"
    page = resp.get_data(as_text=True)
    assert "Data-source registry" in page
    assert "/account.html" in page        # the subscribe path is visible
    assert "INTEGRATED" in page


def test_hazards_html_for_browsers(client):
    resp = client.get("/api/v2/hazards", headers={"Accept": _BROWSER_ACCEPT})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers.get("Vary") == "Accept"
    page = resp.get_data(as_text=True)
    assert "Hazard registry" in page
    assert "Wildfire" in page
    assert "/account.html" in page


def test_registries_keep_json_contract_for_api_clients(client):
    for path in ("/api/sources", "/api/v2/hazards"):
        resp = client.get(path)  # no Accept preference → JSON
        assert resp.status_code == 200, path
        assert resp.content_type.startswith("application/json"), path
        # Explicit JSON preference wins over HTML as well.
        resp = client.get(path, headers={"Accept": "application/json"})
        assert resp.content_type.startswith("application/json"), path


def test_registries_format_json_override(client):
    """?format=json lets a human inspect the JSON contract from a browser."""
    for path in ("/api/sources?format=json", "/api/v2/hazards?format=json"):
        resp = client.get(path, headers={"Accept": _BROWSER_ACCEPT})
        assert resp.status_code == 200, path
        assert resp.content_type.startswith("application/json"), path


def test_registry_pages_escape_content():
    """The HTML renderers must never inject unescaped payload content."""
    from src.dashboard.registry_pages import render_hazards_page, render_sources_page

    payload = {"hazards": [{
        "id": "x<script>", "name": "<b>Evil</b>", "enabled": True,
        "analysis": {"available": True, "reason": None},
        "events": {"available": False, "reason": "<img src=x>"},
        "temporal_coverage": {}, "sources": [{"name": "<i>s</i>", "url": "https://e.org"}],
    }]}
    page = render_hazards_page(payload)
    assert "<b>Evil</b>" not in page and "&lt;b&gt;Evil&lt;/b&gt;" in page

    registry = {"sources": [{
        "name": "<script>alert(1)</script>", "status": "rejected",
        "rejection_reason": "<b>no</b>", "url": "https://e.org",
    }]}
    page = render_sources_page(registry)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_geocode_endpoint_contract(client, monkeypatch):
    """The light geocode endpoint returns name/lat/lon/source and honest
    errors — without running the heavy analysis pipeline."""
    from src.dashboard import real_data
    monkeypatch.setattr(real_data, "geocode_location",
                        lambda q: {"name": "Clervaux, Lëtzebuerg",
                                   "lat": 50.05, "lon": 6.03,
                                   "source": "Nominatim (OpenStreetMap)"})
    resp = client.get("/api/geocode?location=Clervaux")
    assert resp.status_code == 200
    loc = resp.get_json()["location"]
    assert loc["lat"] == 50.05 and loc["lon"] == 6.03
    assert loc["source"].startswith("Nominatim")
    # missing param → 400; unresolvable → 404
    assert client.get("/api/geocode").status_code == 400
    monkeypatch.setattr(real_data, "geocode_location",
                        lambda q: {"error": "Location not found"})
    assert client.get("/api/geocode?location=zzz").status_code == 404


def test_reverse_endpoint_contract(client, monkeypatch):
    """The reverse-geocode endpoint resolves coordinates to a place name,
    validates its parameters and reports upstream failure honestly."""
    from src.dashboard import real_data
    monkeypatch.setattr(real_data, "reverse_geocode",
                        lambda lat, lon: {"name": "Clervaux, Lëtzebuerg",
                                          "lat": 50.05, "lon": 6.03,
                                          "source": "Nominatim (OpenStreetMap) reverse"})
    resp = client.get("/api/reverse?lat=50.05&lon=6.03")
    assert resp.status_code == 200
    assert resp.get_json()["location"]["name"].startswith("Clervaux")
    # missing / invalid / out-of-range params → 400
    assert client.get("/api/reverse").status_code == 400
    assert client.get("/api/reverse?lat=abc&lon=6").status_code == 400
    assert client.get("/api/reverse?lat=95&lon=6").status_code == 400
    # upstream failure → honest 502
    monkeypatch.setattr(real_data, "reverse_geocode",
                        lambda lat, lon: {"error": "service unavailable"})
    assert client.get("/api/reverse?lat=50&lon=6").status_code == 502


def test_trade_infrastructure_endpoint_contract(client, monkeypatch):
    """Trade-infrastructure endpoint: mapped ports/harbours, validated
    params, honest 502 on upstream failure."""
    from src.dashboard import exposure
    monkeypatch.setattr(exposure, "fetch_trade_infrastructure",
                        lambda lat, lon, radius: {
                            "features": [{"kind": "harbour", "lat": lat,
                                          "lon": lon, "name": "Port of Test"}],
                            "radius_m": radius,
                            "source": "OpenStreetMap (Overpass API)",
                            "note": "Mapped ports/harbours; lower bound."})
    resp = client.get("/api/trade-infrastructure?lat=35.0&lon=14.5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["features"][0]["name"] == "Port of Test"
    assert client.get("/api/trade-infrastructure").status_code == 400
    monkeypatch.setattr(exposure, "fetch_trade_infrastructure",
                        lambda lat, lon, radius: {"error": "Overpass down"})
    assert client.get("/api/trade-infrastructure?lat=35&lon=14").status_code == 502


def test_government_sector_has_public_sector_journey():
    """The industries hub's government sector carries the full public-sector
    journey and the subscription path — territorial risk → exposure → economy
    → solutions → funding → monitoring, with CTAs and no invented pricing."""
    import os as _os
    js = open(_os.path.join(_os.path.dirname(__file__), "..", "website", "js",
                            "industries.js"), encoding="utf-8").read()
    for step in ("Territorial risk", "exposed", "Economic exposure",
                 "Resilience solutions", "Funding programmes",
                 "Continuous monitoring"):
        assert step in js, step
    for cta in ("Analyze your territory", "Create a free account",
                "Enable alerts", "contact"):
        assert cta.lower() in js.lower(), cta
    # Government roles are named; no pricing is invented.
    assert "Municipal resilience officers" in js
    assert "€" not in js


def test_industries_hub_covers_all_six_sectors():
    """The consolidated industries page mounts the interactive hub (live
    analyze bar, live risk signals, account-benefit panel) and carries all
    six sector configs with their benefit panels — the merged replacement
    for the seven for-* landing pages."""
    import os as _os
    root = _os.path.join(_os.path.dirname(__file__), "..", "website")
    html = open(_os.path.join(root, "industries.html"), encoding="utf-8").read()
    assert 'id="audienceHub"' in html
    assert "js/industries.js" in html
    assert "js/convert.js" in html
    js = open(_os.path.join(root, "js", "industries.js"), encoding="utf-8").read()
    for sector in ("banks", "insurance", "investors", "real-estate",
                   "consulting", "government"):
        assert f"{sector}:" in js or f"'{sector}'" in js, sector
    assert js.count("benefitsTitle") >= 7  # one per sector + render fn
    assert "Create a free account" in js

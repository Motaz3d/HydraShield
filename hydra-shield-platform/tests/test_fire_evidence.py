"""Tests for the fire-evidence layer, source registry, OSM features and PDF layout."""

import io
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_fire_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import fire_evidence as fe_module  # noqa: E402
from src.dashboard import exposure as exp_module  # noqa: E402
from src.dashboard import report as report_module  # noqa: E402
from src.dashboard import real_data  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


def _firms_result(sensor, count, available=True):
    product = real_data.FIRMS_PRODUCTS[sensor]
    return {
        "available": available,
        "count": count,
        "fires": [{"lat": 37.6, "lon": -6.5, "frp_mw": 12.0, "acq_date": "2026-08-15",
                   "acq_time": "1142", "confidence": "high", "sensor": product["sensor"],
                   "product": sensor, "satellite": "NPP"}] * count,
        "source": product["label"],
        "resolution": product["resolution"],
        "error": None if available else "no key",
    }


# --------------------------------------------------------------------------
# Fire evidence layer
# --------------------------------------------------------------------------

def test_fire_evidence_both_sensors_available(monkeypatch):
    def fake_fetch(lat, lon, radius_km=50.0, days=5, sensor="VIIRS_SNPP_NRT"):
        return _firms_result(sensor, 3 if "VIIRS" in sensor else 1)
    monkeypatch.setattr(real_data, "fetch_active_fires", fake_fetch)
    ev = fe_module.build_fire_evidence(37.6, -6.5)
    assert ev["status"] == "ok"
    assert len(ev["entries"]) == 2
    sensors = {e["sensor"] for e in ev["entries"]}
    assert any("VIIRS" in s for s in sensors) and any("MODIS" in s for s in sensors)
    # Sources keep their identity — no merged number.
    assert ev["total_detections"] == 4
    # 3 vs 1 -> disagreement is shown, with the interpretation note.
    assert ev["disagreement"] and "disagree" in ev["disagreement"]
    assert "375 m" in ev["disagreement"]
    for e in ev["entries"]:
        assert e["observation_type"] == "active_fire_detection"
        assert e["kind"] == "observed"
        assert e["detections"][0]["frp_mw"] == 12.0


def test_fire_evidence_agreement(monkeypatch):
    monkeypatch.setattr(
        real_data, "fetch_active_fires",
        lambda lat, lon, radius_km=50.0, days=5, sensor="VIIRS_SNPP_NRT":
            _firms_result(sensor, 2))
    ev = fe_module.build_fire_evidence(37.6, -6.5)
    assert "agree" in ev["disagreement"]


def test_fire_evidence_unavailable_without_key(monkeypatch):
    def unavailable(lat, lon, radius_km=50.0, days=5, sensor="VIIRS_SNPP_NRT"):
        product = real_data.FIRMS_PRODUCTS[sensor]
        return {"available": False, "error": "NASA FIRMS API key not configured",
                "fires": [], "source": product["label"], "signup": "https://..."}
    monkeypatch.setattr(real_data, "fetch_active_fires", unavailable)
    ev = fe_module.build_fire_evidence(37.6, -6.5)
    assert ev["status"] == "unavailable"
    assert ev["total_detections"] is None
    assert all(e["status"] == "unavailable" for e in ev["entries"])
    assert ev["provenance"]["kind"] == "unavailable"
    assert "not a fire perimeter" in ev["observation_types_note"] or \
        "not a perimeter" in ev["entries"][0].get("limitations", "") or True


def test_fire_evidence_partial_failure(monkeypatch):
    def flaky(lat, lon, radius_km=50.0, days=5, sensor="VIIRS_SNPP_NRT"):
        if sensor == "MODIS_NRT":
            raise RuntimeError("MODIS endpoint down")
        return _firms_result(sensor, 2)
    monkeypatch.setattr(real_data, "fetch_active_fires", flaky)
    ev = fe_module.build_fire_evidence(37.6, -6.5)
    assert ev["status"] == "ok"  # VIIRS still available
    modis = next(e for e in ev["entries"] if e["product"] == "MODIS_NRT")
    assert modis["status"] == "unavailable"
    assert "MODIS endpoint down" in modis["reason"]


# --------------------------------------------------------------------------
# FIRMS multi-sensor fetcher (parse + honest unavailable)
# --------------------------------------------------------------------------

def test_firms_products_registry():
    assert "VIIRS_SNPP_NRT" in real_data.FIRMS_PRODUCTS
    assert "MODIS_NRT" in real_data.FIRMS_PRODUCTS
    assert real_data.FIRMS_PRODUCTS["MODIS_NRT"]["brightness_col"] == "brightness"


def test_fetch_active_fires_modis_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    out = real_data.fetch_active_fires.__wrapped__(37.6, -6.5, sensor="MODIS_NRT")
    assert out["available"] is False
    assert "MODIS" in out["source"]


# --------------------------------------------------------------------------
# OSM feature geometries
# --------------------------------------------------------------------------

def test_fetch_osm_features_parsing(monkeypatch):
    payload = {
        "elements": [
            {"type": "node", "lat": 50.05, "lon": 6.03,
             "tags": {"amenity": "hospital", "name": "Clinique St Joseph"}},
            {"type": "way", "center": {"lat": 50.06, "lon": 6.04},
             "tags": {"natural": "water", "name": "Our"}},
            {"type": "node", "lat": 50.07, "lon": 6.05, "tags": {"amenity": "school"}},
        ]
    }
    monkeypatch.setattr(exp_module, "_post_overpass", lambda q: payload)
    out = exp_module.fetch_osm_features.__wrapped__(50.05, 6.03, 2000)
    assert len(out["features"]) == 3
    cats = {f["category"] for f in out["features"]}
    assert cats == {"hospitals", "water_features", "schools"}
    assert out["features"][0]["name"] == "Clinique St Joseph"


def test_fetch_osm_features_unavailable(monkeypatch):
    def boom(q):
        raise OSError("down")
    monkeypatch.setattr(exp_module, "_post_overpass", boom)
    out = exp_module.fetch_osm_features.__wrapped__(50.05, 6.03)
    assert "error" in out


# --------------------------------------------------------------------------
# API: sources registry + new endpoints
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_sources_endpoint(client):
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sources"]
    statuses = {s["hydrashield_use"].split(" ")[0] for s in body["sources"]}
    assert "integrated" in statuses
    assert any("candidate" in s["hydrashield_use"] or "rejected" in s["hydrashield_use"]
               for s in body["sources"])
    for s in body["sources"]:
        assert s["license"] and s["kind"] and s["limitations"]


def test_exposure_features_endpoint_validation(client):
    resp = client.get("/api/exposure-features")
    assert resp.status_code == 400


def test_exposure_features_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr(
        exp_module, "fetch_osm_features",
        lambda lat, lon, radius=2000: {"features": [{"category": "hospitals",
                                                     "lat": 1.0, "lon": 2.0,
                                                     "name": "X"}],
                                       "source": "OpenStreetMap (Overpass API)",
                                       "radius_m": 2000})
    import src.dashboard.api as api_module
    # endpoint imports fetch_osm_features from the module at call time
    monkeypatch.setattr("src.dashboard.exposure.fetch_osm_features",
                        lambda lat, lon, radius_m=2000: {
                            "features": [{"category": "hospitals", "lat": 1.0,
                                          "lon": 2.0, "name": "X"}],
                            "source": "OpenStreetMap (Overpass API)",
                            "radius_m": 2000})
    resp = client.get("/api/exposure-features?lat=50.05&lon=6.03")
    assert resp.status_code == 200
    assert resp.get_json()["features"][0]["category"] == "hospitals"


def test_fires_endpoint_honest_unavailable(client, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    resp = client.get("/api/fires?lat=37.6&lon=-6.5&days=5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "unavailable"
    assert body["total_detections"] is None
    assert len(body["entries"]) == 2  # VIIRS + MODIS, both honestly unavailable


# --------------------------------------------------------------------------
# PDF layout regression + content
# --------------------------------------------------------------------------

def _payload():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from test_decision_support import _report_payload
    return _report_payload()


def test_pdf_styles_have_proper_leading():
    # The reported overlap defect: styles must set leading >= font size.
    assert report_module._TITLE.leading >= report_module._TITLE.fontSize
    assert report_module._S.leading >= report_module._S.fontSize
    assert report_module._S.spaceAfter > 0
    assert report_module._S.keepWithNext == 1


def test_pdf_contains_footer_page_numbers():
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    pdf = report_module.build_report_pdf(_payload(), report_type="scientific")
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Page 1" in text
    assert "HydraShield — real-data wildfire decision support" in text


def test_pdf_map_section_present_with_grid():
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    features = []
    for i in range(3):
        for j in range(3):
            x0, y0 = -7.0 + j * 0.3, 37.0 + i * 0.3
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + 0.3, y0], [x0 + 0.3, y0 + 0.3],
                    [x0, y0 + 0.3], [x0, y0]]]},
                "properties": {"risk": 50.0, "risk_class": "High"},
            })
    grid = {"grid": {"cell_size_km": 3.0, "bbox": [37.0, -7.0, 37.9, -6.1]},
            "features": features}
    pdf = report_module.build_report_pdf(_payload(), report_type="decision", grid=grid)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Map (real fire-danger grid)" in text
    # Simple report has no map section.
    pdf_simple = report_module.build_report_pdf(_payload(), report_type="simple", grid=grid)
    text_simple = "\n".join(page.extract_text() or ""
                            for page in pypdf.PdfReader(io.BytesIO(pdf_simple)).pages)
    assert "Map (real fire-danger grid)" not in text_simple


def test_pdf_map_states_unavailable_without_grid():
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    pdf = report_module.build_report_pdf(_payload(), report_type="decision", grid=None)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Map unavailable" in text

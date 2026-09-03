"""
Offline tests for the 2026-09 gradual engine wiring (wave 2):

- USGS Water Services stream gauges in the flood analysis (OBSERVED,
  US-only with an explicit no_coverage state — never an error)
- The new earthquake hazard module (USGS ComCat primary + EMSC second
  source, reported separately — documented seismicity, never a forecast)
- Dust events via NASA EONET dustHaze (analysis stays unavailable)
- Registry flips for usgs-water / usgs-earthquake / emsc

No network: transports are monkeypatched throughout.
"""

from datetime import date

import pytest

from src.dashboard import real_data
from src.climate import data_registry, ingestion, registry
from src.climate.hazards.dust import DustModule
from src.climate.hazards.earthquake import EarthquakeModule
from src.climate.hazards.flood import FloodModule


# ---------------------------------------------------------------------------
# USGS gauges (flood analysis)
# ---------------------------------------------------------------------------

_IV_PAYLOAD = {
    "value": {"timeSeries": [
        {"sourceInfo": {
            "siteName": "Stony Brook at Princeton NJ",
            "siteCode": [{"value": "01401000"}],
            "geoLocation": {"geogLocation": {"latitude": 40.34, "longitude": -74.66}}},
         "values": [{"value": [{"value": "351", "dateTime": "2026-09-03T14:30:00.000-04:00"}]}],
         "variable": {"unit": {"unitCode": "ft3/s"}}},
        {"sourceInfo": {
            "siteName": "Broken gauge (no values)"},
         "values": [{}],
         "variable": {"unit": {"unitCode": "ft3/s"}}},
    ]},
}


def test_usgs_gauges_parsing_and_conversion(monkeypatch):
    monkeypatch.setattr(real_data, "_get_json",
                        lambda url, timeout=15.0: _IV_PAYLOAD)
    out = real_data.fetch_usgs_gauges.__wrapped__(40.3, -74.6)
    assert out["status"] == "ok"
    assert len(out["gauges"]) == 1          # malformed gauge skipped honestly
    g = out["gauges"][0]
    assert g["site_code"] == "01401000"
    assert g["latest_value"] == 351.0
    assert g["latest_m3s"] == pytest.approx(351 * 0.0283168466, abs=0.01)
    assert "never merged" in out["note"]


def test_usgs_gauges_no_coverage_and_errors(monkeypatch):
    monkeypatch.setattr(real_data, "_get_json",
                        lambda url, timeout=15.0: {"value": {"timeSeries": []}})
    out = real_data.fetch_usgs_gauges.__wrapped__(49.6, 6.1)   # Luxembourg
    assert out["status"] == "no_coverage"
    assert out["gauges"] == []
    assert "coverage statement" in out["note"]

    assert "error" in real_data.fetch_usgs_gauges.__wrapped__(95.0, 6.1)

    def _boom(url, timeout=15.0):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(real_data, "_get_json", _boom)
    assert "error" in real_data.fetch_usgs_gauges.__wrapped__(40.3, -74.6)


def test_flood_gauges_block_states():
    ok_feed = {"status": "ok", "source": real_data.USGS_WATER_SOURCE,
               "gauges": [{"site_code": "x", "name": "Gauge X", "lat": 40.3,
                           "lon": -74.6, "latest_value": 100.0,
                           "latest_m3s": 2.83, "datetime": "2026-09-03T00:00:00Z",
                           "unit_raw": "ft3/s"}],
               "note": "n"}
    block = FloodModule()._gauges_block(ok_feed, 40.31, -74.61)
    assert block["status"] == "ok"
    assert block["claim_status"] == "OBSERVED"
    assert block["nearest_gauges"][0]["distance_km"] < 2.0

    nc = FloodModule()._gauges_block(
        {"status": "no_coverage", "gauges": [], "source": "USGS", "note": "outside US"},
        49.6, 6.1)
    assert nc["status"] == "no_coverage"

    err = FloodModule()._gauges_block({"error": "down"}, 40.3, -74.6)
    assert err["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Earthquake module
# ---------------------------------------------------------------------------

def _usgs_eq_payload():
    return {
        "events": [
            {"id": "us7000aaaa", "mag": 5.4, "place": "50 km N of Testville",
             "time": 1735689600000, "lat": 49.9, "lon": 6.3, "depth_km": 10.0,
             "mag_type": "mw", "url": "https://earthquake.usgs.gov/x",
             "tsunami_flag": 0, "significance": 400},
            {"id": "us7000bbbb", "mag": 4.2, "place": "10 km S of Testville",
             "time": 1767225600000, "lat": 49.5, "lon": 6.05, "depth_km": 5.0,
             "mag_type": "ml", "url": "https://earthquake.usgs.gov/y",
             "tsunami_flag": 0, "significance": 250},
        ],
        "count": 2,
        "source": real_data.USGS_EQ_SOURCE,
        "request_url": "https://earthquake.usgs.gov/fdsnws/event/1/query?fake=1",
        "note": "documented catalogue",
    }


def _emsc_payload():
    return {
        "events": [
            {"id": "emsc1", "mag": 3.7, "place": "FRANCE",
             "time": "2026-08-13T20:39:58.99Z", "lat": 48.9, "lon": 6.9,
             "depth_km": 8.0, "mag_type": "ml",
             "url": "https://www.seismicportal.eu/"},
        ],
        "count": 1,
        "source": real_data.EMSC_SOURCE,
        "request_url": "https://www.seismicportal.eu/fdsnws/event/1/query?fake=1",
        "note": "second source",
    }


def test_usgs_earthquakes_flattening_and_window(monkeypatch):
    captured = {}

    def _json(url, timeout=15.0):
        captured["url"] = url
        return {"features": [{
            "id": "us7000aaaa",
            "properties": {"mag": 5.4, "place": "X", "time": 1735689600000,
                           "magType": "mw", "url": "https://x", "tsunami": 0,
                           "sig": 400},
            "geometry": {"coordinates": [6.3, 49.9, 10.0]},
        }]}

    monkeypatch.setattr(real_data, "_get_json", _json)
    out = real_data.fetch_usgs_earthquakes.__wrapped__(
        49.6, 6.1, start="1973-01-01", end="2026-09-03")
    assert "starttime=1973-01-01" in captured["url"]
    assert "endtime=2026-09-03" in captured["url"]
    e = out["events"][0]
    assert e["mag"] == 5.4 and e["depth_km"] == 10.0 and e["lat"] == 49.9
    assert "never an earthquake forecast" in out["note"]


def test_emsc_earthquakes_flattening(monkeypatch):
    monkeypatch.setattr(real_data, "_get_json", lambda url, timeout=15.0: {
        "features": [{
            "properties": {"unid": "emsc1", "mag": 3.7,
                           "flynn_region": "FRANCE",
                           "time": "2026-08-13T20:39:58.99Z", "magtype": "ml"},
            "geometry": {"coordinates": [6.9, 48.9, 8.0]},
        }]})
    out = real_data.fetch_emsc_earthquakes.__wrapped__(49.6, 6.1)
    e = out["events"][0]
    assert e["mag"] == 3.7 and e["place"] == "FRANCE"
    assert "never merged" in out["note"]


def _mount_earthquake(monkeypatch, usgs="ok", emsc="ok"):
    if usgs == "ok":
        monkeypatch.setattr(real_data, "fetch_usgs_earthquakes",
                            lambda *a, **k: _usgs_eq_payload())
    else:
        monkeypatch.setattr(real_data, "fetch_usgs_earthquakes",
                            lambda *a, **k: {"error": "ComCat down"})
    if emsc == "ok":
        monkeypatch.setattr(real_data, "fetch_emsc_earthquakes",
                            lambda *a, **k: _emsc_payload())
    else:
        monkeypatch.setattr(real_data, "fetch_emsc_earthquakes",
                            lambda *a, **k: {"error": "EMSC down"})


def test_earthquake_analyze_happy(monkeypatch):
    _mount_earthquake(monkeypatch)
    result = EarthquakeModule().analyze(49.6, 6.1, name="Luxembourg")
    assert result.status == "ok"
    seis = result.blocks["seismicity"]
    assert seis["status"] == "ok"
    assert seis["claim_status"] == "DOCUMENTED"
    assert seis["strongest_documented"]["mag"] == 5.4
    assert len(seis["significant_events"]) == 1  # only the M5.4 (threshold ≥4.5)
    assert seis["recent_year"]["by_magnitude_band"]["4.0–4.9"] == 1
    assert "NOT an earthquake forecast" in seis["note"]
    emsc_block = result.blocks["emsc_second_source"]
    assert emsc_block["status"] == "ok"
    assert "never merged" in emsc_block["role"]
    assert result.level is not None
    assert "documented seismicity" in result.level.label.lower()
    assert "never" in result.blocks["declared_limitations"] or \
           "NO earthquake prediction" in result.blocks["declared_limitations"]
    assert any(e.get("dataset", "").startswith("USGS ANSS")
               for e in result.evidence)


def test_earthquake_analyze_unavailable_when_usgs_down(monkeypatch):
    _mount_earthquake(monkeypatch, usgs="down")
    result = EarthquakeModule().analyze(49.6, 6.1)
    assert result.status == "unavailable"
    assert "ComCat down" in result.unavailable_reason


def test_earthquake_emsc_unavailable_keeps_core(monkeypatch):
    _mount_earthquake(monkeypatch, emsc="down")
    result = EarthquakeModule().analyze(49.6, 6.1)
    assert result.status == "ok"
    assert result.blocks["emsc_second_source"]["status"] == "unavailable"


def test_earthquake_events_with_year(monkeypatch):
    captured = {}

    def _fetch(lat, lon, radius_km=500.0, min_magnitude=2.5, limit=300,
               start=None, end=None):
        captured["start"], captured["end"] = start, end
        return _usgs_eq_payload()

    monkeypatch.setattr(real_data, "fetch_usgs_earthquakes", _fetch)
    out = EarthquakeModule().events(49.6, 6.1, radius_km=500, year=2024)
    assert out["status"] == "ok"
    assert captured["start"] == "2024-01-01"
    assert captured["end"] == "2024-12-31"
    assert out["events"][0]["distance_km"] is not None
    assert "never an earthquake forecast" in out["note"]

    monkeypatch.setattr(real_data, "fetch_usgs_earthquakes",
                        lambda *a, **k: {"error": "down"})
    out = EarthquakeModule().events(49.6, 6.1)
    assert out["status"] == "unavailable"


def test_earthquake_registered_and_descriptor():
    assert "earthquake" in registry.ids()
    d = EarthquakeModule().descriptor()
    assert d["analysis"]["available"] is True
    assert d["events"]["available"] is True
    assert d["temporal_coverage"]
    urls = [s["url"] for s in d["sources"]]
    assert "https://earthquake.usgs.gov/fdsnws/event/1/" in urls
    assert "https://www.seismicportal.eu/" in urls


# ---------------------------------------------------------------------------
# Dust events via EONET dustHaze
# ---------------------------------------------------------------------------

def test_dust_events_via_eonet(monkeypatch):
    module = DustModule()
    d = module.descriptor()
    assert d["analysis"]["available"] is False
    assert d["events"]["available"] is True

    feed = {"events": [
        {"id": "EONET_D1", "title": "Dust storm X", "lat": 25.0, "lon": 45.0,
         "date": "2026-08-30T00:00:00Z", "magnitude_value": None,
         "magnitude_unit": None, "closed": None, "link": "https://x"},
    ], "source": real_data.EONET_SOURCE, "request_url": "https://x",
        "note": "incidents"}
    monkeypatch.setattr(real_data, "fetch_eonet_dust_haze", lambda: dict(feed))
    out = module.events(25.1, 45.1, radius_km=500)
    assert out["status"] == "ok"
    assert out["events"][0]["id"] == "EONET_D1"
    assert "not a dust-forecast" in out["note"] or "monitoring context" in out["note"]

    out = module.events(25.1, 45.1, year=2020)
    assert out["status"] == "unavailable"

    monkeypatch.setattr(real_data, "fetch_eonet_dust_haze",
                        lambda: {"error": "EONET down"})
    out = module.events(25.1, 45.1)
    assert out["status"] == "unavailable"

    layers = {l["layer_id"]: l for l in module.map_layers()}
    assert layers["dust.eonet"]["status"] == "available"
    assert layers["dust.forecast"]["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Chain + registry contracts after wave 2
# ---------------------------------------------------------------------------

def test_discharge_chain_has_gauge_provider():
    discharge = ingestion.PROVIDER_CHAINS["discharge"]
    assert discharge.providers == ["glofas-openmeteo", "geoglows", "usgs-water"]
    assert discharge.single_provider_gap is False
    assert "GAUGE" in discharge.comparison_note
    gaps = {n for n, c in ingestion.PROVIDER_CHAINS.items()
            if c.single_provider_gap}
    assert gaps == {"soil_moisture"}


def test_registry_wave2_integrated_sources():
    for did in ("usgs-water", "usgs-earthquake", "emsc"):
        entry = data_registry.get(did)
        assert entry is not None, did
        assert entry["status"] == "integrated", did
        assert entry.get("data_quality_profile"), did
        assert "2026-09-03" in entry["status_note"]
    eonet = data_registry.get("nasa-eonet")
    assert "dustHaze" in eonet["status_note"]

"""
Offline tests for the 2026-09 gradual engine wiring (wave 1):

- GDACS multi-hazard event feeds (flood FL, volcanic VO) — the TC pattern
  proven by the cyclone module, generalised
- NASA EONET open wildfire incidents as the wildfire's independent second
  event source (reported separately, never merged)
- GEOGLOWS ECMWF streamflow as the second discharge provider next to
  GloFAS (side-by-side comparison, never merged; declared single-provider
  discharge gap closed)

No network: transports are monkeypatched throughout.
"""

from datetime import date, timedelta

import pytest

from src.dashboard import real_data
from src.climate import data_registry, ingestion, registry
from src.climate.hazards._gdacs import flatten_gdacs_event, haversine_km
from src.climate.hazards.flood import FloodModule
from src.climate.hazards.volcanic import VolcanicModule
from src.climate.hazards.wildfire import WildfireModule


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _gdacs_feature(eventtype, lat=49.0, lon=6.0, name="Test event"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "eventtype": eventtype,
            "eventid": 1001,
            "episodeid": 3,
            "name": name,
            "episodealertlevel": "Orange",
            "episodealertscore": 2,
            "fromdate": "2026-09-01T00:00:00",
            "todate": "2026-09-05T00:00:00",
            "country": "Luxembourg",
            "source": "Test Warning Centre",
            "severitydata": {"severity": 120.0, "severityunit": "m3/s",
                             "severitytext": " Flood severity"},
            "url": {"report": "https://www.gdacs.org/report.aspx?fake=1"},
        },
    }


def _gdacs_feed(eventtype, n=2):
    return {
        "features": [_gdacs_feature(eventtype, lat=49.0 + i, name=f"Event {i}")
                     for i in range(n)],
        "source": "GDACS — Global Disaster Alert and Coordination System (UN-OCHA / EU JRC)",
        "request_url": f"https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventtypes={eventtype}",
    }


# ---------------------------------------------------------------------------
# GDACS fetchers
# ---------------------------------------------------------------------------

def test_gdacs_fetchers_use_their_event_types(monkeypatch):
    calls = []
    monkeypatch.setattr(
        real_data, "_fetch_gdacs_event_list",
        lambda t: calls.append(t) or {"features": [], "source": "GDACS"})
    real_data.fetch_active_cyclones.__wrapped__()
    real_data.fetch_gdacs_floods.__wrapped__()
    real_data.fetch_gdacs_volcanoes.__wrapped__()
    assert calls == ["TC", "FL", "VO"]


def test_gdacs_event_list_error_dict(monkeypatch):
    class _Boom:
        def read(self):
            raise OSError("edge down")

    monkeypatch.setattr(real_data.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("edge down")))
    out = real_data._fetch_gdacs_event_list("FL")
    assert "error" in out and "GDACS" in out["error"]


def test_flatten_gdacs_event_filters_type_and_computes_distance():
    f = _gdacs_feature("FL", lat=49.0, lon=6.0)
    rec = flatten_gdacs_event(f, 49.0, 6.0, "FL")
    assert rec is not None
    assert rec["distance_km"] == pytest.approx(0.0, abs=0.01)
    assert rec["alert_level"] == "Orange"
    assert rec["severity"]["unit"] == "m3/s"
    # wrong type → None; malformed geometry → None
    assert flatten_gdacs_event(f, 49.0, 6.0, "VO") is None
    assert flatten_gdacs_event({"properties": {"eventtype": "FL"}}, 49.0, 6.0, "FL") is None
    # distance is real (1° lon ≈ 73 km at 49°N)
    far = flatten_gdacs_event(f, 49.0, 7.0, "FL")
    assert 60.0 < far["distance_km"] < 90.0
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.5)


# ---------------------------------------------------------------------------
# Flood: GDACS events + GEOGLOWS second provider
# ---------------------------------------------------------------------------

def test_flood_events_via_gdacs(monkeypatch):
    monkeypatch.setattr(real_data, "fetch_gdacs_floods", lambda: _gdacs_feed("FL"))
    out = FloodModule().events(49.0, 6.0, radius_km=300)
    assert out["status"] == "ok"
    assert out["events"] and all(e["alert_level"] for e in out["events"])
    assert out["events"] == sorted(out["events"], key=lambda e: e["distance_km"])
    assert "monitoring context" in out["note"] or "monitoring" in out["note"]

    monkeypatch.setattr(real_data, "fetch_gdacs_floods",
                        lambda: {"error": "GDACS down"})
    out = FloodModule().events(49.0, 6.0)
    assert out["status"] == "unavailable" and out["events"] == []

    out = FloodModule().events(49.0, 6.0, year=2020)
    assert out["status"] == "unavailable"
    assert "not wired" in out["reason"] or "archive" in out["reason"]


def _geoglows_series(days=400):
    today = date.today()
    times = [(today - timedelta(days=days - i)).isoformat() for i in range(days)]
    values = [8.0] * (days - 2) + [300.0, 300.0]
    return {
        "time": times, "river_discharge": values, "units": "m³/s",
        "source": real_data.GEOGLOWS_SOURCE,
        "river_id": 230285584,
        "forecast": {"daily_median_m3s": [{"date": times[-1], "discharge_m3s": 12.0}],
                     "method": "fake"},
        "request_url": "https://geoglows.ecmwf.int/api/v2/getriverid?fake=1",
        "note": "Hydrological model output (GEOGLOWS/ECMWF), not gauge observations.",
    }


def _glofas_series(days=400):
    today = date.today()
    times = [(today - timedelta(days=days - i)).isoformat() for i in range(days)]
    discharge = [10.0] * (days - 3) + [500.0, 500.0, 500.0]
    return {
        "time": times, "river_discharge": discharge, "units": "m³/s",
        "source": "GloFAS river discharge (Copernicus EMS / EC JRC via Open-Meteo Flood API)",
        "request_url": "https://flood-api.open-meteo.com/v1/flood?fake=1",
        "note": "Hydrological model output (GloFAS), not gauge observations.",
    }


def _mount_flood(monkeypatch, geoglows=None):
    from src.dashboard import exposure
    from src.gis_mapping import landcover
    monkeypatch.setattr(real_data, "fetch_terrain",
                        lambda lat, lon: {"elevation_m": 200.0, "slope_degrees": 2.0,
                                          "dataset": "eudem25m", "resolution": "25 m",
                                          "source": "DEM (OpenTopoData eudem25m, 25 m)"})
    monkeypatch.setattr(exposure, "fetch_osm_context",
                        lambda lat, lon, r: {"counts": {"waterways": 1},
                                             "radius_m": r, "source": "OSM",
                                             "note": "fake"})
    monkeypatch.setattr(landcover, "fetch_landcover", lambda lat, lon: {"label": "x"})
    monkeypatch.setattr(real_data, "fetch_flood_discharge",
                        lambda lat, lon, start, end: _glofas_series())
    today = date.today()
    ptimes = [(today - timedelta(days=400 - i)).isoformat() for i in range(400)]
    monkeypatch.setattr(
        real_data, "fetch_daily_climate",
        lambda lat, lon, start, end, variables: {
            "time": ptimes, "precipitation_sum": [2.0] * 400, "units": {},
            "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
            "variables": list(variables),
            "request_url": "https://archive-api.open-meteo.com/v1/archive?fake=1",
        })
    monkeypatch.setattr(
        real_data, "fetch_geoglows_discharge",
        lambda lat, lon, start, end: geoglows if geoglows is not None else _geoglows_series())


def test_flood_analyze_includes_geoglows_second_provider(monkeypatch):
    _mount_flood(monkeypatch)
    result = FloodModule().analyze(49.75, 6.64, name="Trier")
    assert result.status == "ok"
    block = result.blocks["river_discharge_geoglows"]
    assert block["status"] == "ok"
    assert block["river_id"] == 230285584
    assert block["latest"]["discharge_m3s"] == 300.0
    assert block["percentile_of_latest"] == 100.0
    assert block["forecast"]["daily_median_m3s"]
    # Side-by-side comparison, never merged: both series reported, the
    # screening level stays GloFAS-based.
    assert block["glofas_comparison"]["aligned_days"] > 300
    assert "never silently merged" in block["glofas_comparison"]["note"]
    assert "GloFAS-based" in block["role"]
    assert result.level.label == "Very high"  # from the GloFAS percentile
    assert "river_discharge_geoglows" in result.provenance
    assert any(e.get("dataset", "").startswith("GEOGLOWS")
               for e in result.evidence)


def test_flood_analyze_geoglows_unavailable_does_not_break_core(monkeypatch):
    _mount_flood(monkeypatch, geoglows={"error": "GEOGLOWS down",
                                        "source": real_data.GEOGLOWS_SOURCE})
    result = FloodModule().analyze(49.75, 6.64)
    assert result.status == "ok"  # core GloFAS+precip path unaffected
    block = result.blocks["river_discharge_geoglows"]
    assert block["status"] == "unavailable"
    assert "GEOGLOWS down" in block["reason"]


def test_flood_geoglows_block_compares_only_when_both_ok():
    block = FloodModule()._geoglows_block(
        _geoglows_series(), {"error": "GloFAS down"}, date.today())
    assert block["status"] == "ok"
    assert block["glofas_comparison"] is None


# ---------------------------------------------------------------------------
# Volcanic: GDACS VO events live, analysis honestly unavailable
# ---------------------------------------------------------------------------

def test_volcanic_events_live_analysis_unavailable(monkeypatch):
    module = VolcanicModule()
    d = module.descriptor()
    assert d["analysis"]["available"] is False
    assert "GVP" in d["analysis"]["reason"]
    assert d["events"]["available"] is True

    monkeypatch.setattr(real_data, "fetch_gdacs_volcanoes", lambda: _gdacs_feed("VO"))
    out = module.events(49.0, 6.0, radius_km=3000)
    assert out["status"] == "ok"
    assert out["events"] and "volcanic" in out["coverage"]

    out = module.events(49.0, 6.0, year=2010)
    assert out["status"] == "unavailable" and "GVP" in out["reason"]

    result = module.analyze(37.0, 15.0)
    assert result.status == "unavailable" and result.unavailable_reason


def test_volcanic_map_layers_gdacs_available_gvp_unavailable():
    layers = {l["layer_id"]: l for l in VolcanicModule().map_layers()}
    assert layers["volcanic.gdacs_active"]["status"] == "available"
    assert layers["volcanic.gdacs_active"]["url"] == "https://www.gdacs.org/"
    assert layers["volcanic.gvp_events"]["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Wildfire: EONET second independent source
# ---------------------------------------------------------------------------

_EONET_FEED = {
    "events": [
        {"id": "EONET_1", "title": "Near fire", "lat": 49.2, "lon": 6.1,
         "date": "2026-08-30T00:00:00Z", "magnitude_value": 100.0,
         "magnitude_unit": "acres", "closed": None, "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_1"},
        {"id": "EONET_2", "title": "Far fire", "lat": -33.9, "lon": 151.2,
         "date": "2026-08-29T00:00:00Z", "magnitude_value": 500.0,
         "magnitude_unit": "acres", "closed": None, "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_2"},
    ],
    "source": real_data.EONET_SOURCE,
    "request_url": "https://eonet.gsfc.nasa.gov/api/v3/events?fake=1",
    "note": "Incident-report catalogue — reported separately, never merged.",
}


def test_eonet_flattening_uses_latest_geometry(monkeypatch):
    payload = {"events": [{
        "id": "EONET_X", "title": "Fire X", "closed": None,
        "link": "https://example.test/x",
        "geometry": [
            {"date": "2026-08-01T00:00:00Z", "type": "Point",
             "coordinates": [10.0, 50.0], "magnitudeValue": 10.0,
             "magnitudeUnit": "acres"},
            {"date": "2026-08-05T00:00:00Z", "type": "Point",
             "coordinates": [11.0, 51.0], "magnitudeValue": 99.0,
             "magnitudeUnit": "acres"},
        ],
    }]}
    monkeypatch.setattr(real_data, "_get_json", lambda url, timeout=15.0: payload)
    out = real_data.fetch_eonet_wildfires.__wrapped__()
    assert out["events"][0]["lat"] == 51.0 and out["events"][0]["lon"] == 11.0
    assert out["events"][0]["magnitude_value"] == 99.0
    assert out["events"][0]["date"] == "2026-08-05T00:00:00Z"


def test_wildfire_events_carry_separate_eonet_section(monkeypatch):
    base = {"hazard": "wildfire", "status": "key_required",
            "reason": "no key", "events": [{"firms": True}]}
    monkeypatch.setattr(
        "src.climate.fire_events.derive_fire_events",
        lambda **kw: dict(base))
    monkeypatch.setattr(real_data, "fetch_eonet_wildfires", lambda: dict(_EONET_FEED))

    out = WildfireModule().events(49.0, 6.0, radius_km=50.0)
    # FIRMS section untouched (never merged)
    assert out["status"] == "key_required"
    assert out["events"] == [{"firms": True}]
    # EONET section real and radius-filtered (the Sydney incident is out)
    eonet = out["eonet"]
    assert eonet["status"] == "ok"
    assert [e["id"] for e in eonet["events"]] == ["EONET_1"]
    assert eonet["events"][0]["name"] == "Near fire"
    assert "never merged" in eonet["note"]


def test_wildfire_events_eonet_unavailable_is_honest(monkeypatch):
    monkeypatch.setattr(
        "src.climate.fire_events.derive_fire_events",
        lambda **kw: {"hazard": "wildfire", "status": "ok", "events": []})
    monkeypatch.setattr(real_data, "fetch_eonet_wildfires",
                        lambda: {"error": "EONET down"})
    out = WildfireModule().events(49.0, 6.0)
    assert out["eonet"]["status"] == "unavailable"
    assert "EONET down" in out["eonet"]["reason"]


# ---------------------------------------------------------------------------
# GEOGLOWS fetcher (CSV parsing, window clipping, forecast, error paths)
# ---------------------------------------------------------------------------

def _mount_geoglows(monkeypatch):
    monkeypatch.setattr(
        real_data, "_get_json",
        lambda url, timeout=15.0: {"river_id": 230285584})
    retro = "time,230285584\n" + "\n".join(
        f"2026-08-{d:02d} 00:00:00+00:00,{d * 1.5}" for d in range(1, 29))
    forecast = ("datetime,flow_uncertainty_upper,flow_median,flow_uncertainty_lower\n"
                "2026-09-03T00:00:00+00:00,20.0,10.0,5.0\n"
                "2026-09-03T03:00:00+00:00,22.0,12.0,6.0\n"
                "2026-09-04T00:00:00+00:00,30.0,15.0,8.0\n")

    def _text(url, timeout=15.0):
        return retro if "retrospectivedaily" in url else forecast

    monkeypatch.setattr(real_data, "_get_text", _text)


def test_geoglows_discharge_happy_path(monkeypatch):
    _mount_geoglows(monkeypatch)
    out = real_data.fetch_geoglows_discharge.__wrapped__(
        49.61, 6.13, "2026-08-10", "2026-08-20")
    assert "error" not in out
    assert out["river_id"] == 230285584
    assert out["time"][0] == "2026-08-10" and out["time"][-1] == "2026-08-20"
    assert len(out["time"]) == 11
    assert out["river_discharge"][0] == pytest.approx(15.0)
    medians = out["forecast"]["daily_median_m3s"]
    assert medians[0]["date"] == "2026-09-03"
    assert medians[0]["discharge_m3s"] == pytest.approx(11.0)  # mean(10, 12)
    assert "never merged" in out["note"]


def test_geoglows_discharge_error_paths(monkeypatch):
    assert "error" in real_data.fetch_geoglows_discharge.__wrapped__(
        95.0, 6.13, "2026-08-10", "2026-08-20")  # out of range
    assert "error" in real_data.fetch_geoglows_discharge.__wrapped__(
        49.61, 6.13, "2026-08-20", "2026-08-10")  # bad range

    monkeypatch.setattr(
        real_data, "_get_json",
        lambda url, timeout=15.0: {"error": "no reach"})
    out = real_data.fetch_geoglows_discharge.__wrapped__(
        49.61, 6.13, "2026-08-10", "2026-08-20")
    assert "error" in out and "river reach" in out["error"]

    _mount_geoglows(monkeypatch)
    out = real_data.fetch_geoglows_discharge.__wrapped__(
        49.61, 6.13, "2026-09-10", "2026-09-20")  # outside the fake series
    assert "error" in out and "no retrospective discharge" in out["error"]


# ---------------------------------------------------------------------------
# Chain + registry contracts after the wiring
# ---------------------------------------------------------------------------

def test_discharge_chain_gap_closed_soil_moisture_gap_declared():
    discharge = ingestion.PROVIDER_CHAINS["discharge"]
    assert discharge.providers == ["glofas-openmeteo", "geoglows"]
    assert discharge.single_provider_gap is False
    assert "never merged" in discharge.comparison_note
    gaps = {n for n, c in ingestion.PROVIDER_CHAINS.items()
            if c.single_provider_gap}
    assert gaps == {"soil_moisture"}
    assert "SINGLE-PROVIDER GAP" in \
        ingestion.PROVIDER_CHAINS["soil_moisture"].comparison_note


def test_registry_wired_sources_integrated_with_profiles():
    for did in ("gdacs-events", "nasa-eonet", "geoglows"):
        entry = data_registry.get(did)
        assert entry is not None, did
        assert entry["status"] == "integrated", did
        profile = entry.get("data_quality_profile")
        assert profile and all(profile[k] for k in (
            "freshness", "completeness", "spatial_resolution_note",
            "temporal_resolution_note", "provenance_note", "validation",
            "coverage_note", "licensing_note")), did
        assert "2026-09-03" in entry["status_note"]


def test_nasa_eonet_catalogued_as_hazard_disaster():
    entry = data_registry.get("nasa-eonet")
    assert entry["catalog_group"] == "hazard_disaster"
    assert entry["access_method"] == "api"
    assert entry["commercial_use"] == "allowed"

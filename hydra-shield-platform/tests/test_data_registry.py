"""
Offline tests for the Data Observatory (data registry), the uncertainty
envelope, and the multi-provider ingestion layer.

Everything here runs without network access: the registry is a config
file, the API endpoints read config, and the validators are pure.
"""

import json
import os
import re

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_datareg_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402
from src.climate import data_registry, ingestion, uncertainty  # noqa: E402

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "data_registry.json"
)

_HTTPS_RE = re.compile(r"^https://[a-z0-9.-]+\.[a-z]{2,}(/|$)", re.IGNORECASE)

#: Authoritative global entries added on top of the transformed sources —
#: all must be present as catalog records with status "candidate".
_NEW_CANDIDATE_IDS = (
    "noaa-ncei", "noaa-cdo", "usgs-water", "usgs-earthquake",
    "nasa-earthdata", "ecmwf-opencharts", "eea-discomap",
    "copernicus-cds-ads", "cems-efas", "cma-data", "cma-nmic", "jma",
    "kma", "bom", "imd", "worldbank-cckp", "ocha-hdx", "wmo-oscar",
    "metoffice", "dwd", "meteofrance", "fao-giews", "reliefweb",
)

#: Ids the transformed source_registry entries must have produced (the two
#: dual-dataset entries were split per dataset+access path).
_TRANSFORMED_IDS = (
    "sentinel2-l2a", "open-meteo-forecast", "era5-archive",
    "opentopodata-eudem", "srtm", "esa-worldcover", "firms-viirs",
    "firms-modis", "worldpop", "ghsl", "gpw-v4", "eurostat-geostat",
    "cams", "noaa-hysplit", "blitzortung", "ohsome", "overpass",
    "nominatim", "effis-gwis", "cdse", "sentinel-1", "sentinel-3-slstr",
    "sentinel-5p", "clms-burnt-area", "modis-mcd64a1", "gfw-fires",
    "fy-satellites", "tpdc", "copernicus-dem", "glofas-openmeteo",
    "open-meteo-marine", "era5-land",
)


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Registry loads + schema validation
# ---------------------------------------------------------------------------

def test_registry_loads_and_validates():
    entries = data_registry.all()
    assert len(entries) >= 40


def test_registry_raw_file_schema():
    with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    ids = set()
    for entry in doc["datasets"]:
        for field in data_registry.REQUIRED_FIELDS:
            assert field in entry, f"{entry.get('id')}: missing {field}"
        assert entry["id"] not in ids, f"duplicate id {entry['id']}"
        ids.add(entry["id"])
        assert _HTTPS_RE.match(entry["url"]), \
            f"{entry['id']}: not an https URL: {entry['url']}"
        assert entry["status"] in data_registry.VALID_STATUSES
        assert entry["provider_class"] in data_registry.VALID_PROVIDER_CLASSES
        assert entry["access_method"] in data_registry.VALID_ACCESS_METHODS
        assert entry["commercial_use"] in data_registry.VALID_COMMERCIAL_USE
        assert isinstance(entry["variables"], list)
        assert isinstance(entry["hazard_relevance"], list)


def test_registry_status_counts():
    s = data_registry.summary()
    assert s["by_status"]["integrated"] > 0
    assert s["by_status"]["candidate"] > 0
    assert s["by_status"]["rejected"] > 0
    assert s["total"] == sum(s["by_status"].values())


def test_new_global_candidates_present_as_candidates():
    for cid in _NEW_CANDIDATE_IDS:
        entry = data_registry.get(cid)
        assert entry is not None, f"missing candidate '{cid}'"
        assert entry["status"] == "candidate", \
            f"{cid}: expected candidate, got {entry['status']}"


def test_transformed_sources_present_with_statuses():
    for tid in _TRANSFORMED_IDS:
        assert data_registry.get(tid) is not None, f"missing '{tid}'"
    # statuses carried over from the source audit
    assert data_registry.get("open-meteo-forecast")["status"] == "integrated"
    assert data_registry.get("ghsl")["status"] == "candidate"
    assert data_registry.get("blitzortung")["status"] == "rejected"
    assert data_registry.get("tpdc")["status"] == "rejected"


def test_reliefweb_labelled_documented_events_only():
    entry = data_registry.get("reliefweb")
    blob = (entry["quality"] + entry["status_note"]).lower()
    assert "never scientific evidence" in blob
    assert "documented" in blob


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def test_query_helpers():
    assert data_registry.get("no-such-dataset") is None
    integrated = data_registry.by_status("integrated")
    assert integrated and all(e["status"] == "integrated" for e in integrated)
    wildfire = data_registry.by_hazard("wildfire")
    assert wildfire
    assert all("wildfire" in e["hazard_relevance"] for e in wildfire)
    assert data_registry.get("firms-viirs") in wildfire
    s = data_registry.summary()
    assert set(s) == {"total", "by_status", "by_provider_class", "by_region"}
    assert s["by_provider_class"]


def test_malformed_registry_fails_loud(tmp_path, monkeypatch):
    bad = tmp_path / "bad_registry.json"
    bad.write_text(json.dumps({"datasets": [
        {"id": "broken", "url": "http://insecure.example.com/"}
    ]}))
    monkeypatch.setattr(data_registry, "_REGISTRY_PATH", str(bad))
    data_registry.reset_for_tests()
    with pytest.raises(data_registry.RegistryError):
        data_registry.all()
    monkeypatch.undo()
    data_registry.reset_for_tests()
    assert data_registry.all()  # real registry loads again


# ---------------------------------------------------------------------------
# API: /api/v2/registry (+filters, 404)
# ---------------------------------------------------------------------------

def test_api_registry_list(client):
    resp = client.get("/api/v2/registry")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == len(body["datasets"]) >= 40
    assert "observatory_note" in body
    assert "status=integrated" in body["observatory_note"]
    for entry in body["datasets"]:
        assert entry["status"] in {"integrated", "candidate", "rejected"}


def test_api_registry_filters(client):
    resp = client.get("/api/v2/registry?status=candidate")
    assert resp.status_code == 200
    assert all(e["status"] == "candidate" for e in resp.get_json()["datasets"])

    resp = client.get("/api/v2/registry?hazard=flood")
    assert resp.status_code == 200
    datasets = resp.get_json()["datasets"]
    assert datasets
    assert all("flood" in e["hazard_relevance"] for e in datasets)

    resp = client.get("/api/v2/registry?provider_class=un_agency")
    assert resp.status_code == 200
    datasets = resp.get_json()["datasets"]
    assert datasets
    assert all(e["provider_class"] == "un_agency" for e in datasets)

    resp = client.get("/api/v2/registry?status=nonsense")
    assert resp.status_code == 400
    resp = client.get("/api/v2/registry?provider_class=nonsense")
    assert resp.status_code == 400


def test_api_registry_entry_and_404(client):
    resp = client.get("/api/v2/registry/usgs-water")
    assert resp.status_code == 200
    assert resp.get_json()["dataset"]["id"] == "usgs-water"
    resp = client.get("/api/v2/registry/no-such-dataset")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# API: /api/v2/models and /api/v2/research (seeded registries)
# ---------------------------------------------------------------------------

def test_api_models(client):
    resp = client.get("/api/v2/models")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert any(m["id"] == "fwi_system_v1" for m in models)

    resp = client.get("/api/v2/models/fwi_system_v1")
    assert resp.status_code == 200
    assert resp.get_json()["validation"]["status"] in \
        data_registry.VALID_MODEL_STATUSES

    resp = client.get("/api/v2/models/no-such-model")
    assert resp.status_code == 404


def test_api_research(client):
    resp = client.get("/api/v2/research")
    assert resp.status_code == 200
    refs = resp.get_json()["references"]
    ids = {r["id"] for r in refs}
    assert {"vanwagner1987", "zscheischler2020typology"} <= ids

    resp = client.get("/api/v2/research/zscheischler2020typology")
    assert resp.status_code == 200
    assert resp.get_json()["pipeline_stage"]

    resp = client.get("/api/v2/research?topic=wildfire")
    assert resp.status_code == 200
    for ref in resp.get_json()["references"]:
        assert "wildfire" in [t.lower() for t in ref["topics"]]

    resp = client.get("/api/v2/research?pipeline_stage=production")
    assert resp.status_code == 200
    refs = resp.get_json()["references"]
    assert refs
    assert all(r["pipeline_stage"] == "production" for r in refs)

    resp = client.get("/api/v2/research/no-such-ref")
    assert resp.status_code == 404


def test_offline_model_and_research_loaders():
    assert data_registry.models_get("fwi_system_v1") is not None
    assert data_registry.models_get("nope") is None
    assert data_registry.research_get("vanwagner1987") is not None
    assert data_registry.research_get("nope") is None
    assert len(data_registry.models_all()) >= 10
    assert len(data_registry.research_all()) >= 10


# ---------------------------------------------------------------------------
# Uncertainty envelope
# ---------------------------------------------------------------------------

def test_analytical_result_statuses():
    obs = uncertainty.AnalyticalResult.observed(12.5, source="USGS gauge")
    assert obs.to_dict()["status"] == "observed"
    der = uncertainty.AnalyticalResult.derived(
        3.2, source="ERA5", method="7-day anomaly vs climatology")
    assert der.to_dict()["status"] == "derived"
    mod = uncertainty.AnalyticalResult.modelled(
        42.0, source="GloFAS", method="Lisflood ensemble median")
    assert mod.to_dict()["status"] == "modelled"
    proj = uncertainty.AnalyticalResult.projected(
        1.8, source="CMIP6", method="SSP2-4.5 multi-model mean")
    d = proj.to_dict()
    assert d["status"] == "projected"
    assert d["confidence"] == "low"


def test_analytical_result_unavailable_carries_reason():
    res = uncertainty.AnalyticalResult.unavailable(
        "FIRMS key not configured", source="NASA FIRMS")
    d = res.to_dict()
    assert d["status"] == "unavailable"
    assert d["value"] is None
    assert d["unavailable_reason"] == "FIRMS key not configured"


def test_analytical_result_rejects_bad_vocabulary():
    with pytest.raises(ValueError):
        uncertainty.AnalyticalResult(1.0, "guessed")
    with pytest.raises(ValueError):
        uncertainty.AnalyticalResult(1.0, "observed", confidence="very-high")
    with pytest.raises(ValueError):
        uncertainty.AnalyticalResult.unavailable("")


def test_wrap_series():
    out = uncertainty.wrap_series(
        [{"date": "2024-01-01", "value": 1.0},
         {"date": "2024-01-02", "value": None}],
        status="modelled", source="ERA5-Land", method="reanalysis aggregate")
    assert out["point_count"] == 2
    assert out["null_count"] == 1
    assert out["status"] == "modelled"
    with pytest.raises(ValueError):
        uncertainty.wrap_series([], status="observed")  # no source declared
    with pytest.raises(ValueError):
        uncertainty.wrap_series(
            [{"date": "2024-01-01", "value": 1.0}],
            status="modelled", source="x")  # modelled requires method


# ---------------------------------------------------------------------------
# Ingestion validators
# ---------------------------------------------------------------------------

def _series(*pairs):
    return [{"date": d, "value": v} for d, v in pairs]


def test_validate_series_clean():
    out = ingestion.validate_series(_series(
        ("2024-01-01", 1.0), ("2024-01-02", 2.0), ("2024-01-03", 3.0)))
    assert out["ok"]
    assert out["issues"] == []
    assert out["coverage"]["span_days"] == 3
    assert out["coverage"]["null_ratio"] == 0


def test_validate_series_gap():
    out = ingestion.validate_series(_series(
        ("2024-01-01", 1.0), ("2024-01-04", 2.0)))
    assert out["ok"]  # a gap is a warning, not an error
    assert any(i["type"] == "gap" for i in out["issues"])


def test_validate_series_duplicates_and_order():
    out = ingestion.validate_series(_series(
        ("2024-01-01", 1.0), ("2024-01-01", 2.0)))
    assert not out["ok"]
    assert any(i["type"] == "duplicate_date" for i in out["issues"])

    out = ingestion.validate_series(_series(
        ("2024-01-03", 1.0), ("2024-01-02", 2.0)))
    assert not out["ok"]
    assert any(i["type"] == "non_monotonic" for i in out["issues"])


def test_validate_series_nulls_and_bad_dates():
    out = ingestion.validate_series(_series(
        ("2024-01-01", None), ("2024-01-02", 2.0)))
    assert out["ok"]
    assert out["coverage"]["null_ratio"] == 0.5
    assert any(i["type"] == "null_values" for i in out["issues"])

    out = ingestion.validate_series(_series(("not-a-date", 1.0)))
    assert not out["ok"]
    assert any(i["type"] == "invalid_date" for i in out["issues"])

    assert not ingestion.validate_series([])["ok"]


def test_validate_spatial():
    assert ingestion.validate_spatial(40.1, 6.2)["ok"]
    assert not ingestion.validate_spatial(95.0, 6.2)["ok"]
    assert not ingestion.validate_spatial(40.1, 200.0)["ok"]
    assert not ingestion.validate_spatial("abc", 6.2)["ok"]
    bbox = (40.0, 5.0, 41.0, 7.0)
    assert ingestion.validate_spatial(40.5, 6.0, bbox)["ok"]
    out = ingestion.validate_spatial(39.0, 6.0, bbox)
    assert not out["ok"]
    assert any(i["type"] == "outside_bbox" for i in out["issues"])


def test_compare_sources():
    out = ingestion.compare_sources([1.0, 2.0, 3.0], [1.1, 2.1, 3.1], 0.5)
    assert out["ok"] and out["disagreement"] is False
    assert out["mean_abs_delta"] == pytest.approx(0.1)
    assert "never merged" in out["note"]

    out = ingestion.compare_sources([1.0, 2.0], [1.0, 9.0], 0.5)
    assert out["disagreement"] is True
    assert out["max_delta"] == pytest.approx(7.0)

    # nulls are skipped, not treated as zero
    out = ingestion.compare_sources([1.0, None], [1.0, 5.0], 0.1)
    assert out["compared"] == 1
    assert out["disagreement"] is False

    out = ingestion.compare_sources([1.0], [1.0, 2.0], 0.1)
    assert not out["ok"]
    assert out["disagreement"] is None

    with pytest.raises(ValueError):
        ingestion.compare_sources([1.0], [1.0], -0.1)


def test_quality_score_heuristic():
    clean = ingestion.validate_series(_series(("2024-01-01", 1.0)))
    gappy = ingestion.validate_series(_series(
        ("2024-01-01", 1.0), ("2024-01-05", 2.0)))
    broken = ingestion.validate_series(_series(("bad", 1.0)))
    spatial_ok = ingestion.validate_spatial(40.0, 6.0)
    assert ingestion.quality_score({"s": clean, "p": spatial_ok}) == "high"
    assert ingestion.quality_score({"s": gappy, "p": spatial_ok}) == "medium"
    assert ingestion.quality_score({"s": broken, "p": spatial_ok}) == "low"


# ---------------------------------------------------------------------------
# Provider chains
# ---------------------------------------------------------------------------

def test_chains_reference_existing_registry_ids():
    for name, chain in ingestion.PROVIDER_CHAINS.items():
        assert chain.primary in chain.providers
        for pid in chain.providers:
            entry = data_registry.get(pid)
            assert entry is not None, \
                f"chain '{name}': unknown registry id '{pid}'"


def test_chains_declared_gaps():
    gaps = {n for n, c in ingestion.PROVIDER_CHAINS.items()
            if c.single_provider_gap}
    assert gaps == {"discharge", "soil_moisture"}
    for name in gaps:
        assert "SINGLE-PROVIDER GAP" in \
            ingestion.PROVIDER_CHAINS[name].comparison_note
    # fires chain: VIIRS and MODIS reported per sensor, never merged
    fires = ingestion.PROVIDER_CHAINS["fires"]
    assert set(fires.providers) == {"firms-viirs", "firms-modis"}
    assert "never merged" in fires.comparison_note


def test_api_ingestion_chains(client):
    resp = client.get("/api/v2/ingestion/chains")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["single_provider_gaps"]) == {"discharge", "soil_moisture"}
    chains = body["chains"]
    assert chains["weather_daily"]["primary"] == "open-meteo-forecast"
    assert chains["weather_daily"]["fallbacks"] == ["era5-archive"]
    assert chains["exposure"]["fallbacks"] == ["overpass"]
    assert chains["discharge"]["single_provider_gap"] is True

"""Tests for the Environmental Licensing Advisory feature.

Fully offline: hazard modules and all data fetchers are stubbed via
monkeypatch + registry reset, so no network calls are made.
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_licensing_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import licensing as licensing_module  # noqa: E402
from src.climate import registry  # noqa: E402
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Drop the cached registry before/after each test."""
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture(autouse=True)
def _stub_fetchers(monkeypatch):
    """Offline guarantee: every data fetcher the engine calls is stubbed."""
    monkeypatch.setattr(
        "src.gis_mapping.landcover.fetch_landcover",
        lambda lat, lon: {
            "dominant_label": "Tree cover",
            "dominant_fraction": 0.62,
            "histogram": {},
            "source": "ESA WorldCover",
            "resolution": "10 m",
        },
    )
    monkeypatch.setattr(
        "src.dashboard.real_data.fetch_satellite_data",
        lambda lat, lon, days_back=60: {
            "ndvi": 0.58,
            "ndmi": 0.21,
            "observation_date": "2026-08-15",
            "source": "Sentinel-2 L2A",
            "resolution_m": 10,
        },
    )
    monkeypatch.setattr(
        "src.dashboard.real_data.fetch_active_fires",
        lambda lat, lon, radius_km=50.0, days=5: {
            "count": 3,
            "radius_km": radius_km,
            "days": days,
            "sensor": "VIIRS",
        },
    )
    monkeypatch.setattr(
        "src.dashboard.real_data.geocode_location",
        lambda query: {
            "name": "Stubbed Place",
            "lat": 40.0,
            "lon": -3.0,
            "source": "Nominatim (OpenStreetMap)",
        },
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated rate limiter per test."""
    import src.dashboard.api as api_module

    api_module._rate_limiter._hits.clear()
    return {}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# -----------------------------------------------------------------------------
# Stub hazard modules
# -----------------------------------------------------------------------------


class _FakeOkModule:
    def __init__(self, hazard_id: str, label: str = "High"):
        self.id = hazard_id
        self._label = label

    def availability(self):
        return True, None

    def events_availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="ok",
            summary=f"{self.id} screening ok",
            level=HazardLevel(
                label=self._label,
                score=0.8,
                score_max=1.0,
                basis="modelled screening indicator",
                validated=False,
            ),
            evidence=[{
                "evidence_class": "MODELLED",
                "claim_status": "MODELLED",
                "source": "Fake source",
                "dataset": "Fake dataset",
            }],
            provenance={"model": {"source": "Fake"}},
        )

    def events(self, lat, lon, radius_km=50.0, year=None, **kw):
        return {
            "hazard": self.id,
            "status": "ok",
            "events": [{"id": f"{self.id}-1", "title": "Stubbed event"}],
        }


class _FakeBoomModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def events_availability(self):
        return False, "No events layer"

    def analyze(self, lat, lon, name=None):
        raise ValueError("boom")


class _FakeUnavailableModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return False, "No real data for this hazard"

    def events_availability(self):
        return False, "No events layer"

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="unavailable",
            summary=f"{self.id} unavailable",
            unavailable_reason="No real data for this hazard",
        )


def _stub_registry(monkeypatch, ok=("flood",), boom=(), unavailable=()):
    def fake_get(hazard_id: str):
        if hazard_id in ok:
            return _FakeOkModule(hazard_id)
        if hazard_id in boom:
            return _FakeBoomModule(hazard_id)
        if hazard_id in unavailable:
            return _FakeUnavailableModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


# -----------------------------------------------------------------------------
# Engine tests
# -----------------------------------------------------------------------------


def test_dossier_happy_path(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "wildfire"))
    dossier = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, name="Test Site",
        side="authority", typology="solar_pv", permit_type="eia_screening",
        project_title="Helios 50 MW", jurisdiction="Almería, ES",
    )
    assert "error" not in dossier
    assert dossier["dossier_id"]
    assert dossier["engine_version"] == licensing_module.ENGINE_VERSION
    assert dossier["site"]["name"] == "Test Site"
    assert dossier["request"]["side"] == "authority"
    assert dossier["request"]["typology"] == "solar_pv"
    assert dossier["request"]["project_title"] == "Helios 50 MW"
    assert dossier["request"]["jurisdiction"] == "Almería, ES"

    base = dossier["evidence_base"]
    assert base["landcover"]["evidence_label"] == "DOCUMENTED"
    assert base["satellite"]["evidence_label"] == "OBSERVED"
    assert base["historical_events"]["evidence_label"] == "REPORTED"

    checks = {c["hazard"]: c for c in base["hazard_exposure"]}
    assert checks["flood"]["evidence_label"] == "MODELLED"
    assert checks["flood"]["level"]["label"] == "High"
    # Unregistered hazards are declared UNKNOWN, never dropped.
    assert checks["heat"]["evidence_label"] == "UNKNOWN"
    assert "not registered" in checks["heat"]["reason"]

    assert dossier["disclaimer"] == licensing_module.DISCLAIMER
    assert dossier["honesty_contract"] == licensing_module.HONESTY_CONTRACT


def test_dossier_inferred_constraints(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "wildfire"))
    dossier = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, name="Test Site")
    ids = {c["id"] for c in dossier["constraints"]}
    # High flood/wildfire levels, tree-cover dominance and 3 fire detections
    # each derive a transparent INFERRED flag.
    assert "elevated_flood_exposure" in ids
    assert "elevated_wildfire_exposure" in ids
    assert "vegetation_clearance_likely" in ids
    assert "recent_fire_activity" in ids
    for c in dossier["constraints"]:
        assert c["evidence_label"] == "INFERRED"
        assert c["basis"]
        assert c["derived_from"]


def test_dossier_declared_gaps(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",), boom=("wind",),
                   unavailable=("heat",))
    dossier = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, name="Test Site")
    checks = {c["hazard"]: c for c in dossier["evidence_base"]["hazard_exposure"]}
    assert checks["wind"]["evidence_label"] == "UNKNOWN"
    assert "boom" in checks["wind"]["reason"]
    assert checks["heat"]["evidence_label"] == "UNKNOWN"

    gap_layers = {g["layer"] for g in dossier["declared_gaps"]}
    assert "hazard_exposure:wind" in gap_layers
    assert "hazard_exposure:heat" in gap_layers
    assert "historical_events:wind" in gap_layers
    assert dossier["summary"]


def test_dossier_layer_failure_is_a_gap(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    monkeypatch.setattr(
        "src.gis_mapping.landcover.fetch_landcover",
        lambda lat, lon: {"error": "service down"},
    )
    dossier = licensing_module.build_licensing_dossier(lat=1.0, lon=2.0)
    lc = dossier["evidence_base"]["landcover"]
    assert lc["evidence_label"] == "UNKNOWN"
    assert any(g["layer"] == "landcover" for g in dossier["declared_gaps"])
    # No vegetation constraint without land-cover evidence.
    assert "vegetation_clearance_likely" not in {
        c["id"] for c in dossier["constraints"]}


def test_dossier_invalid_requests():
    bad_radius = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, radius_km=500)
    assert "error" in bad_radius

    no_site = licensing_module.build_licensing_dossier(site=None)
    assert "error" in no_site

    bad_site = licensing_module.build_licensing_dossier(
        site={"lat": 95, "lon": 2})
    assert "error" in bad_site


def test_dossier_address_resolution(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    dossier = licensing_module.build_licensing_dossier(
        site={"address": "Somewhere in Spain"})
    assert "error" not in dossier
    assert dossier["site"]["lat"] == 40.0
    assert dossier["site"]["lon"] == -3.0
    assert dossier["site"]["name"] == "Stubbed Place"


def test_dossier_id_deterministic(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    a = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, typology="wind")
    b = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, typology="wind")
    c = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, typology="solar_pv")
    assert a["dossier_id"] == b["dossier_id"]
    assert a["dossier_id"] != c["dossier_id"]


def test_dossier_hazard_subset(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "wildfire"))
    dossier = licensing_module.build_licensing_dossier(
        lat=1.0, lon=2.0, hazards=["flood"])
    checks = dossier["evidence_base"]["hazard_exposure"]
    assert [c["hazard"] for c in checks] == ["flood"]


# -----------------------------------------------------------------------------
# API tests
# -----------------------------------------------------------------------------


def test_frameworks_endpoint(client):
    resp = client.get("/api/v2/licensing/frameworks")
    assert resp.status_code == 200
    data = resp.get_json()
    side_ids = {s["id"] for s in data["applicant_sides"]}
    assert side_ids == {"applicant", "authority"}
    typ_ids = {t["id"] for t in data["typologies"]}
    assert "solar_pv" in typ_ids and "other" in typ_ids
    permit_ids = {p["id"] for p in data["permit_types"]}
    assert "eia_screening" in permit_ids
    hazard_ids = {h["id"] for h in data["hazards"]}
    assert "wildfire" in hazard_ids and "coastal" in hazard_ids
    assert data["frameworks"]
    assert data["disclaimer"]
    assert data["honesty_contract"]


def test_dossier_endpoint_requires_body(client):
    resp = client.post("/api/v2/licensing/dossier")
    assert resp.status_code == 400


def test_dossier_endpoint_requires_site(client):
    resp = client.post("/api/v2/licensing/dossier", json={"radius_km": 25})
    assert resp.status_code == 400
    assert "site" in resp.get_json()["error"]


def test_dossier_endpoint_rejects_bad_radius(client):
    resp = client.post(
        "/api/v2/licensing/dossier",
        json={"site": {"lat": 1, "lon": 2}, "radius_km": 0},
    )
    assert resp.status_code == 400


def test_dossier_endpoint_success(client, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "wildfire"))
    resp = client.post(
        "/api/v2/licensing/dossier",
        json={
            "site": {"lat": 1.0, "lon": 2.0, "name": "Test Site"},
            "radius_km": 25,
            "side": "applicant",
            "typology": "solar_pv",
            "permit_type": "construction_permit",
            "project_title": "Helios 50 MW",
            "description": "Ground-mounted solar plant.",
            "jurisdiction": "Almería, ES",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["dossier_id"]
    assert data["request"]["typology"] == "solar_pv"
    assert data["request"]["permit_type"] == "construction_permit"
    assert data["evidence_base"]["hazard_exposure"]
    assert data["frameworks"]
    assert data["disclaimer"]


def test_dossier_endpoint_address_site(client, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    resp = client.post(
        "/api/v2/licensing/dossier",
        json={"site": {"address": "Almería, Spain"}},
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["site"]["lat"] == 40.0


# -----------------------------------------------------------------------------
# TX adapter tests (licensing as a TX-2 product)
# -----------------------------------------------------------------------------


def test_licensing_registered_as_tx_product():
    from tx_core.adapters import products as product_adapters

    assert "licensing" in product_adapters.product_ids()
    module = product_adapters.get_product_module("licensing")
    assert module is not None
    descriptor = module.descriptor()
    assert descriptor["id"] == "licensing"
    assert descriptor["kind"] == "product"
    assert descriptor["tx_level"] == 2
    assert descriptor["engine_version"] == licensing_module.ENGINE_VERSION


def test_licensing_tx_product_analyze(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "wildfire"))
    from tx_core.adapters import products as product_adapters

    module = product_adapters.get_product_module("licensing")
    result = module.analyze(lat=1.0, lon=2.0, name="Test Site")
    assert result.hazard == "licensing"
    assert result.status == "partial"  # unregistered hazards are unavailable
    assert "screened" in result.summary
    assert result.blocks["dossier_id"]
    assert result.blocks["evidence_base"]["hazard_exposure"]
    assert result.provenance["engine"] == "licensing"


def test_licensing_tx_product_unavailable_when_nothing_assessed(monkeypatch):
    _stub_registry(monkeypatch, ok=())
    from tx_core.adapters import products as product_adapters

    module = product_adapters.get_product_module("licensing")
    result = module.analyze(lat=1.0, lon=2.0)
    assert result.status == "unavailable"
    assert result.unavailable_reason

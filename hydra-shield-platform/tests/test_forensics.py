"""Tests for the Environmental Security & Forensic Verification feature.

Fully offline: land-cover, Sentinel-2 and active-fire fetchers are monkeypatched.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_forensics_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "forensics.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path, "outbox": tmp_path / "outbox"}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# -----------------------------------------------------------------------------
# Fetcher stubs
# -----------------------------------------------------------------------------


def _landcover_tree(lat, lon, window_m=500.0):
    return {
        "dominant_class": 10,
        "dominant_label": "Tree cover",
        "dominant_fraction": 0.82,
        "source": "ESA WorldCover 10m 2021 v200",
        "resolution": "10 m",
    }


def _landcover_crop(lat, lon, window_m=500.0):
    return {
        "dominant_class": 40,
        "dominant_label": "Cropland",
        "dominant_fraction": 0.75,
        "source": "ESA WorldCover 10m 2021 v200",
        "resolution": "10 m",
    }


def _landcover_error(lat, lon, window_m=500.0):
    return {"error": "WorldCover read failed", "source": "ESA WorldCover 10m 2021 v200"}


def _satellite_ndvi(value):
    def _fetch(lat, lon, days_back=30):
        if value is None:
            return {"error": "No recent cloud-free Sentinel-2 scene available", "source": "Sentinel-2 L2A"}
        return {
            "ndvi": value,
            "ndmi": 0.1,
            "ndwi": -0.05,
            "observation_date": "2024-06-15T00:00:00",
            "source": "Satellite observation (Earth Search STAC)",
            "resolution_m": 10,
        }
    return _fetch


def _fires(count):
    def _fetch(lat, lon, radius_km=50.0, days=5):
        if count is None:
            return {
                "error": "NASA FIRMS API key not configured",
                "available": False,
                "count": 0,
                "fires": [],
                "days": days,
                "radius_km": radius_km,
                "sensor": "VIIRS_SNPP_NRT",
                "source": "NASA FIRMS VIIRS SNPP NRT",
            }
        return {
            "available": True,
            "count": count,
            "fires": [{"acq_date": "2024-06-14"} for _ in range(count)],
            "days": days,
            "radius_km": radius_km,
            "sensor": "VIIRS_SNPP_NRT",
            "source": "NASA FIRMS VIIRS SNPP NRT",
            "resolution": "375 m",
        }
    return _fetch


@pytest.fixture()
def stub_tree_no_fires_high_ndvi(monkeypatch):
    import src.climate.forensics as forensics

    monkeypatch.setattr(forensics, "fetch_landcover", _landcover_tree)
    monkeypatch.setattr(forensics, "fetch_satellite_data", _satellite_ndvi(0.7))
    monkeypatch.setattr(forensics, "fetch_active_fires", _fires(0))


@pytest.fixture()
def stub_crop_three_fires_low_ndvi(monkeypatch):
    import src.climate.forensics as forensics

    monkeypatch.setattr(forensics, "fetch_landcover", _landcover_crop)
    monkeypatch.setattr(forensics, "fetch_satellite_data", _satellite_ndvi(0.1))
    monkeypatch.setattr(forensics, "fetch_active_fires", _fires(3))


@pytest.fixture()
def stub_unavailable(monkeypatch):
    import src.climate.forensics as forensics

    monkeypatch.setattr(forensics, "fetch_landcover", _landcover_error)
    monkeypatch.setattr(forensics, "fetch_satellite_data", _satellite_ndvi(None))
    monkeypatch.setattr(forensics, "fetch_active_fires", _fires(None))


# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------


def _register(client, email="user@example.org", password="correct horse battery"):
    resp = client.post(
        "/api/v2/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Test User",
            "consent": True,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    return resp


def _verification_token(outbox_dir):
    import email as email_lib
    import re

    files = sorted(outbox_dir.glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    raw = files[-1].read_text(encoding="utf-8")
    msg = email_lib.message_from_string(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                break
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, "no verification token in email"
    return match.group(1)


def _register_and_verify(client, env, email="user@example.org", password="correct horse battery"):
    _register(client, email, password)
    token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return body["user"], body["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------------
# Endpoint tests
# -----------------------------------------------------------------------------


def test_frameworks_public(client):
    resp = client.get("/api/v2/forensics/frameworks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "typologies" in data
    assert "claim_types" in data
    assert "frameworks" in data
    assert data["legal_note"]
    assert data["disclaimer"]
    assert any(t["id"] == "illegal_logging" for t in data["typologies"])
    assert any(c["id"] == "site_forested" for c in data["claim_types"])


def test_cases_requires_auth(client):
    resp = client.post("/api/v2/forensics/cases", json={"typology": "illegal_logging"})
    assert resp.status_code in (401, 403)


def _case_payload(claim_type="site_forested"):
    return {
        "title": "Test case",
        "typology": "illegal_logging",
        "site": {"lat": -12.3, "lon": -55.4},
        "subject_claim": {"type": claim_type, "text": "Site is intact forest"},
        "radius_km": 25,
    }


def test_site_forested_consistent(client, env, stub_tree_no_fires_high_ndvi):
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("site_forested"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["case_id"]
    check = data["checks"][0]
    assert check["check"] == "site_forested"
    assert check["result"] == "consistent"
    assert data["case_verdict"] == "no_inconsistency_detected_with_current_evidence"
    assert data["declared_gaps_count"] >= 1

    record = client.get(f"/api/v2/forensics/cases/{data['case_id']}", headers=_auth(token)).get_json()
    assert record["case_id"] == data["case_id"]
    assert record["user_id"] == user["id"]


def test_site_forested_inconsistent(client, env, stub_crop_three_fires_low_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("site_forested"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "inconsistent"
    assert data["case_verdict"] == "inconsistencies_found"


def test_site_forested_cannot_assess(client, env, stub_unavailable):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("site_forested"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "cannot_assess"
    assert data["case_verdict"] == "partially_assessable"


def test_no_burning_inconsistent(client, env, stub_crop_three_fires_low_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("no_burning"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "inconsistent"
    assert "3" in check["basis"] and "detection" in check["basis"]


def test_no_burning_consistent(client, env, stub_tree_no_fires_high_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("no_burning"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "consistent"
    assert "0" in check["basis"]


def test_no_burning_cannot_assess(client, env, stub_unavailable):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("no_burning"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "cannot_assess"
    assert any(g["dataset"] == "NASA FIRMS" for g in data["payload"]["declared_gaps"])


def test_vegetation_present_consistent(client, env, stub_tree_no_fires_high_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("vegetation_present"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "consistent"
    assert "0.700" in check["basis"] or "0.7" in check["basis"]


def test_vegetation_present_inconsistent(client, env, stub_crop_three_fires_low_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("vegetation_present"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "inconsistent"


def test_free_text_cannot_assess(client, env, stub_tree_no_fires_high_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("free_text"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    check = data["checks"][0]
    assert check["result"] == "cannot_assess"
    assert data["case_verdict"] == "partially_assessable"


def test_honesty_no_legal_verdict(client, env, stub_tree_no_fires_high_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("site_forested"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    payload = data["payload"]
    assert payload["case_verdict"] in (
        "inconsistencies_found",
        "partially_assessable",
        "no_inconsistency_detected_with_current_evidence",
    )
    assert "illegal activity confirmed" not in json.dumps(payload).lower()
    # Legal note is present but it is a declaration of non-determination, not a verdict.
    assert payload["legal_note"]
    assert payload["disclaimer"]
    assert payload["honesty_contract"]


def test_chain_of_custody(client, env, stub_tree_no_fires_high_ndvi):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/forensics/cases", json=_case_payload("site_forested"), headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    coc = data["payload"]["chain_of_custody"]
    assert coc["case_id"] == data["case_id"]
    assert coc["engine_version"]
    assert len(coc["evidence_records"]) >= 1
    for rec in coc["evidence_records"]:
        assert rec["evidence_id"]
        assert rec["content_hash"]
        assert rec["source"]


def test_invalid_typology(client, env):
    _, token = _register_and_verify(client, env)
    payload = _case_payload()
    payload["typology"] = "not_a_typology"
    resp = client.post("/api/v2/forensics/cases", json=payload, headers=_auth(token))
    assert resp.status_code == 400
    assert "typology" in resp.get_json()["error"].lower()


def test_invalid_claim_type(client, env):
    _, token = _register_and_verify(client, env)
    payload = _case_payload()
    payload["subject_claim"]["type"] = "not_a_claim"
    resp = client.post("/api/v2/forensics/cases", json=payload, headers=_auth(token))
    assert resp.status_code == 400
    assert "subject_claim" in resp.get_json()["error"].lower()


def test_invalid_site(client, env):
    _, token = _register_and_verify(client, env)
    payload = _case_payload()
    payload["site"] = {"lat": 999, "lon": 0}
    resp = client.post("/api/v2/forensics/cases", json=payload, headers=_auth(token))
    assert resp.status_code == 400


def test_case_unknown_id(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.get("/api/v2/forensics/cases/nosuchid", headers=_auth(token))
    assert resp.status_code == 404


def test_case_pdf(client, env, stub_tree_no_fires_high_ndvi):
    pytest.importorskip("reportlab")
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/forensics/cases/pdf",
        json=_case_payload("site_forested"),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert 'inline; filename="talaix_forensics_' in resp.headers.get("Content-Disposition", "")


def test_case_pdf_reportlab_missing(client, env, stub_tree_no_fires_high_ndvi, monkeypatch):
    monkeypatch.setattr("src.dashboard.forensics_report._HAS_REPORTLAB", False)
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/forensics/cases/pdf",
        json=_case_payload("site_forested"),
        headers=_auth(token),
    )
    assert resp.status_code == 503
    assert "reportlab" in resp.get_json()["error"].lower()

"""Tests for the Supply Chain Origin & EUDR Evidence feature.

Fully offline: land-cover and Sentinel-2 fetchers are monkeypatched, so no
network calls are made.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_supplychain_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "supplychain.sqlite3"
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


def _landcover_ok(lat, lon, window_m=500.0):
    return {
        "dominant_class": 10,
        "dominant_label": "Tree cover",
        "dominant_fraction": 0.72,
        "fuel_model": "TL3",
        "resolution": "10 m",
        "source": "ESA WorldCover 10m 2021 v200",
        "histogram": {10: {"label": "Tree cover", "fraction": 0.72}},
    }


def _satellite_ok(lat, lon, days_back=30):
    return {
        "ndvi": 0.67,
        "ndmi": 0.12,
        "observation_date": "2024-06-15T00:00:00",
        "source": "Satellite observation (Earth Search STAC)",
        "resolution_m": 10,
    }


def _landcover_error(lat, lon, window_m=500.0):
    return {"error": "WorldCover read failed: network timeout", "source": "ESA WorldCover 10m 2021 v200"}


def _satellite_error(lat, lon, days_back=30):
    return {"error": "No recent cloud-free Sentinel-2 scene available", "source": "Sentinel-2 L2A (Earth Search STAC)"}


@pytest.fixture()
def stub_ok(monkeypatch):
    import src.climate.supplychain as sc

    monkeypatch.setattr(sc, "fetch_landcover", _landcover_ok)
    monkeypatch.setattr(sc, "fetch_satellite_data", _satellite_ok)


@pytest.fixture()
def stub_unavailable(monkeypatch):
    import src.climate.supplychain as sc

    monkeypatch.setattr(sc, "fetch_landcover", _landcover_error)
    monkeypatch.setattr(sc, "fetch_satellite_data", _satellite_error)


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
    resp = client.get("/api/v2/supplychain/frameworks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "frameworks" in data
    assert len(data["frameworks"]) >= 1
    assert any(fw.get("id") == "eudr" for fw in data["frameworks"])


def test_claims_requires_auth(client):
    resp = client.post("/api/v2/supplychain/claims", json={"plots": [{"lat": 1.0, "lon": 2.0}]})
    assert resp.status_code in (401, 403)


def test_claims_authenticated(client, env, stub_ok):
    user, token = _register_and_verify(client, env)

    payload = {
        "supplier": "Acme S.A.",
        "commodity": "soy",
        "country": "Brazil",
        "plots": [
            {"name": "Farm A", "lat": -12.3, "lon": -55.4},
            {"name": "Farm B", "lat": -12.31, "lon": -55.41},
        ],
    }
    resp = client.post("/api/v2/supplychain/claims", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["claim_id"]
    assert data["claim_verdict"] == "not_verifiable_with_current_evidence"
    assert data["deforestation_assessment"]["status"] == "not_verifiable"
    assert data["declared_gaps_count"] >= 1
    assert data["plot_count"] == 2
    assert data["partial_evidence_count"] == 2
    assert data["no_evidence_count"] == 0

    claim = data["claim"]
    assert claim["eudr_cutoff_date"] == "2020-12-31"
    assert claim["honesty_contract"]
    assert claim["disclaimer"]
    assert len(claim["declared_gaps"]) >= 1

    for p in claim["plots"]:
        assert p["verdict"] == "partial_evidence"
        assert "error" not in p["landcover"]
        assert "error" not in p["satellite"]
        assert p["evidence"]

    # No verified-green / verified-deforestation-free wording anywhere.
    payload_text = json.dumps(data).lower()
    assert "verified green" not in payload_text
    assert "verified deforestation-free" not in payload_text

    # Owner can retrieve the stored claim.
    resp2 = client.get(f"/api/v2/supplychain/claims/{data['claim_id']}", headers=_auth(token))
    assert resp2.status_code == 200
    record = resp2.get_json()
    assert record["claim_id"] == data["claim_id"]
    assert record["user_id"] == user["id"]
    assert record["claim"]["claim_id"] == data["claim_id"]


def test_claims_invalid_plot(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/supplychain/claims",
        json={"plots": [{"name": "Bad", "lat": "abc", "lon": 0.0}]},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_claims_over_limit(client, env):
    _, token = _register_and_verify(client, env)
    plots = [{"name": f"P{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/supplychain/claims",
        json={"plots": plots},
        headers=_auth(token),
    )
    assert resp.status_code == 413, resp.get_json()
    body = resp.get_json()
    assert body["upgrade"]["required_role"] == "subscriber"


def test_claims_pdf(client, env, stub_ok):
    pytest.importorskip("reportlab")
    _, token = _register_and_verify(client, env)

    payload = {
        "supplier": "Acme S.A.",
        "commodity": "soy",
        "country": "Brazil",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    }
    resp = client.post(
        "/api/v2/supplychain/claims/pdf",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert 'inline; filename="talaix_supplychain_soy.pdf"' in resp.headers.get("Content-Disposition", "")


def test_claim_pdf_reportlab_missing(client, env, stub_ok, monkeypatch):
    """If reportlab is unavailable the PDF endpoint returns 503 honestly."""
    monkeypatch.setattr(
        "src.dashboard.supplychain_report._HAS_REPORTLAB", False
    )
    _, token = _register_and_verify(client, env)
    payload = {
        "supplier": "Acme S.A.",
        "commodity": "soy",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    }
    resp = client.post(
        "/api/v2/supplychain/claims/pdf",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 503
    assert "reportlab" in resp.get_json()["error"].lower()


def test_claim_unknown_id(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.get("/api/v2/supplychain/claims/nosuchid", headers=_auth(token))
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Engine tests
# -----------------------------------------------------------------------------


def test_engine_honesty_when_data_unavailable(stub_unavailable):
    from src.climate.supplychain import evaluate_claim

    claim = evaluate_claim({
        "supplier": "Acme S.A.",
        "commodity": "soy",
        "country": "Brazil",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    })
    assert claim["claim_verdict"] == "not_verifiable_with_current_evidence"
    assert claim["deforestation_assessment"]["status"] == "not_verifiable"
    assert claim["deforestation_assessment"]["cutoff_date"] == "2020-12-31"
    assert len(claim["declared_gaps"]) >= 1

    assert claim["plots"][0]["verdict"] == "no_evidence"
    assert claim["partial_evidence_count"] == 0
    assert claim["no_evidence_count"] == 1

    payload_text = json.dumps(claim).lower()
    assert "verified green" not in payload_text
    assert "verified deforestation-free" not in payload_text


def test_engine_partial_evidence(stub_ok):
    from src.climate.supplychain import evaluate_claim

    claim = evaluate_claim({
        "supplier": "Acme S.A.",
        "commodity": "soy",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    })
    assert claim["claim_verdict"] == "not_verifiable_with_current_evidence"
    assert claim["plots"][0]["verdict"] == "partial_evidence"
    assert any("single-year snapshot" in g["reason"] for g in claim["declared_gaps"])
    assert any(
        g.get("dataset", "").startswith("Global Forest Watch") or "forest-loss" in g["reason"]
        for g in claim["declared_gaps"]
    )


# -----------------------------------------------------------------------------
# EUDR commodity vocabulary
# -----------------------------------------------------------------------------


def test_frameworks_lists_eudr_commodities(client):
    resp = client.get("/api/v2/supplychain/frameworks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["eudr_commodities"]) == 7
    assert "soya" in data["eudr_commodities"]
    assert data["eudr_cutoff_date"] == "2020-12-31"
    assert data["disclaimer"]


def test_commodity_normalisation_and_advisory(stub_ok):
    from src.climate.supplychain import evaluate_claim

    # EUDR-covered commodity (with alias): normalised, no advisory.
    claim = evaluate_claim({
        "commodity": "soy",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    })
    assert claim["commodity_normalised"] == "soya"
    assert claim["commodity_advisory"] is None
    assert claim["supplier_declaration"]

    # Non-EUDR commodity: advisory declared, screen still runs.
    claim = evaluate_claim({
        "commodity": "bananas",
        "plots": [{"name": "Farm A", "lat": -12.3, "lon": -55.4}],
    })
    assert claim["commodity_normalised"] == "bananas"
    assert "not an EUDR-covered commodity" in claim["commodity_advisory"]
    assert claim["claim_verdict"] == "not_verifiable_with_current_evidence"

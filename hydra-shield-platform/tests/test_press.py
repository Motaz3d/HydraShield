"""
Tests for the Talaix Press evidence-pack API.

Covers: English public packs, subscriber language gating, figure endpoints,
source registry, PDF generation, and deterministic pack structure. All tests
are offline: external fetchers and image builders are mocked.
"""

import email as email_lib
import email.policy
import re
import sqlite3

import pytest

from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test; dev email backend guaranteed."""
    db_path = tmp_path / "press.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    for var in ("SMTP_HOST", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    yield {"db": db_path, "outbox": tmp_path / "outbox"}
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def client(env, monkeypatch):
    app = create_app()
    app.config["TESTING"] = True

    # Mock the external data paths so every test is offline.
    monkeypatch.setattr(
        "src.climate.press.verify_asset",
        lambda lat, lon, name=None: {
            "verification_id": "v1234567890abcdef",
            "asset": {"lat": lat, "lon": lon, "name": name},
            "generated_at": "2026-08-26T00:00:00Z",
            "hazard_checks": [
                {
                    "hazard": "flood",
                    "taxonomy_label": "Riverine / pluvial flooding",
                    "risk_class": ["acute"],
                    "status": "ok",
                    "claim_status": "MODELLED",
                    "confidence": "medium",
                    "level": {"label": "Low", "basis": "Low screening indicator from GloFAS."},
                    "summary": "Flood risk is low.",
                    "evidence": [],
                    "limitations": [],
                },
                {
                    "hazard": "drought",
                    "taxonomy_label": "Drought / water stress",
                    "risk_class": ["chronic"],
                    "status": "ok",
                    "claim_status": "MODELLED",
                    "confidence": "medium",
                    "level": {"label": "Severe", "basis": "Severe screening indicator from precipitation anomaly."},
                    "summary": "Drought risk is severe.",
                    "evidence": [],
                    "limitations": [],
                },
                {
                    "hazard": "wind",
                    "taxonomy_label": "Storms & extreme wind",
                    "risk_class": ["acute"],
                    "status": "ok",
                    "claim_status": "MODELLED",
                    "confidence": "medium",
                    "level": {"label": "Moderate", "basis": "Moderate screening indicator from wind gusts."},
                    "summary": "Wind risk is moderate.",
                    "evidence": [],
                    "limitations": [],
                },
            ],
            "declared_gaps": [],
            "summary": "3 of 3 hazards assessed.",
        },
    )
    monkeypatch.setattr(
        "src.climate.press.fetch_climate_series",
        lambda lat, lon, start_year=1991: {
            "annual": [
                {"year": 2022, "mean_tmax_c": 14.10, "total_precip_mm": 720.0, "days_used": 365},
                {"year": 2023, "mean_tmax_c": 14.50, "total_precip_mm": 680.0, "days_used": 365},
                {"year": 2024, "mean_tmax_c": 14.80, "total_precip_mm": 640.0, "days_used": 366},
            ],
            "baseline": {"period": "1991–2020", "mean_tmax_c": 14.00, "precip_mm": 700.0, "years_used": 30},
            "current": {"year": 2024, "mean_tmax_anomaly_c": 0.80, "precip_pct_of_baseline": 91.4},
            "series_end_year": 2024,
            "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
        },
    )
    monkeypatch.setattr(
        "src.climate.press.fetch_satellite_data",
        lambda lat, lon, days_back=30: {
            "ndvi": 0.42,
            "ndmi": 0.21,
            "ndwi": -0.05,
            "cloud_cover_pct": 12.0,
            "observation_date": "2026-08-20",
            "source": "Sentinel-2 L2A (Earth Search STAC)",
            "ndvi_grid": [[0.1] * 24 for _ in range(24)],
        },
    )
    monkeypatch.setattr(
        "src.climate.press.reverse_geocode",
        lambda lat, lon: {"name": "Testville", "lat": lat, "lon": lon, "source": "Nominatim"},
    )
    monkeypatch.setattr(
        "src.climate.press.build_site_context_png",
        lambda lat, lon, window_m=1000.0: b"fake-site-png",
    )
    monkeypatch.setattr(
        "src.dashboard.press_charts.climate_series_png",
        lambda lat, lon: b"fake-climate-png",
    )
    monkeypatch.setattr(
        "src.dashboard.press_charts.build_ndvi_png",
        lambda grid: b"fake-ndvi-png",
    )
    monkeypatch.setattr(
        "src.dashboard.site_image.build_site_context_png",
        lambda lat, lon, window_m=1000.0: b"fake-site-png",
    )
    # Avoid depending on reportlab in the test environment.
    monkeypatch.setattr(
        "src.dashboard.press_pdf.build_press_pdf",
        lambda pack: b"fake-pdf-bytes",
    )

    with app.test_client() as c:
        yield c


def _auth_headers(client, env, email="user@example.org"):
    """Register + verify a user through the real auth flow; Bearer headers."""
    resp = client.post(
        "/api/v2/auth/register",
        json={"email": email, "password": "correct horse battery", "consent": True},
    )
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default
    )
    token = re.search(r"token=([A-Za-z0-9_\-]+)", msg.get_body(("plain",)).get_content()).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    return {"Authorization": f"Bearer {resp.get_json()['session_token']}"}


# ---------------------------------------------------------------------------
# Pack endpoint
# ---------------------------------------------------------------------------


def test_press_pack_en_public(client):
    resp = client.get("/api/v2/press/pack?lat=49.85&lon=6.03")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["language"] == "en"
    assert body["tier"] == "public"
    assert body["location"]["name"] == "Testville"
    assert body["topic"]["hazard"] == "drought"
    assert body["topic"]["level"] == "Severe"
    assert body["headline"].startswith("Climate evidence pack:")
    assert any("2024" in fact for fact in body["key_facts"])
    assert len(body["quotable_lines"]) >= 2
    assert len(body["figures"]) == 3
    assert len(body["press_watch"]) == 25


def test_press_pack_fr_requires_authentication(client):
    resp = client.get("/api/v2/press/pack?lat=49.85&lon=6.03&lang=fr")
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["error"] == "Authentication required"


def test_press_pack_fr_authenticated_non_subscriber_403(client, env):
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/press/pack?lat=49.85&lon=6.03&lang=fr", headers=headers)
    assert resp.status_code == 403, resp.get_json()
    body = resp.get_json()
    assert body["upgrade"]["required_role"] == "subscriber"
    assert body["upgrade"]["your_role"] == "registered"


def test_press_pack_fr_subscriber_ok(client, env):
    headers = _auth_headers(client, env)
    sub = client.post("/api/v2/account/subscribe", headers=headers)
    assert sub.status_code == 201, sub.get_json()

    resp = client.get("/api/v2/press/pack?lat=49.85&lon=6.03&lang=fr", headers=headers)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["language"] == "fr"
    assert body["tier"] == "subscriber"
    assert body["headline"].startswith("Dossier d’évidence")


def test_press_pack_invalid_coordinates(client):
    assert client.get("/api/v2/press/pack").status_code == 400
    assert client.get("/api/v2/press/pack?lat=99&lon=6").status_code == 400


def test_press_pack_unsupported_language(client):
    resp = client.get("/api/v2/press/pack?lat=49.85&lon=6.03&lang=es")
    assert resp.status_code == 400
    assert "Unsupported language" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# PDF endpoint
# ---------------------------------------------------------------------------


def test_press_pdf_en_public(client):
    resp = client.get("/api/v2/press/pack.pdf?lat=49.85&lon=6.03")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data == b"fake-pdf-bytes"


def test_press_pdf_fr_requires_authentication(client):
    resp = client.get("/api/v2/press/pack.pdf?lat=49.85&lon=6.03&lang=fr")
    assert resp.status_code == 401


def test_press_pdf_fr_authenticated_non_subscriber_403(client, env):
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/press/pack.pdf?lat=49.85&lon=6.03&lang=fr", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "subscriber"


# ---------------------------------------------------------------------------
# Figure endpoints
# ---------------------------------------------------------------------------


def test_press_figure_climate(client):
    resp = client.get("/api/v2/press/figure/climate?lat=49.85&lon=6.03")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data == b"fake-climate-png"


def test_press_figure_ndvi(client):
    resp = client.get("/api/v2/press/figure/ndvi?lat=49.85&lon=6.03")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data == b"fake-ndvi-png"


def test_press_figure_site(client):
    resp = client.get("/api/v2/press/figure/site?lat=49.85&lon=6.03")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data == b"fake-site-png"


def test_press_figure_unknown_kind(client):
    assert client.get("/api/v2/press/figure/weather?lat=49.85&lon=6.03").status_code == 404


# ---------------------------------------------------------------------------
# Sources / press-watch registry
# ---------------------------------------------------------------------------


def test_press_sources_registry(client):
    resp = client.get("/api/v2/press/sources")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["sources"], list)
    assert len(body["sources"]) == 25
    assert all("name" in s and "url" in s for s in body["sources"])

"""Tests for per-user portfolios (geographic + temporal + goal containers)
and the analysis/report history wiring.

Fully offline: isolated tmp SQLite DB per test; history wiring is exercised
through the auth helpers inside a request context — never the network.
"""

import pytest

from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "accounts.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register_and_verify(client, env, email="user@example.org",
                         password="correct horse battery"):
    import re

    resp = client.post("/api/v2/auth/register",
                       json={"email": email, "password": password, "consent": True})
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["db"].parent.joinpath("outbox").glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    import email as email_lib
    import email.policy  # noqa: F401

    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    plain = msg.get_body(("plain",)).get_content()
    token = re.search(r"token=([A-Za-z0-9_\-]+)", plain).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return body["user"], body["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_portfolio(client, token, **overrides):
    payload = {"name": "Iberia wildfire review", "goal": "insurance_review",
               "region_name": "Andalusia", "start_date": "2026-01-01",
               "end_date": "2026-12-31"}
    payload.update(overrides)
    resp = client.post("/api/v2/account/portfolios", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["portfolio"]


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

def test_portfolios_require_authentication(client):
    assert client.get("/api/v2/account/portfolios").status_code == 401
    assert client.post("/api/v2/account/portfolios", json={"name": "x"}).status_code == 401
    assert client.get("/api/v2/account/portfolios/1").status_code == 401
    assert client.post("/api/v2/account/portfolios/1/items", json={}).status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_list_get_portfolio(client, env):
    _, token = _register_and_verify(client, env)
    p = _create_portfolio(client, token)
    assert p["goal"] == "insurance_review"
    assert p["region_name"] == "Andalusia"
    assert p["start_date"] == "2026-01-01"

    listed = client.get("/api/v2/account/portfolios", headers=_auth(token)).get_json()
    assert [x["id"] for x in listed["portfolios"]] == [p["id"]]
    assert listed["portfolios"][0]["item_count"] == 0

    got = client.get(f"/api/v2/account/portfolios/{p['id']}", headers=_auth(token))
    assert got.status_code == 200
    assert got.get_json()["portfolio"]["items"] == []


def test_create_portfolio_validation(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/account/portfolios", json={"name": ""}, headers=_auth(token))
    assert resp.status_code == 400
    resp = client.post("/api/v2/account/portfolios",
                       json={"name": "x", "start_date": "2026-12-31",
                             "end_date": "2026-01-01"}, headers=_auth(token))
    assert resp.status_code == 400


def test_portfolio_items_lifecycle(client, env):
    _, token = _register_and_verify(client, env)
    p = _create_portfolio(client, token)

    for kind, extra in (
        ("location", {"lat": 37.6, "lon": -6.5}),
        ("analysis", {"lat": 37.6, "lon": -6.5, "ref_id": 12,
                      "meta": {"risk_class": "High"}}),
        ("report", {"ref_id": 7, "meta": {"report_type": "decision"}}),
        ("alert", {"ref_id": 3}),
    ):
        resp = client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                           json={"kind": kind, **extra}, headers=_auth(token))
        assert resp.status_code == 201, (kind, resp.get_json())

    got = client.get(f"/api/v2/account/portfolios/{p['id']}", headers=_auth(token))
    items = got.get_json()["portfolio"]["items"]
    assert [i["kind"] for i in items] == ["location", "analysis", "report", "alert"]
    assert items[1]["meta"]["risk_class"] == "High"

    listed = client.get("/api/v2/account/portfolios", headers=_auth(token)).get_json()
    assert listed["portfolios"][0]["item_count"] == 4

    resp = client.delete(f"/api/v2/account/portfolios/{p['id']}/items/{items[0]['id']}",
                         headers=_auth(token))
    assert resp.status_code == 200
    got = client.get(f"/api/v2/account/portfolios/{p['id']}", headers=_auth(token))
    assert len(got.get_json()["portfolio"]["items"]) == 3


def test_portfolio_item_validation(client, env):
    _, token = _register_and_verify(client, env)
    p = _create_portfolio(client, token)
    resp = client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                       json={"kind": "satellite"}, headers=_auth(token))
    assert resp.status_code == 400
    resp = client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                       json={"kind": "location", "lat": 37.6}, headers=_auth(token))
    assert resp.status_code == 400
    resp = client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                       json={"kind": "location", "lat": 91.0, "lon": 0.0},
                       headers=_auth(token))
    assert resp.status_code == 400
    resp = client.post("/api/v2/account/portfolios/9999/items",
                       json={"kind": "location", "lat": 1.0, "lon": 1.0},
                       headers=_auth(token))
    assert resp.status_code == 404


def test_portfolios_are_isolated_per_user(client, env):
    _, token_a = _register_and_verify(client, env, email="a@example.org")
    _, token_b = _register_and_verify(client, env, email="b@example.org")
    p = _create_portfolio(client, token_a)

    assert client.get("/api/v2/account/portfolios", headers=_auth(token_b)
                      ).get_json()["portfolios"] == []
    assert client.get(f"/api/v2/account/portfolios/{p['id']}",
                      headers=_auth(token_b)).status_code == 404
    assert client.delete(f"/api/v2/account/portfolios/{p['id']}",
                         headers=_auth(token_b)).status_code == 404
    assert client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                       json={"kind": "report"}, headers=_auth(token_b)).status_code == 404


def test_delete_portfolio_cascades_items(client, env):
    _, token = _register_and_verify(client, env)
    p = _create_portfolio(client, token)
    client.post(f"/api/v2/account/portfolios/{p['id']}/items",
                json={"kind": "report", "ref_id": 1}, headers=_auth(token))
    assert client.delete(f"/api/v2/account/portfolios/{p['id']}",
                         headers=_auth(token)).status_code == 200
    assert client.get(f"/api/v2/account/portfolios/{p['id']}",
                      headers=_auth(token)).status_code == 404
    store = UserStore(str(env["db"]))
    with store._connect() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM portfolio_items").fetchone()
    assert rows[0] == 0


# ---------------------------------------------------------------------------
# History wiring (record_analysis / record_report are now actually called)
# ---------------------------------------------------------------------------

def test_history_recording_helpers(client, env):
    user, token = _register_and_verify(client, env)
    from src.dashboard.auth_api import record_user_analysis, record_user_report

    with client.application.test_request_context(
            "/api/v2/analyze", headers={"Authorization": f"Bearer {token}"}):
        record_user_analysis("wildfire", 37.6, -6.5, {"name": "Huelva"},
                             {"risk_class": "High"})
        record_user_report("decision", "wildfire", 37.6, -6.5,
                           {"name": "Huelva"}, {"report_id": "r1"})

    hist = client.get("/api/v2/account/history", headers=_auth(token)).get_json()
    assert hist["analyses"][0]["hazard"] == "wildfire"
    assert hist["analyses"][0]["summary"]["risk_class"] == "High"
    assert hist["reports"][0]["report_type"] == "decision"
    assert hist["reports"][0]["report_meta"]["report_id"] == "r1"
    assert user["id"]


def test_history_recording_skips_anonymous(client, env):
    from src.dashboard.auth_api import record_user_analysis

    with client.application.test_request_context("/api/v2/analyze"):
        record_user_analysis("wildfire", 37.6, -6.5, {}, {})  # must not raise

    store = UserStore(str(env["db"]))
    with store._connect() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM analysis_history").fetchone()
    assert rows[0] == 0

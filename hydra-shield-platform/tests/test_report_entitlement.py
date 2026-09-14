"""The pay-per-report entitlement contract (operator decision 2026-09-14).

Verified live before this gate existed: `GET /api/report?lat=…&lon=…&type=decision`
and `…&type=scientific` returned real PDFs (31,632 / 35,199 bytes) with **no
authentication at all**, so the published €19 / €39 packs were one URL away for
anyone. The published free tier promises a free *simple* report, so the fix is
to keep `simple` open to everyone and release the two paid packs only to an
active subscription or a completed purchase of that exact pack.

Design note: the gate runs before the analysis, so these tests stub
`_cached_analysis` to fail deterministically. That gives a sharp contrast —
the *same* stub yields 404 for a free request (gate passed) and 402 for a paid
one (gate blocked).
"""

import os

import pytest

os.environ.setdefault("HYDRASHIELD_CACHE_DB",
                      "/tmp/hydrashield_test_entitlement.sqlite3")
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.delenv("HYDRASHIELD_OPERATOR_EMAILS", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._RateLimiter())
    return {"db": db_path}


@pytest.fixture()
def client(env):
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _register_login(client, env, email):
    client.post("/api/v2/auth/register",
                json={"email": email, "password": "Correct-Horse-42!",
                      "consent": True})
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email(email)
    store.mark_email_verified(user["id"])
    login = client.post("/api/v2/auth/login",
                        json={"email": email, "password": "Correct-Horse-42!"})
    return {"Authorization": f"Bearer {login.get_json()['session_token']}"}, user["id"]


def _stub_analysis(monkeypatch):
    """Make the analysis fail cleanly: everything after the gate returns 404."""
    import src.dashboard.api as api_mod

    monkeypatch.setattr(api_mod, "_cached_analysis",
                        lambda lat, lon, name: {"error": "no data (offline test)"})
    return api_mod


# ---------------------------------------------------------------------------
# The leak is closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("report_type,price", [("decision", "€19"),
                                               ("scientific", "€39")])
def test_anonymous_paid_report_is_refused(client, report_type, price):
    resp = client.get(f"/api/report?lat=37.6&lon=-6.5&type={report_type}")
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["error"] == "purchase_required"
    assert body["price"] == price
    assert body["kind"] == f"report_{report_type}"


def test_the_bare_url_is_not_a_loophole(client):
    """`/api/report?lat&lon` defaults to the decision pack — the exact URL that
    used to hand out the paid PDF."""
    resp = client.get("/api/report?lat=37.6&lon=-6.5")
    assert resp.status_code == 402


def test_a_refusal_is_a_path_not_a_dead_end(client):
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=decision")
    body = resp.get_json()
    assert "simple" in body["message"], "name the free alternative"
    assert body["buy_url"].endswith("#builder")
    assert body["free_report_url"]
    assert "reason=signin" in body["sign_in_url"]


def test_browser_visitor_gets_a_purchase_page_not_raw_json(client):
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=scientific",
                      headers={"Accept": "text/html"})
    assert resp.status_code == 402
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)
    assert "purchase required" in html.lower()
    assert "€39" in html
    assert "/pricing.html" in html
    assert "/reports.html" in html


# ---------------------------------------------------------------------------
# The free tier stays free
# ---------------------------------------------------------------------------

def test_simple_report_is_never_gated(client, monkeypatch):
    """Same failing-analysis stub as the paid tests: `simple` gets past the
    gate (404 from the stub), the paid packs do not (402)."""
    _stub_analysis(monkeypatch)
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=simple")
    assert resp.status_code != 402
    assert b"purchase_required" not in resp.data


def test_the_gate_runs_before_the_analysis(client, monkeypatch):
    """An unentitled request must not trigger a (slow, costly) computation."""
    import src.dashboard.api as api_mod

    called = {"n": 0}

    def _boom(lat, lon, name):
        called["n"] += 1
        return {"error": "should never be reached"}

    monkeypatch.setattr(api_mod, "_cached_analysis", _boom)
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=decision")
    assert resp.status_code == 402
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Who is entitled
# ---------------------------------------------------------------------------

def test_an_active_subscription_unlocks_both_packs(client, env, monkeypatch):
    headers, user_id = _register_login(client, env, "subscriber@example.org")
    from src.dashboard.accounts import UserStore

    UserStore(str(env["db"])).activate_subscription(user_id, tier="professional")
    _stub_analysis(monkeypatch)
    for report_type in ("decision", "scientific"):
        resp = client.get(f"/api/report?lat=37.6&lon=-6.5&type={report_type}",
                          headers=headers)
        assert resp.status_code != 402, report_type
        assert b"purchase_required" not in resp.data


def test_a_recorded_purchase_unlocks_only_that_pack(client, env, monkeypatch):
    headers, user_id = _register_login(client, env, "buyer@example.org")
    from src.dashboard.billing import BillingStore

    BillingStore(str(env["db"])).record_purchase(
        user_id, "report_decision", "cs_test_decision")
    _stub_analysis(monkeypatch)
    owned = client.get("/api/report?lat=37.6&lon=-6.5&type=decision", headers=headers)
    assert owned.status_code != 402
    other = client.get("/api/report?lat=37.6&lon=-6.5&type=scientific", headers=headers)
    assert other.status_code == 402


def test_an_unfinished_purchase_does_not_unlock(client, env, monkeypatch):
    headers, user_id = _register_login(client, env, "pending@example.org")
    from src.dashboard.billing import BillingStore

    BillingStore(str(env["db"])).record_purchase(
        user_id, "report_decision", "cs_test_pending", status="pending")
    _stub_analysis(monkeypatch)
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=decision", headers=headers)
    assert resp.status_code == 402


def test_another_users_purchase_does_not_unlock(client, env, monkeypatch):
    headers, _ = _register_login(client, env, "stranger@example.org")
    _, buyer_id = _register_login(client, env, "realbuyer@example.org")
    from src.dashboard.billing import BillingStore

    BillingStore(str(env["db"])).record_purchase(
        buyer_id, "report_decision", "cs_test_other")
    _stub_analysis(monkeypatch)
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=decision", headers=headers)
    assert resp.status_code == 402


def test_the_operator_can_always_generate(client, env, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_OPERATOR_EMAILS", "info@talaix.com")
    headers, _ = _register_login(client, env, "info@talaix.com")
    _stub_analysis(monkeypatch)
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=scientific",
                      headers=headers)
    assert resp.status_code != 402
    assert b"purchase_required" not in resp.data


def test_billing_store_has_purchase_reads_only_completed(client, env):
    """The entitlement helper itself, including its idempotency."""
    from src.dashboard.billing import BillingStore

    store = BillingStore(str(env["db"]))
    assert store.has_purchase(4242, "report_decision") is False
    store.record_purchase(4242, "report_decision", "cs_x1", status="completed")
    store.record_purchase(4242, "report_decision", "cs_x1", status="completed")
    assert store.has_purchase(4242, "report_decision") is True
    assert store.has_purchase(4242, "report_scientific") is False
    store.record_purchase(4242, "report_scientific", "cs_x2", status="refunded")
    assert store.has_purchase(4242, "report_scientific") is False

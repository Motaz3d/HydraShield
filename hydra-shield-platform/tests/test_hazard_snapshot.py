"""Tests for the multi-hazard snapshot backend (network-free).

Covers: per-hazard boards over the monitored areas, honest omission of
non-computable areas (never fabricated levels), top-k ordering, the
unavailable path, the additive /api/risk-snapshot "multi_hazard" key
(failure-isolated from the wildfire snapshot), and the homepage wiring.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_hsnapshot.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import hazard_snapshot as hs  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


def _write_config(tmp_path, n=4, top_k=5):
    areas = [{"name": f"Area{i}", "lat": 40.0 + i, "lon": 10.0 + i}
             for i in range(n)]
    cfg = {"scope": "Test scope", "top_k": top_k, "areas": areas}
    path = tmp_path / "areas.json"
    path.write_text(json.dumps(cfg))
    return str(path)


def _fake_ok(hazard_id, lat, lon, name):
    return {
        "status": "ok",
        "level": {"label": "High", "score": lat, "score_max": 100,
                  "basis": "test basis", "validated": False},
        "summary": "test summary",
    }


# ---------------------------------------------------------------------------
# compute_hazard_snapshot
# ---------------------------------------------------------------------------

def test_boards_cover_every_registered_hazard_except_wildfire(tmp_path):
    cfg = _write_config(tmp_path)
    snap = hs.compute_hazard_snapshot(config_path=cfg, analyse_fn=_fake_ok)
    assert snap["status"] == "ok"
    ids = [h["hazard"] for h in snap["hazards"]]
    assert "wildfire" not in ids
    assert {"flood", "heat", "drought", "wind", "coastal", "cyclone"} <= set(ids)
    assert snap["scope"] == "Test scope"
    assert "screening" in snap["model"]["note"]


def test_entries_are_ranked_and_capped(tmp_path):
    cfg = _write_config(tmp_path, n=6)
    snap = hs.compute_hazard_snapshot(config_path=cfg, analyse_fn=_fake_ok)
    board = next(h for h in snap["hazards"] if h["hazard"] == "flood")
    assert len(board["entries"]) == hs._TOP_PER_HAZARD
    scores = [e["level_score"] for e in board["entries"]]
    assert scores == sorted(scores, reverse=True)
    assert [e["rank"] for e in board["entries"]] == [1, 2, 3]
    for e in board["entries"]:
        assert e["level_basis"] == "test basis"
        assert e["validated"] is False


def test_unavailable_areas_are_omitted_never_filled(tmp_path):
    cfg = _write_config(tmp_path, n=4)

    def fake(hazard_id, lat, lon, name):
        if hazard_id == "coastal":
            return {"status": "unavailable",
                    "unavailable_reason": "not a coastal location"}
        if name == "Area2":
            raise RuntimeError("upstream blew up")
        return _fake_ok(hazard_id, lat, lon, name)

    snap = hs.compute_hazard_snapshot(config_path=cfg, analyse_fn=fake)
    coastal = next(h for h in snap["hazards"] if h["hazard"] == "coastal")
    assert coastal["areas_with_data"] == 0 and coastal["entries"] == []
    flood = next(h for h in snap["hazards"] if h["hazard"] == "flood")
    names = [e["name"] for e in flood["entries"]]
    assert "Area2" not in names
    assert flood["areas_with_data"] == 3


def test_all_failing_analyses_report_unavailable_honestly(tmp_path):
    cfg = _write_config(tmp_path)

    def fake(hazard_id, lat, lon, name):
        return {"status": "unavailable", "unavailable_reason": "no data"}

    snap = hs.compute_hazard_snapshot(config_path=cfg, analyse_fn=fake)
    assert snap["status"] == "unavailable"
    assert all(h["entries"] == [] for h in snap["hazards"])
    assert "temporarily unavailable" in snap["message"]


def test_bad_config_is_an_honest_unavailable(tmp_path):
    snap = hs.compute_hazard_snapshot(config_path=str(tmp_path / "nope.json"),
                                      analyse_fn=_fake_ok)
    assert snap["status"] == "unavailable"


# ---------------------------------------------------------------------------
# /api/risk-snapshot additive multi_hazard key
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    import src.dashboard.api as api_module
    import src.dashboard.snapshot as snapshot_module

    api_module._rate_limiter._hits.clear()
    monkeypatch.setattr(
        snapshot_module, "get_snapshot",
        lambda: {"status": "ok", "scope": "s", "entries": [], "sources": []})
    monkeypatch.setattr(
        hs, "get_hazard_snapshot",
        lambda: {"status": "ok", "hazards": [{"hazard": "flood", "entries": [
            {"name": "A", "level_label": "High", "level_score": 60,
             "level_score_max": 100, "latitude": 1, "longitude": 2}]}]})
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    api_module._rate_limiter._hits.clear()


def test_risk_snapshot_carries_multi_hazard_additively(client):
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    board = body["multi_hazard"]["hazards"][0]
    assert board["hazard"] == "flood"
    assert board["entries"][0]["level_score"] == 60


def test_multi_hazard_failure_never_breaks_wildfire_snapshot(client, monkeypatch):
    def _boom():
        raise RuntimeError("multi-hazard engine down")

    monkeypatch.setattr(hs, "get_hazard_snapshot", _boom)
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 200
    assert "multi_hazard" not in resp.get_json()


# ---------------------------------------------------------------------------
# get_hazard_snapshot: request path never builds inline (production OOM)
# ---------------------------------------------------------------------------

def test_request_path_never_builds_inline(monkeypatch):
    calls = []

    def spy(hazard_id, lat, lon, name):
        calls.append(hazard_id)
        return _fake_ok(hazard_id, lat, lon, name)

    monkeypatch.setattr(hs.default_cache(), "get", lambda key: None)
    snap = hs.get_hazard_snapshot(analyse_fn=spy, build=False)
    assert snap["status"] == "unavailable"
    assert "warming" in snap["message"]
    assert calls == [], "no analysis may run on the request path"


def test_explicit_build_runs_and_caches(monkeypatch, tmp_path):
    cfg = _write_config(tmp_path)
    monkeypatch.setattr(hs.default_cache(), "get", lambda key: None)
    snap = hs.get_hazard_snapshot(config_path=cfg, analyse_fn=_fake_ok, build=True)
    assert snap["status"] == "ok"
    assert any(h["entries"] for h in snap["hazards"])


def test_warming_state_is_omitted_from_risk_snapshot(client, monkeypatch):
    monkeypatch.setattr(hs, "get_hazard_snapshot", lambda: {
        "status": "unavailable", "message": "warming", "hazards": []})
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 200
    assert "multi_hazard" not in resp.get_json()


# ---------------------------------------------------------------------------
# Homepage wiring
# ---------------------------------------------------------------------------

def test_homepage_carries_multi_hazard_mount_and_renderer():
    root = os.path.join(os.path.dirname(__file__), "..", "website")
    with open(os.path.join(root, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'id="hazardBoard"' in html
    assert "wildfire, flood, heat, drought" in html
    with open(os.path.join(root, "js", "risk-snapshot.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert "multi_hazard" in js and "map.html?hazard=" in js


def test_homepage_carries_all_six_audience_services():
    path = os.path.join(os.path.dirname(__file__), "..", "website", "index.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    for sector in ("government", "insurance", "real-estate",
                   "consulting", "investors", "banks"):
        assert f"industries.html?sector={sector}" in html, sector

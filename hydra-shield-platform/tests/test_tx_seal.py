"""Tests for the TX authenticity seal.

Network-free: all seal tests run offline with injected stores and stubbed
hazard modules.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_tx_seal_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import registry  # noqa: E402
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.climate.tx_seal import (  # noqa: E402
    SEAL_RE,
    check_seal,
    issue_seal,
    is_seal_format,
    normalize_code,
    seal_code,
    verify_seal,
)
from src.climate.verification import verify_asset  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402
from src.dashboard.verification_store import VerificationStore  # noqa: E402
from tests.test_tx_core import FakeHazardModule, make_engine  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Flask test client with isolated cache DB."""
    db_path = tmp_path / "tx_seal_api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Core seal behaviour
# ---------------------------------------------------------------------------


def test_seal_code_matches_format():
    code = seal_code({"a": 1})
    assert SEAL_RE.match(code)
    assert is_seal_format(code)
    assert normalize_code(code) == code


def test_seal_code_is_deterministic():
    payload = {"lat": 41.5, "lon": -8.6, "items": ["a", "b"]}
    assert seal_code(payload) == seal_code(payload)


def test_seal_code_changes_with_payload():
    a = seal_code({"x": 1})
    b = seal_code({"x": 2})
    assert a != b
    assert SEAL_RE.match(a)
    assert SEAL_RE.match(b)


def test_is_seal_format_normalizes_input():
    assert is_seal_format("tx-1a2b-3c4d-5e6f")
    assert is_seal_format("  tx-1A2B-3C4D-5E6F  ")
    assert not is_seal_format("TX-1234")
    assert not is_seal_format(123)
    assert normalize_code("tx-abcd-ef12-3456") == "TX-ABCD-EF12-3456"
    assert normalize_code("bad") is None


# ---------------------------------------------------------------------------
# Stateless check_seal
# ---------------------------------------------------------------------------


def test_check_seal_true_for_original():
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    code = seal_code(payload)
    assert check_seal(payload, code)


def test_check_seal_false_for_tampered_payload():
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    code = seal_code(payload)
    assert not check_seal({**payload, "extra": "tamper"}, code)


def test_check_seal_false_for_wrong_code():
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    assert not check_seal(payload, seal_code({"other": True}))


def test_check_seal_false_for_malformed_code():
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    assert not check_seal(payload, "not-a-seal")
    assert not check_seal(payload, "TX-123")


# ---------------------------------------------------------------------------
# Registry roundtrip
# ---------------------------------------------------------------------------


def test_issue_seal_records_and_verifies(tmp_path):
    db = tmp_path / "seals.sqlite3"
    store = VerificationStore(db_path=str(db))
    payload = {"checks": [{"hazard": "flood", "status": "ok"}]}
    seal = issue_seal("verification", "vid-1", payload, store=store)

    assert SEAL_RE.match(seal["code"])
    assert seal["kind"] == "verification"
    assert seal["engine"] == "TX"
    assert seal["verify_url"] == f"/verify.html#{seal['code']}"

    record = verify_seal(seal["code"], store=store)
    assert record is not None
    assert record["valid"] is True
    assert record["kind"] == "verification"
    assert record["ref_id"] == "vid-1"
    assert record["engine"] == "TX"
    assert "issued_at" in record


def test_verify_seal_unknown_returns_none(tmp_path):
    db = tmp_path / "seals.sqlite3"
    store = VerificationStore(db_path=str(db))
    assert verify_seal("TX-0000-0000-0000", store=store) is None


def test_issue_seal_survives_registry_failure(tmp_path):
    """A registry write error must never break product generation."""
    db = tmp_path / "seals.sqlite3"
    store = VerificationStore(db_path=str(db))

    class BrokenStore:
        def record_seal(self, *a, **kw):
            raise RuntimeError("disk full")

    seal = issue_seal("verification", "vid-1", {"x": 1}, store=BrokenStore())
    assert SEAL_RE.match(seal["code"])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_get_unknown_code(client):
    resp = client.get("/api/v2/verify/TX-0000-0000-0000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is False
    assert "hint" in body


def test_api_get_known_code(client, monkeypatch, tmp_path):
    # Ensure the API and the test share the same DB.
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(tmp_path / "shared.sqlite3"))
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    store = VerificationStore()
    seal = issue_seal("verification", "vid-1", {"x": 1}, store=store)

    resp = client.get(f"/api/v2/verify/{seal['code']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is True
    assert body["kind"] == "verification"
    assert body["ref_id"] == "vid-1"


def test_api_post_valid_recompute(client):
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    code = seal_code(payload)
    resp = client.post("/api/v2/verify", json={"payload": payload, "code": code})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is True
    assert body["code"] == code


def test_api_post_tampered_payload(client):
    payload = {"analysis_id": "TX-20260901-abcdef12", "results": []}
    code = seal_code(payload)
    resp = client.post(
        "/api/v2/verify",
        json={"payload": {**payload, "extra": "tamper"}, "code": code},
    )
    assert resp.status_code == 200
    assert resp.get_json()["valid"] is False


def test_api_post_missing_fields(client):
    resp = client.post("/api/v2/verify", json={"payload": {"x": 1}})
    assert resp.status_code == 400
    resp = client.post("/api/v2/verify", json={"code": "TX-1234-5678-9ABC"})
    assert resp.status_code == 400


def test_api_post_malformed_code(client):
    resp = client.post(
        "/api/v2/verify",
        json={"payload": {"x": 1}, "code": "not-a-seal"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Product-engine integration
# ---------------------------------------------------------------------------


class _FakeOkModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="ok",
            summary=f"{self.id} ok",
            level=HazardLevel(
                label="High",
                score=0.8,
                score_max=1.0,
                basis="modelled screening indicator",
                validated=False,
            ),
            evidence=[{
                "evidence_class": "MODELLED",
                "claim_status": "MODELLED",
                "temporal": "OBSERVED",
                "source": "Fake source",
                "dataset": "Fake dataset",
            }],
            provenance={"model": {"source": "Fake"}},
        )


def _stub_registry(monkeypatch, ok=("flood",)):
    def fake_get(hazard_id: str):
        if hazard_id in ok:
            return _FakeOkModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


def test_verification_payload_has_authenticity(client, monkeypatch, tmp_path):
    _stub_registry(monkeypatch, ok=("flood",))
    db = tmp_path / "verify.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db))
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)

    result = verify_asset(41.5, -8.6, name="Test")
    assert "authenticity" in result
    code = result["authenticity"]["code"]
    assert SEAL_RE.match(code)
    assert result["authenticity"]["kind"] == "verification"
    assert result["authenticity"]["engine"] == "TX"


# ---------------------------------------------------------------------------
# tx_core engine integration
# ---------------------------------------------------------------------------


def test_txresult_has_authenticity_code():
    engine = make_engine({"flood": FakeHazardModule("flood")})
    result = engine.analyze(lat=41.5, lon=-8.6)
    assert result.authenticity_code
    assert SEAL_RE.match(result.authenticity_code)

    d = result.to_dict()
    assert "authenticity" in d
    assert d["authenticity"]["code"] == result.authenticity_code
    assert d["authenticity"]["engine"] == "TX"
    assert d["authenticity"]["verify"] == "POST /api/v2/verify"


def test_txresult_authenticity_is_deterministic():
    """Same inputs on the same UTC day produce the same seal code."""
    engine = make_engine({"flood": FakeHazardModule("flood")})
    r1 = engine.analyze(lat=41.5, lon=-8.6)
    r2 = engine.analyze(lat=41.5, lon=-8.6)
    assert r1.authenticity_code == r2.authenticity_code


def test_txresult_empty_authenticity_omits_key():
    from tx_core.models import TxLocation, TxResult

    result = TxResult(
        analysis_id="TX-20260901-abcdef12",
        location=TxLocation(lat=0, lon=0),
        depth="standard",
        results=[],
        engine_version="0.1.0",
        tx_version="0.1.0",
        tam_version="1.0.0",
    )
    d = result.to_dict()
    assert "authenticity" not in d

"""Offline tests for the QGIS plugin's TX client (qgis-plugin/hydrashield).

QGIS is not available in CI, so these tests cover the pure (QGIS-free)
module ``tx_client``: URL construction for GET /api/tx/analyze and the
TxResult → feature-records normalization. Compilation of the QGIS-coupled
algorithm file is covered by tests/test_qgis_plugin.py's directory walk.
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
PLUGIN = os.path.join(ROOT, "qgis-plugin", "hydrashield")
sys.path.insert(0, PLUGIN)

import tx_client  # noqa: E402  (pure module — no qgis imports at module level)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_tx_analyze_url_minimal():
    url = tx_client.tx_analyze_url(49.96, 6.03)
    assert url == ("https://talaix.com/api/tx/analyze"
                   "?lat=49.96000&lon=6.03000&depth=standard")


def test_tx_analyze_url_hazards_repeated_and_depth():
    url = tx_client.tx_analyze_url(49.96, 6.03, hazards=["wildfire", "flood"],
                                   depth="deep")
    assert url == ("https://talaix.com/api/tx/analyze"
                   "?lat=49.96000&lon=6.03000"
                   "&hazard=wildfire&hazard=flood&depth=deep")


def test_tx_analyze_url_name_quoted():
    url = tx_client.tx_analyze_url(41.5, -8.6, name="Serra da Estrela")
    assert "name=Serra%20da%20Estrela" in url


def test_tx_analyze_url_base_override():
    url = tx_client.tx_analyze_url(0, 0, base="http://localhost:5000")
    assert url.startswith("http://localhost:5000/api/tx/analyze")


def test_tx_analyze_url_with_analyses():
    url = tx_client.tx_analyze_url(49.96, 6.03, hazards=["flood"],
                                   analyses=["insurance", "verification"])
    assert url == ("https://talaix.com/api/tx/analyze"
                   "?lat=49.96000&lon=6.03000"
                   "&hazard=flood&analysis=insurance&analysis=verification"
                   "&depth=standard")


def test_tx_products_registry_ids():
    assert tx_client.TX_PRODUCTS == ["insurance", "sustainability",
                                     "verification"]


# ---------------------------------------------------------------------------
# TxResult normalization
# ---------------------------------------------------------------------------

ENVELOPE = {
    "analysis_id": "TX-20260901-abcd1234",
    "location": {"lat": 49.96, "lon": 6.03, "name": "Clervaux"},
    "depth": "deep",
    "status": "partial",
    "summary": "TX analysis partially complete: 2 hazard(s) ran; …",
    "results": [
        {
            "hazard": "flood",
            "status": "ok",
            "summary": "Elevated flood exposure.",
            "level": {"label": "High", "score": 0.8, "score_max": 1.0,
                      "basis": "ERA5 + DEM", "validated": False},
            "blocks": {},
            "evidence": [{"kind": "modeled"}],
            "provenance": {"source": "fake"},
            "unavailable_reason": None,
            "tx_level": 1,
        },
        {
            "hazard": "dust",
            "status": "unavailable",
            "summary": "No dust cell.",
            "level": None,
            "blocks": {},
            "evidence": [],
            "provenance": {},
            "unavailable_reason": "no coverage at this location",
            "tx_level": 2,
        },
    ],
    "status_counts": {"ok": 1, "unavailable": 1},
    "evidence": [{"kind": "modeled"}],
    "sources": [{"name": "ERA5", "url": "https://example.test/"}],
    "engine_version": "0.1.0",
    "tx_version": "0.1.0",
    "tam_version": "1.0.0",
    "generated_at": "2026-09-01T00:00:00Z",
}


def test_normalize_tx_result_records():
    norm = tx_client.normalize_tx_result(ENVELOPE)
    records = norm["records"]
    assert len(records) == 2

    ok = records[0]
    assert ok["hazard"] == "flood"
    assert ok["status"] == "ok"
    assert ok["level_label"] == "High"
    assert ok["level_score"] == 0.8
    assert ok["level_basis"] == "ERA5 + DEM"
    assert ok["validated"] is False
    assert ok["lat"] == 49.96 and ok["lon"] == 6.03
    assert ok["name"] == "Clervaux"
    assert ok["analysis_id"] == "TX-20260901-abcd1234"
    assert ok["depth"] == "deep"
    assert ok["engine_version"] == "0.1.0"
    assert ok["tx_level"] == 1
    assert records[1]["tx_level"] == 2  # product analyses stamped TX-2+


def test_normalize_tx_result_unavailable_is_honest():
    norm = tx_client.normalize_tx_result(ENVELOPE)
    dust = norm["records"][1]
    assert dust["status"] == "unavailable"
    assert dust["unavailable_reason"] == "no coverage at this location"
    # Missing level block: fields stay None — never invented.
    assert dust["level_label"] is None
    assert dust["level_score"] is None


def test_normalize_tx_result_rows():
    norm = tx_client.normalize_tx_result(ENVELOPE)
    rows = dict(norm["rows"])
    assert rows["analysis_id"] == "TX-20260901-abcd1234"
    assert rows["status"] == "partial"
    assert rows["depth"] == "deep"
    assert "0.1.0" in rows["engine"]
    assert rows["status_counts"] == "ok=1, unavailable=1"
    assert rows["source"] == "ERA5"
    assert "summary" in rows


def test_normalize_tx_result_empty_results():
    norm = tx_client.normalize_tx_result({"analysis_id": "TX-x",
                                          "results": []})
    assert norm["records"] == []
    assert dict(norm["rows"])["analysis_id"] == "TX-x"


# ---------------------------------------------------------------------------
# Wiring markers (QGIS-coupled files are only compile-checked in CI)
# ---------------------------------------------------------------------------

def test_processing_provider_registers_tx_algorithm():
    provider = open(os.path.join(PLUGIN, "processing", "provider.py"),
                    encoding="utf-8").read()
    assert "AnalyzeTxPointAlgorithm" in provider
    algorithm = open(os.path.join(PLUGIN, "processing", "analyze_tx_point.py"),
                     encoding="utf-8").read()
    assert "tx_analyze_url" in algorithm
    assert "normalize_tx_result" in algorithm
    assert "http_get_json" in algorithm  # network stays on the worker thread
    assert "INPUT_ANALYSES" in algorithm  # TX-2+ product analyses selectable

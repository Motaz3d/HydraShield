"""Offline tests for the QGIS Phase 0 plugin spike (qgis-plugin/hydrashield).

QGIS is not available in CI, so these tests cover everything that does not
need a QGIS runtime: the metadata contract, syntax compilation of every
plugin file, the pure (QGIS-free) API-client functions, structural markers
of the QGIS-coupled modules, and the no-secrets rule.
"""

import os
import py_compile
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
PLUGIN = os.path.join(ROOT, "qgis-plugin", "hydrashield")
sys.path.insert(0, PLUGIN)

import api_client  # noqa: E402  (pure module — no qgis imports at module level)


# ---------------------------------------------------------------------------
# metadata.txt contract (official repository requirements)
# ---------------------------------------------------------------------------


@pytest.fixture()
def metadata():
    text = open(os.path.join(PLUGIN, "metadata.txt"), encoding="utf-8").read()
    assert text.startswith("[general]")
    return text


def test_metadata_required_keys(metadata):
    for key in ("name=", "version=", "qgisMinimumVersion=3.40",
                "hasProcessingProvider=yes", "license=GPLv2+",
                "homepage=https://hydrashield.earth",
                "repository=https://github.com/", "tracker=",
                "email=info@hydrashield.earth"):
        assert key in metadata, key


def test_metadata_discloses_account_requirement(metadata):
    """Repo rule: plugins requiring an account must disclose it."""
    assert "account" in metadata.lower()


def test_metadata_experimental_flag(metadata):
    assert "experimental=True" in metadata


# ---------------------------------------------------------------------------
# Syntax compilation (QGIS-coupled files compile without importing qgis)
# ---------------------------------------------------------------------------


def test_all_plugin_files_compile():
    compiled = 0
    for dirpath, _dirs, files in os.walk(PLUGIN):
        for name in files:
            if name.endswith(".py"):
                py_compile.compile(os.path.join(dirpath, name), doraise=True)
                compiled += 1
    assert compiled >= 6


# ---------------------------------------------------------------------------
# Pure API-client functions (no QGIS needed)
# ---------------------------------------------------------------------------


def test_urls():
    assert api_client.hazards_url() == "https://hydrashield.earth/api/v2/hazards"
    url = api_client.analyze_url("flood", 37.389213, -5.984512, "Sevilla")
    assert url.startswith("https://hydrashield.earth/api/v2/analyze?hazard=flood")
    assert "lat=37.38921" in url and "lon=-5.98451" in url
    assert "name=Sevilla" in url


def test_normalize_hazard_descriptor():
    descriptor = {
        "id": "wildfire", "name": "Wildfire", "enabled": True,
        "analysis": {"available": True, "reason": None},
        "events": {"available": False, "reason": "key not configured"},
        "sources": [{"name": "NASA FIRMS",
                     "url": "https://firms.modaps.eosdis.nasa.gov/"}],
        "provenance": {"module": "src.climate.hazards.wildfire.WildfireModule",
                       "indicator_status": "screening"},
    }
    h = api_client.normalize_hazard(descriptor)
    assert h["id"] == "wildfire" and h["enabled"] is True
    assert h["analysis_available"] is True
    assert h["events_available"] is False
    assert h["events_reason"] == "key not configured"
    assert h["sources"] == [("NASA FIRMS",
                             "https://firms.modaps.eosdis.nasa.gov/")]


def test_normalize_analysis_preserves_honesty_fields():
    payload = {
        "hazard": "heat", "status": "ok", "summary": "Heat screening",
        "level": {"label": "High", "score": 94.9, "score_max": 100.0,
                  "basis": "percentile vs 1991-2020", "validated": False},
        "location": {"lat": 37.4, "lon": -6.0, "name": "Andalusia"},
        "provenance": {"weather": {"source": "ERA5 via Open-Meteo"}},
    }
    out = api_client.normalize_analysis(payload)
    rec = out["record"]
    assert rec["level_label"] == "High"
    assert rec["level_score"] == 94.9
    assert rec["validated"] is False
    assert rec["unavailable_reason"] is None
    rows = dict(out["rows"])
    assert rows["validated"] == "False"
    assert rows["source:weather"] == "ERA5 via Open-Meteo"


def test_normalize_analysis_unavailable_stays_honest():
    payload = {"hazard": "flood", "status": "unavailable",
               "unavailable_reason": "archive down", "level": None}
    rec = api_client.normalize_analysis(payload)["record"]
    assert rec["status"] == "unavailable"
    assert rec["unavailable_reason"] == "archive down"
    assert rec["level_score"] is None  # never invented


# ---------------------------------------------------------------------------
# Structural markers + no secrets
# ---------------------------------------------------------------------------


def test_provider_and_algorithm_structure():
    provider_src = open(os.path.join(PLUGIN, "processing", "provider.py"),
                        encoding="utf-8").read()
    assert "QgsProcessingProvider" in provider_src
    assert '"hydrashield"' in provider_src
    algo_src = open(os.path.join(PLUGIN, "processing", "analyze_point.py"),
                    encoding="utf-8").read()
    assert "QgsProcessingAlgorithm" in algo_src
    assert '"analyze_point"' in algo_src
    assert "EPSG:4326" in algo_src


def test_no_secrets_in_plugin_source():
    """No tokens/passwords may live in the plugin (authcfg ids only)."""
    import re
    pattern = re.compile(r"(api[_-]?key|token|password|secret)\s*=\s*['\"][^'\"]{8,}",
                         re.IGNORECASE)
    for dirpath, _dirs, files in os.walk(PLUGIN):
        for name in files:
            if name.endswith((".py", ".txt")):
                text = open(os.path.join(dirpath, name),
                            encoding="utf-8").read()
                assert not pattern.search(text), name


def test_network_uses_qgis_network_access_manager():
    src = open(os.path.join(PLUGIN, "api_client.py"), encoding="utf-8").read()
    assert "QgsNetworkAccessManager" in src
    # Official guidance: no requests/urllib for HTTP in the network path.
    assert "import requests" not in src

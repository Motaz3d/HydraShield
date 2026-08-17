"""
Offline tests for the Compound empirical dependence analysis
(src/climate/compound.py::dependence_analysis), the evidence-backed
Cascading Risk Graph edges (config/cascading_graph.json +
src/climate/cascading.py validator), and the Loss Data Registry
(config/loss_registry.json + src/climate/losses.py + src/climate/api_losses.py).

No network: daily series are synthetic fixtures; assess_compound runs with
monkeypatched signal extraction and dependence-series fetcher. The losses
blueprint is tested via a Flask app registering losses_bp directly.
"""

import copy
import json
import os
from datetime import date, timedelta

import pytest

# Isolate the cache DB for the whole test module.
os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_losses_dep_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from flask import Flask  # noqa: E402

from src.climate import cascading as cascading_module  # noqa: E402
from src.climate import compound as compound_module  # noqa: E402
from src.climate import losses as losses_module  # noqa: E402
from src.climate.api_losses import losses_bp  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic daily series with a KNOWN co-occurrence structure
# ---------------------------------------------------------------------------
#
# 8 years of sequential days from 2010-01-01 (2920 days, leap days of 2012
# and 2016 included in the calendar but never in the generated range). One
# calendar year (2013, not a leap year) is hot and high-FWI; all other days
# are mild and low-FWI. Precipitation is constant, so the drought indicator
# has a zero-variance baseline and fires nowhere (honest no-event).
#
# Known truth: heat event days = FWI event days = the 365 days of 2013, so
# P(A) = P(B) = P(A∩B) = 365/2920 = 0.125 and lift = 1/0.125 = 8.0 exactly.

_HOT_YEAR = 2013
_N_DAYS = 8 * 365


def _synthetic_series():
    start = date(2010, 1, 1)
    dates, tmax, pr, fwi = [], [], [], []
    for i in range(_N_DAYS):
        d = start + timedelta(days=i)
        dates.append(d.isoformat())
        hot = d.year == _HOT_YEAR
        tmax.append(30.0 if hot else 20.0)
        pr.append(10.0)
        fwi.append(35.0 if hot else 5.0)
    return dates, tmax, pr, fwi


def _series_dict(dates, tmax, pr, fwi):
    return {
        "heat": {"dates": dates, "values": tmax},
        "drought": {"dates": dates, "values": pr},
        "wildfire": {"dates": dates, "values": fwi},
    }


# ---------------------------------------------------------------------------
# dependence_analysis
# ---------------------------------------------------------------------------


def test_dependence_lift_from_known_cooccurrence():
    dates, tmax, pr, fwi = _synthetic_series()
    out = compound_module.dependence_analysis(
        _series_dict(dates, tmax, pr, fwi), window_years=8)

    pair = out["pairs"]["heat_wildfire"]
    assert pair["status"] == "ok"
    # Real counts from the synthetic record.
    assert pair["n_days_total"] == _N_DAYS
    assert pair["n_A"] == 365
    assert pair["n_B"] == 365
    assert pair["n_AB"] == 365
    # Empirical frequencies and lift.
    assert pair["P_A"] == pytest.approx(0.125, abs=1e-4)
    assert pair["P_B"] == pytest.approx(0.125, abs=1e-4)
    assert pair["P_AB"] == pytest.approx(0.125, abs=1e-4)
    assert pair["lift"] == pytest.approx(8.0, abs=1e-3)
    # Honest labelling.
    assert out["claim_status"] == "MODELLED"
    assert "NOT a fitted dependence model" in out["method"]
    assert "no causal claim" in out["method"]
    assert "small-count guard" in out["small_count_guard"]
    # Honest significance note instead of pseudo-precise p-values.
    assert "No significance testing" in out["significance_note"]
    for pair_out in out["pairs"].values():
        assert "p_value" not in pair_out
        assert "pvalue" not in pair_out
    # No compound score anywhere in the dependence block.
    assert "score" not in out
    assert "score" not in json.dumps(out)


def test_dependence_small_count_guard():
    dates, tmax, pr, fwi = _synthetic_series()
    # FWI never reaches the threshold: 0 event days -> guard, never a number.
    out = compound_module.dependence_analysis(
        _series_dict(dates, tmax, pr, [1.0] * _N_DAYS), window_years=8)
    pair = out["pairs"]["heat_wildfire"]
    assert pair["status"] == "insufficient_data"
    assert pair["n_B"] == 0
    assert pair["n_days_total"] == _N_DAYS  # real counts still reported
    assert pair["lift"] is None
    assert pair["P_A"] is None and pair["P_B"] is None and pair["P_AB"] is None
    assert "small-count guard" in pair["reason"]

    # The constant-precipitation record yields zero drought event days
    # (zero-variance baseline -> honest no-event), so both drought pairs
    # are guarded as well.
    assert out["pairs"]["heat_drought"]["status"] == "insufficient_data"
    assert out["pairs"]["drought_wildfire"]["status"] == "insufficient_data"
    assert out["status"] == "unavailable"  # no pair computable


def test_dependence_guard_boundary_at_min_event_days():
    dates, tmax, pr, fwi = _synthetic_series()
    # Exactly 10 FWI event days (the guard minimum) -> computable. They do
    # not overlap the 2013 heat events, so the empirical lift is honestly 0.
    fwi10 = [35.0 if i < 10 else 5.0 for i in range(_N_DAYS)]
    out10 = compound_module.dependence_analysis(
        _series_dict(dates, tmax, pr, fwi10), window_years=8)
    pair10 = out10["pairs"]["heat_wildfire"]
    assert pair10["n_B"] == 10
    assert pair10["status"] == "ok"
    assert pair10["n_AB"] == 0
    assert pair10["lift"] == 0.0

    # 9 event days -> below the guard: insufficient_data, never a number.
    fwi9 = [35.0 if i < 9 else 5.0 for i in range(_N_DAYS)]
    out9 = compound_module.dependence_analysis(
        _series_dict(dates, tmax, pr, fwi9), window_years=8)
    pair9 = out9["pairs"]["heat_wildfire"]
    assert pair9["n_B"] == 9
    assert pair9["status"] == "insufficient_data"
    assert pair9["lift"] is None
    assert pair9["P_AB"] is None


def test_dependence_missing_series_is_unavailable_not_a_crash():
    dates, tmax, pr, fwi = _synthetic_series()
    out = compound_module.dependence_analysis(
        {"heat": {"dates": dates, "values": tmax}}, window_years=8)
    assert out["status"] == "unavailable"
    for key, pair in out["pairs"].items():
        assert pair["status"] == "unavailable"
        assert pair["lift"] is None
        assert "daily series unavailable" in pair["reason"]
    assert set(out["series_unavailable"]) == {"drought", "wildfire"}
    # Empty input degrades the same honest way.
    out_empty = compound_module.dependence_analysis({})
    assert out_empty["status"] == "unavailable"
    assert all(p["status"] == "unavailable" for p in out_empty["pairs"].values())


# ---------------------------------------------------------------------------
# assess_compound wiring (monkeypatched fetchers — offline)
# ---------------------------------------------------------------------------


def _sig(hazard, elevated=False, values=None):
    return {
        "hazard": hazard,
        "status": "ok",
        "level": {"label": "Low", "score": None, "score_max": None,
                  "basis": "synthetic fixture", "validated": False},
        "elevated": elevated,
        "elevated_basis": f"synthetic {hazard} breach" if elevated else None,
        "values": values or {},
        "spells": [],
        "spell_kind": None,
        "spell_status": {"ongoing": False},
        "evidence": [{"evidence_class": "OPEN_DATA_OFFICIAL",
                      "claim_status": "MODELLED", "temporal": "HISTORICAL",
                      "source": f"synthetic {hazard} source"}],
        "source": f"synthetic {hazard} source",
        "summary": f"synthetic {hazard} signal",
        "unavailable_reason": None,
    }


def _extracted(signals):
    return {
        "location": {"lat": 10.0, "lon": 20.0},
        "generated_at": "2026-08-17T00:00:00Z",
        "as_of": "2026-08-12",
        "signals": signals,
        "hazards_unavailable": [],
        "thresholds": dict(compound_module.ELEVATED_THRESHOLDS),
    }


def test_assess_compound_includes_dependence_block(monkeypatch):
    signals = {
        "heat": _sig("heat", elevated=True,
                     values={"percentile_vs_doy_climatology": 95.0}),
        "wildfire": _sig("wildfire", elevated=True,
                         values={"fwi_latest": 35.0,
                                 "fwi_latest_date": "2026-08-12"}),
    }
    monkeypatch.setattr(compound_module, "extract_light_signals",
                        lambda *a, **k: _extracted(signals))
    dates, tmax, pr, fwi = _synthetic_series()
    monkeypatch.setattr(compound_module, "_dependence_series", lambda *a, **k: {
        "window": {"start": dates[0], "end": dates[-1]},
        "series_by_hazard": _series_dict(dates, tmax, pr, fwi),
        "source": "synthetic ERA5 archive",
    })

    out = compound_module.assess_compound.__wrapped__(12.345, 54.321)
    dep = out["dependence"]
    assert dep["status"] == "partial"  # heat_wildfire ok, drought pairs guarded
    assert dep["source"] == "synthetic ERA5 archive"
    assert dep["claim_status"] == "MODELLED"
    pair = dep["pairs"]["heat_wildfire"]
    assert pair["status"] == "ok"
    assert pair["lift"] == pytest.approx(8.0, abs=1e-3)
    assert dep["pairs"]["heat_drought"]["status"] == "insufficient_data"
    # Typology signals are untouched and no compound score appeared.
    assert [s["type"] for s in out["compound_signals"]] == ["multivariate"]
    assert "score" not in out
    assert "score" not in dep
    assert any("dependence block" in lim for lim in out["limitations"])


def test_assess_compound_dependence_failure_is_honest(monkeypatch):
    signals = {"heat": _sig("heat")}
    monkeypatch.setattr(compound_module, "extract_light_signals",
                        lambda *a, **k: _extracted(signals))
    monkeypatch.setattr(compound_module, "_dependence_series",
                        lambda *a, **k: {"error": "synthetic archive down"})

    out = compound_module.assess_compound.__wrapped__(12.346, 54.322)
    dep = out["dependence"]
    assert dep["status"] == "unavailable"
    assert "synthetic archive down" in dep["reason"]
    assert dep["pairs"] == {}
    assert dep["method"]
    # The rest of the assessment is unaffected.
    assert out["status"] == "ok"
    assert "score" not in out


# ---------------------------------------------------------------------------
# Cascading graph: evidence blocks on every edge
# ---------------------------------------------------------------------------


def test_cascade_config_validates_with_evidence_on_all_edges():
    graph = cascading_module.load_cascading_graph()
    assert cascading_module.validate_cascading_graph(graph) == []
    assert graph["edges"], "graph must have edges"
    for edge in graph["edges"]:
        ev = edge.get("evidence")
        assert isinstance(ev, dict), f"edge {edge['from']}->{edge['to']}: no evidence"
        assert ev["class"] in ("SCIENTIFIC", "OPEN_DATA_OFFICIAL")
        assert ev["class"] == edge["evidence_class"]
        assert isinstance(ev["basis"], str) and ev["basis"].strip()
        assert ev["confidence"] in ("high", "medium", "low")
        assert isinstance(ev["limitations"], str) and ev["limitations"].strip()
        assert edge["quantified"] is False
        assert edge["mechanism"]


def test_cascade_validator_requires_evidence_block_and_vocabulary():
    graph = cascading_module.load_cascading_graph()

    missing = copy.deepcopy(graph)
    del missing["edges"][0]["evidence"]
    problems = cascading_module.validate_cascading_graph(missing)
    assert any("evidence block" in p for p in problems)

    bad_conf = copy.deepcopy(graph)
    bad_conf["edges"][0]["evidence"]["confidence"] = "very-high"
    problems = cascading_module.validate_cascading_graph(bad_conf)
    assert any("evidence.confidence" in p for p in problems)

    bad_class = copy.deepcopy(graph)
    bad_class["edges"][0]["evidence"]["class"] = "MEDIA"
    problems = cascading_module.validate_cascading_graph(bad_class)
    assert any("evidence.class" in p for p in problems)

    mismatched = copy.deepcopy(graph)
    edge = mismatched["edges"][0]
    edge["evidence"]["class"] = (
        "OPEN_DATA_OFFICIAL" if edge["evidence_class"] == "SCIENTIFIC"
        else "SCIENTIFIC")
    problems = cascading_module.validate_cascading_graph(mismatched)
    assert any("must match" in p for p in problems)

    no_basis = copy.deepcopy(graph)
    no_basis["edges"][0]["evidence"]["basis"] = ""
    problems = cascading_module.validate_cascading_graph(no_basis)
    assert any("evidence.basis" in p for p in problems)


def _synthetic_exposure():
    def _cat(count, desc):
        return {"status": "mapped", "count": count, "description": desc,
                "source": "OpenStreetMap via ohsome API (Heidelberg Institute)",
                "completeness_caveat": "OSM completeness varies by region.",
                "analysis_window": "current conditions"}

    return {
        "location": {"lat": 0.0, "lon": 0.0},
        "radius_km": 5.0,
        "analysis_window": "current conditions",
        "exposure": {
            "buildings": _cat(214, "buildings"),
            "critical_facilities": {
                "status": "mapped", "count": 8,
                "breakdown": {"hospitals": 2, "schools": 5, "fire_stations": 1},
                "source": "OSM", "completeness_caveat": "varies"},
            "transport": _cat(130, "roads"),
            "energy": _cat(3, "power"),
            "water": _cat(6, "water"),
        },
        "monetary_quantification": {"status": "not_quantified"},
        "provenance": {"evidence": [{"source": "synthetic exposure evidence"}]},
    }


def test_cascading_paths_carry_edge_evidence(monkeypatch):
    signals = {
        "wildfire": _sig("wildfire", elevated=True,
                         values={"fwi_latest": 35.0}),
        "heat": _sig("heat", elevated=False,
                     values={"percentile_vs_doy_climatology": 50.0}),
    }
    monkeypatch.setattr(cascading_module, "extract_light_signals",
                        lambda *a, **k: _extracted(signals))
    monkeypatch.setattr(cascading_module, "build_economic_exposure",
                        lambda *a, **k: _synthetic_exposure())

    out = cascading_module.assess_cascading.__wrapped__(55.555, 66.666)
    assert out["status"] == "ok"
    assert out["cascade_paths"]
    for path in out["cascade_paths"]:
        for edge in path["edges"]:
            ev = edge["evidence"]
            assert ev["class"] == edge["evidence_class"]
            assert ev["confidence"] in ("high", "medium", "low")
            assert ev["basis"] and ev["limitations"]
        assert path["not_quantified_statement"]
    grid_path = next(p for p in out["cascade_paths"]
                     if p["nodes"] == ["wildfire", "power_grid", "hospitals"])
    first_edge = grid_path["edges"][0]
    assert first_edge["from"] == "wildfire" and first_edge["to"] == "power_grid"
    assert first_edge["evidence"]["class"] == "SCIENTIFIC"


# ---------------------------------------------------------------------------
# Loss Data Registry
# ---------------------------------------------------------------------------


_EXPECTED_SOURCE_IDS = {
    "emdat", "desinventar", "undrr", "worldbank_data", "gfdrr",
    "noaa_billions", "munichre_natcat", "swissre_sigma",
}


def test_loss_registry_loads_candidates_only():
    registry = losses_module.load_loss_registry()
    assert losses_module.validate_loss_registry(registry) == []
    assert registry["observed_events"] == []
    sources = registry["sources"]
    assert {s["id"] for s in sources} == _EXPECTED_SOURCE_IDS
    for src in sources:
        assert src["status"] == "candidate"
        assert src["url"].startswith("https://")
        assert src["access"] in ("registration_required", "api", "download")
        assert src["provider"] and src["coverage"] and src["status_note"]
    assert "strictly separated" in registry["separation_note"]


def test_loss_summary_separation_and_exact_statement():
    summary = losses_module.loss_summary()
    observed = summary["observed_losses"]
    assert observed["status"] == "unavailable"
    assert observed["statement"] == "No documented loss figures in integrated sources."
    assert set(observed["sources_reviewed"]) == _EXPECTED_SOURCE_IDS
    for block in ("estimated_losses", "modelled_losses", "projected_losses"):
        assert summary[block]["status"] == "not_available"
        assert summary[block]["statement"]
    meta = summary["registry"]
    assert meta["source_count"] == len(_EXPECTED_SOURCE_IDS)
    assert meta["observed_event_count"] == 0
    assert meta["sources_by_status"] == {"candidate": len(_EXPECTED_SOURCE_IDS)}
    # No monetary figure leaks anywhere in the payload.
    blob = json.dumps(summary)
    assert "€" not in blob and "$" not in blob


# ---------------------------------------------------------------------------
# /api/v2/losses endpoints (blueprint registered directly on a test app)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    app = Flask("test_losses")
    app.config["TESTING"] = True
    app.register_blueprint(losses_bp)
    with app.test_client() as c:
        yield c


def test_losses_endpoint(client):
    resp = client.get("/api/v2/losses")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["observed_losses"]["status"] == "unavailable"
    assert data["observed_losses"]["statement"] == (
        "No documented loss figures in integrated sources.")
    assert set(data["observed_losses"]["sources_reviewed"]) == _EXPECTED_SOURCE_IDS
    for block in ("estimated_losses", "modelled_losses", "projected_losses"):
        assert data[block]["status"] == "not_available"
    assert data["separation_note"]


def test_losses_sources_endpoint(client):
    resp = client.get("/api/v2/losses/sources")
    assert resp.status_code == 200
    data = resp.get_json()
    sources = data["sources"]
    assert data["source_count"] == len(_EXPECTED_SOURCE_IDS)
    assert {s["id"] for s in sources} == _EXPECTED_SOURCE_IDS
    for src in sources:
        assert src["status"] == "candidate"
        assert src["url"].startswith("https://")
    assert "none is integrated" in data["note"]

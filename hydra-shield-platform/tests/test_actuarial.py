"""Tests for the actuarial layer (src/climate/actuarial.py) and its wiring
into the insurance product engine and the TX envelope.

Fully offline: math is checked against published reference values; the
insurance/TX integration stubs hazard modules via monkeypatch + registry
reset (same pattern as tests/test_insurance.py).
"""

import math
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_actuarial_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import actuarial as ac  # noqa: E402
from src.climate import registry  # noqa: E402
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402


# ---------------------------------------------------------------------------
# Special functions vs published reference values
# ---------------------------------------------------------------------------

def test_chi2_ppf_known_values():
    assert ac.chi2_ppf(0.95, 10) == pytest.approx(18.3070, abs=1e-3)
    assert ac.chi2_ppf(0.05, 10) == pytest.approx(3.9403, abs=1e-3)
    assert ac.chi2_ppf(0.975, 2) == pytest.approx(7.3778, abs=1e-3)
    assert ac.chi2_ppf(0.95, 4) == pytest.approx(9.4877, abs=1e-3)


def test_chi2_cdf_roundtrip():
    for df in (1, 2, 10, 40):
        x = ac.chi2_ppf(0.9, df)
        assert ac.chi2_cdf(x, df) == pytest.approx(0.9, abs=1e-9)


def test_gammainc_edges():
    assert ac.gammainc_p(2.0, 0.0) == 0.0
    with pytest.raises(ValueError):
        ac.gammainc_p(0.0, 1.0)
    with pytest.raises(ValueError):
        ac.gammainc_p(1.0, -1.0)
    with pytest.raises(ValueError):
        ac.chi2_ppf(0.0, 5)
    with pytest.raises(ValueError):
        ac.chi2_ppf(1.0, 5)


# ---------------------------------------------------------------------------
# Frequency estimation
# ---------------------------------------------------------------------------

def test_poisson_count_ci_published_values():
    # Garwood/Pearson–Klugman exact intervals (standard statistical tables).
    lo, hi = ac.poisson_count_ci(10, 0.95)
    assert lo == pytest.approx(4.795, abs=1e-2)
    assert hi == pytest.approx(18.39, abs=1e-2)
    lo, hi = ac.poisson_count_ci(10, 0.90)
    assert lo == pytest.approx(5.425, abs=1e-2)
    assert hi == pytest.approx(16.962, abs=1e-2)


def test_poisson_count_ci_zero_events_rule_of_three():
    # n=0 at 90% confidence → upper ≈ 3 (0.5·χ²(0.95, 2) = 2.996).
    lo, hi = ac.poisson_count_ci(0, 0.90)
    assert lo == 0.0
    assert hi == pytest.approx(2.996, abs=1e-2)


def test_frequency_estimate_math():
    est = ac.frequency_estimate(5, 25.0)
    assert est["lambda_per_year"] == pytest.approx(0.2)
    assert est["ci_lower"] < 0.2 < est["ci_upper"]
    assert est["tier"] == "moderate"
    assert est["low_count"] is False
    assert "Poisson" in est["method"]


def test_frequency_tier_ladder():
    assert ac.frequency_tier(0.001) == "very_low"
    assert ac.frequency_tier(0.05) == "low"
    assert ac.frequency_tier(0.3) == "moderate"
    assert ac.frequency_tier(0.9) == "high"
    assert ac.frequency_tier(2.0) == "very_high"


def test_frequency_estimate_rejects_bad_coverage():
    with pytest.raises(ValueError):
        ac.frequency_estimate(3, 0.0)


# ---------------------------------------------------------------------------
# Exceedance probabilities / return periods
# ---------------------------------------------------------------------------

def test_exceedance_math():
    lam = 0.2
    aep = ac.annual_exceedance_probability(lam)
    assert aep == pytest.approx(1 - math.exp(-0.2), abs=1e-12)
    assert ac.horizon_exceedance_probability(lam, 10) == pytest.approx(
        1 - math.exp(-2.0), abs=1e-12)
    assert ac.return_period_years(aep) == pytest.approx(1 / aep, abs=1e-9)
    assert ac.return_period_years(0.0) is None
    with pytest.raises(ValueError):
        ac.horizon_exceedance_probability(lam, 0)


# ---------------------------------------------------------------------------
# Severity extraction + statistics
# ---------------------------------------------------------------------------

def test_extract_severity_flat_nested_categorical():
    events = [
        {"id": "a", "magnitude": 5.1, "severity": {"max_frp_mw": 100, "detections": 4},
         "alertlevel": "Red"},
        {"id": "b", "magnitude": "4.0", "severity": {"max_frp_mw": 50.5},
         "alertlevel": "red"},
        {"id": "c", "severity": "high", "category": True},  # bool is not a metric
    ]
    out = ac.extract_severity(events)
    assert out["metrics"]["magnitude"] == [5.1, 4.0]
    assert out["metrics"]["severity.max_frp_mw"] == [100.0, 50.5]
    assert out["metrics"]["severity.detections"] == [4.0]
    assert out["labels"] == {"red": 2, "high": 1}
    assert "category" not in out["metrics"]


def test_severity_stats():
    stats = ac.severity_stats([10, 20, 30])
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(20.0)
    assert stats["std"] == pytest.approx(10.0, abs=1e-9)
    assert stats["cv"] == pytest.approx(0.5, abs=1e-9)
    assert ac.severity_stats([]) is None
    assert ac.severity_stats([7])["std"] == 0.0


def test_collective_risk_moments():
    m = ac.collective_risk_moments(0.2, 10.0, 25.0)
    assert m["expected_annual_index"] == pytest.approx(2.0)      # λ·E[X]
    assert m["variance_annual_index"] == pytest.approx(25.0)     # λ·E[X²] = 0.2·125
    assert m["std_annual_index"] == pytest.approx(5.0)
    assert "non-monetary" in m["unit"]


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------

def test_coverage_years_from():
    cov = ac.coverage_years_from({"default": {"start": "2000-01-01", "end": "2024-12-31"}})
    assert cov["years"] == pytest.approx(25.0, abs=0.01)
    assert ac.coverage_years_from(None) is None
    assert ac.coverage_years_from({}) is None
    assert ac.coverage_years_from({"x": {"start": "nope", "end": "2024-01-01"}}) is None
    assert ac.coverage_years_from({"x": {"start": "2024-01-01", "end": "2000-01-01"}}) is None


# ---------------------------------------------------------------------------
# Per-peril actuarial block — honesty paths
# ---------------------------------------------------------------------------

_COVERAGE = {"default": {"start": "2000-01-01", "end": "2024-12-31"}}


def test_peril_actuarial_ok_path():
    events = [
        {"id": "e1", "date": "2020-01-01", "severity": {"max_frp_mw": 120.0, "detections": 8}},
        {"id": "e2", "date": "2019-06-01", "severity": {"max_frp_mw": 40.0, "detections": 3}},
        {"id": "e3", "date": "2015-03-01", "severity": "high"},
    ]
    block = ac.build_peril_actuarial(
        hazard_id="wildfire", peril_label="Wildfire",
        events_status="ok", events_count=3, events=events,
        temporal_coverage=_COVERAGE, radius_km=50.0,
    )
    assert block["status"] == "ok"
    assert block["frequency"]["lambda_per_year"] == pytest.approx(3 / 25, abs=1e-3)
    assert block["annual_exceedance_probability"] == pytest.approx(
        1 - math.exp(-3 / 25), abs=1e-3)
    assert block["return_period_years"] is not None
    assert set(block["horizon_probabilities"]) == {"5y", "10y", "25y"}
    assert block["severity"]["status"] == "ok"
    assert block["severity"]["metrics"]["severity.max_frp_mw"]["n"] == 2
    assert block["severity"]["labels"] == {"high": 1}
    assert block["collective_risk"]["severity_metric"] == "severity.max_frp_mw"
    assert block["frequency"]["low_count"] is True
    assert any("credibility" in n for n in block["notes"])


def test_peril_actuarial_events_unavailable_is_honest():
    block = ac.build_peril_actuarial(
        hazard_id="flood", peril_label="Flood",
        events_status="unavailable", events_count=0,
        temporal_coverage=_COVERAGE, radius_km=50.0,
    )
    assert block["status"] == "unavailable"
    assert "flood" in block["unavailable_reason"]
    assert block["frequency"] is None


def test_peril_actuarial_missing_coverage_partial_when_severity():
    block = ac.build_peril_actuarial(
        hazard_id="wind", peril_label="Windstorm",
        events_status="ok", events_count=2,
        events=[{"severity": {"wind_kmh": 90}}, {"severity": {"wind_kmh": 110}}],
        temporal_coverage=None, radius_km=50.0,
    )
    assert block["status"] == "partial"
    assert "temporal coverage" in block["unavailable_reason"]
    assert block["frequency"] is None
    assert block["severity"]["status"] == "ok"


def test_peril_actuarial_zero_events_never_claims_zero_risk():
    block = ac.build_peril_actuarial(
        hazard_id="coastal", peril_label="Coastal",
        events_status="ok", events_count=0, events=[],
        temporal_coverage=_COVERAGE, radius_km=50.0,
    )
    assert block["status"] == "ok"
    assert block["frequency"]["lambda_per_year"] == 0.0
    assert block["frequency"]["ci_upper"] > 0.0           # upper bound still admits events
    assert block["annual_exceedance_probability"] == 0.0
    assert block["return_period_years"] is None
    assert any("does NOT imply zero risk" in n for n in block["notes"])
    assert block["collective_risk"]["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Cross-peril account aggregate
# ---------------------------------------------------------------------------

def _ok_peril(hazard: str, lam_events: int) -> dict:
    return ac.build_peril_actuarial(
        hazard_id=hazard, peril_label=hazard.title(),
        events_status="ok", events_count=lam_events, events=[],
        temporal_coverage=_COVERAGE, radius_km=50.0,
    )


def test_account_actuarial_aggregates():
    perils = [_ok_peril("flood", 5), _ok_peril("wildfire", 0),
              ac.build_peril_actuarial(
                  hazard_id="wind", peril_label="Windstorm",
                  events_status="unavailable", events_count=0)]
    summary = ac.build_account_actuarial(perils, peril_levels={"flood": "High"})
    assert summary["status"] == "ok"
    assert summary["perils_quantified"] == 2
    assert summary["perils_total"] == 3
    assert summary["expected_annual_events_all_perils"] == pytest.approx(5 / 25, abs=1e-3)
    p_flood = 1 - math.exp(-5 / 25)
    assert summary["any_peril_annual_exceedance_probability"] == pytest.approx(p_flood, abs=1e-3)
    assert summary["dominant_peril"]["hazard"] == "flood"
    assert summary["elevated_current_levels"] == ["flood"]
    assert summary["text"]


def test_account_actuarial_all_unavailable_is_honest():
    summary = ac.build_account_actuarial([
        ac.build_peril_actuarial(
            hazard_id="wind", peril_label="Windstorm",
            events_status="unavailable", events_count=0)
    ])
    assert summary["status"] == "unavailable"
    assert summary["unavailable_reason"]


# ---------------------------------------------------------------------------
# Reference (formulas + bilingual glossary)
# ---------------------------------------------------------------------------

def test_actuarial_reference_structure():
    ref = ac.actuarial_reference()
    assert ref["actuarial_version"] == ac.ACTUARIAL_VERSION
    assert ref["formula_count"] == len(ref["formulas"]) >= 15
    assert ref["term_count"] == len(ref["glossary"]) >= 40
    categories = {t["category"] for t in ref["glossary"]}
    assert set(ref["categories"]) == categories
    for term in ref["glossary"]:
        assert term["term_en"] and term["term_ar"]
        assert term["def_en"] and term["def_ar"]
    ids = {f["id"] for f in ref["formulas"]}
    for required in ("pure_premium", "annual_exceedance", "return_period",
                     "combined_ratio", "xl_recovery", "var_tvar", "ep_curve"):
        assert required in ids
    for f in ref["formulas"]:
        assert f["name_ar"] and f["use_ar"] and f["formula"]


# ---------------------------------------------------------------------------
# Insurance product integration (stubbed hazard modules, offline)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


class _FakeOkEventsModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="ok",
            summary=f"{self.id} screening ok",
            level=HazardLevel(label="High", score=0.8, score_max=1.0,
                              basis="modelled screening indicator", validated=False),
            evidence=[{"evidence_class": "MODELLED", "claim_status": "MODELLED",
                       "temporal": "OBSERVED", "source": "Fake source"}],
            provenance={"model": {"source": "Fake"}},
        )

    def events(self, lat, lon, radius_km=50.0, year=None):
        return {
            "hazard": self.id,
            "status": "ok",
            "events": [
                {"id": "ev1", "date": "2020-06-15", "severity": {"max_frp_mw": 120.0}},
                {"id": "ev2", "date": "2019-07-22", "severity": "high"},
            ],
        }

    def temporal_coverage(self):
        return {"default": {"start": "2000-01-01", "end": "2024-12-31"}}


class _FakeNoEventsModule(_FakeOkEventsModule):
    def events(self, lat, lon, radius_km=50.0, year=None):
        raise ValueError("events database offline")


def _stub_registry(monkeypatch):
    def fake_get(hazard_id: str):
        if hazard_id in ("flood", "wildfire"):
            return _FakeOkEventsModule(hazard_id)
        if hazard_id == "wind":
            return _FakeNoEventsModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


def test_profile_carries_actuarial_layer(monkeypatch):
    _stub_registry(monkeypatch)
    from src.climate.insurance import build_risk_profile

    profile = build_risk_profile(1.0, 2.0, name="Asset", radius_km=25)
    assert profile["loss_quantification"] == "not_quantified"   # unchanged rule

    perils = {p["hazard"]: p for p in profile["perils"]}
    flood = perils["flood"]["actuarial"]
    assert flood["status"] == "ok"
    assert flood["frequency"]["lambda_per_year"] == pytest.approx(2 / 25, abs=1e-3)
    assert flood["severity"]["metrics"]["severity.max_frp_mw"]["n"] == 1
    assert flood["severity"]["labels"] == {"high": 1}

    wind = perils["wind"]["actuarial"]
    assert wind["status"] == "unavailable"
    assert wind["frequency"] is None

    summary = profile["actuarial_summary"]
    assert summary["status"] == "ok"
    assert summary["perils_quantified"] == 2          # flood + wildfire
    assert summary["dominant_peril"]["hazard"] in ("flood", "wildfire")
    assert summary["expected_annual_events_all_perils"] == pytest.approx(4 / 25, abs=1e-3)

    ref = profile["actuarial_reference"]
    assert ref["term_count"] >= 40 and ref["formula_count"] >= 15


def test_portfolio_profile_carries_actuarial(monkeypatch):
    _stub_registry(monkeypatch)
    from src.climate.insurance import build_portfolio_profile

    out = build_portfolio_profile(
        [{"name": "A", "lat": 1.0, "lon": 2.0}, {"name": "B", "lat": 3.0, "lon": 4.0}],
        radius_km=25,
    )
    assert out["loss_quantification"] == "not_quantified"
    act = out["portfolio_summary"]["actuarial"]
    assert act["sites_with_quantified_perils"] == 2
    assert 0.0 < act["any_site_any_peril_aep"] <= 1.0
    assert act["independence_caveat"]
    for r in out["results"]:
        assert r["actuarial"]["perils_quantified"] == 2
        assert r["actuarial"]["dominant_peril"]["hazard"]


def test_tx_engine_envelope_carries_actuarial(monkeypatch):
    """The TX product path (tx_core → adapters.products → build_risk_profile)
    surfaces the actuarial blocks in results[].blocks unchanged."""
    _stub_registry(monkeypatch)
    from tx_core.engine import TXEngine

    engine = TXEngine()
    result = engine.analyze(lat=1.0, lon=2.0, hazards=["no-such-hazard"],
                            analyses=["insurance"])
    assert [r.hazard for r in result.results] == ["insurance"]
    product = result.results[0]
    assert product.status == "ok"
    assert product.tx_level == 2
    assert "actuarial_summary" in product.blocks
    assert "actuarial_reference" in product.blocks
    assert product.blocks["loss_quantification"] == "not_quantified"
    flood = {p["hazard"]: p for p in product.blocks["perils"]}["flood"]
    assert flood["actuarial"]["status"] == "ok"
    # Envelope serialises cleanly with the new blocks.
    d = result.to_dict()
    assert d["results"][0]["blocks"]["actuarial_summary"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Trend-adjusted frequency (non-homogeneous Poisson GLM)
# ---------------------------------------------------------------------------

def _pois(lam: float, rng) -> int:
    L = math.exp(-lam)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def _planted_years(slope: float, seed: int = 11, base: float = -1.2):
    import random

    rng = random.Random(seed)
    years = []
    for yr in range(2000, 2025):
        years.extend([yr] * _pois(math.exp(base + slope * (yr - 2012)), rng))
    return years


def test_event_years_from():
    events = [
        {"date": "2020-06-15"},
        {"year": 2019},
        {"fromdate": "2018-01-01"},
        {"start_date": "2017-05-05"},
        {"date": "not-a-date"},
        {"date": "1800-01-01"},   # out of plausible range → ignored
        {"name": "no date at all"},
    ]
    assert ac.event_years_from(events) == [2020, 2019, 2018, 2017]


def test_frequency_trend_detects_planted_increase():
    years = _planted_years(0.20)
    assert len(years) >= ac.TREND_MIN_EVENTS
    t = ac.frequency_trend(years, {"start": "2000-01-01", "end": "2024-12-31"})
    assert t["status"] == "ok"
    assert t["direction"] == "increasing"
    assert t["slope_per_year"] > 0
    assert t["annual_multiplier"] > 1.0
    assert t["p_value"] < 0.05
    assert t["lambda_current_year"] > t["lambda_average"]
    assert t["trend_ratio_current_vs_average"] > 1.0
    assert "bias" in t["note"].lower()


def test_frequency_trend_flat_is_honest():
    years = _planted_years(0.0, seed=5, base=-0.2)
    t = ac.frequency_trend(years, {"start": "2000-01-01", "end": "2024-12-31"})
    assert t["status"] == "ok"
    assert t["direction"] == "no_significant_trend"


def test_frequency_trend_thin_data_unavailable():
    cov = {"start": "2000-01-01", "end": "2024-12-31"}
    # too few events
    t = ac.frequency_trend([2010, 2015, 2020], cov)
    assert t["status"] == "unavailable"
    assert "at least" in t["unavailable_reason"]
    # record too short
    t = ac.frequency_trend([2018] * 20, {"start": "2015-01-01", "end": "2024-12-31"})
    assert t["status"] == "unavailable"
    # events in too few distinct years
    t = ac.frequency_trend([2010] * 12 + [2011] * 8, cov)
    assert t["status"] == "unavailable"
    assert "distinct year" in t["unavailable_reason"]


def test_peril_actuarial_carries_trend_and_fit_keys():
    block = ac.build_peril_actuarial(
        hazard_id="wildfire", peril_label="Wildfire",
        events_status="ok", events_count=2,
        events=[{"date": "2020-01-01"}, {"date": "2021-01-01"}],
        temporal_coverage=_COVERAGE, radius_km=50.0,
    )
    assert block["trend"]["status"] == "unavailable"      # thin → honest
    assert "at least" in block["trend"]["unavailable_reason"]
    assert block["severity_fit"]["status"] == "unavailable"
    # coverage-less peril still carries the keys
    block2 = ac.build_peril_actuarial(
        hazard_id="wind", peril_label="Windstorm",
        events_status="ok", events_count=1, events=[{"date": "2020-01-01"}],
        temporal_coverage=None, radius_km=50.0,
    )
    assert block2["trend"]["status"] == "unavailable"
    assert "temporal coverage" in block2["trend"]["unavailable_reason"]


# ---------------------------------------------------------------------------
# Severity distribution fitting
# ---------------------------------------------------------------------------

def test_severity_fit_prefers_lognormal_on_lognormal_sample():
    import random

    rng = random.Random(42)
    vals = [rng.lognormvariate(3.0, 0.8) for _ in range(40)]
    fit = ac.severity_distribution_fit(vals)
    assert fit["status"] == "ok"
    assert fit["n"] == 40
    assert fit["preferred"] == "lognormal"
    by_name = {f["distribution"]: f for f in fit["fits"]}
    assert by_name["lognormal"]["ks_statistic"] < 0.2
    assert by_name["lognormal"]["aic"] < by_name["pareto"]["aic"]
    assert by_name["lognormal"]["parameters"]["mu"] == pytest.approx(3.0, abs=0.3)


def test_severity_fit_thin_or_bad_data_unavailable():
    fit = ac.severity_distribution_fit([1.0, 2.0, 3.0])
    assert fit["status"] == "unavailable"
    assert "at least" in fit["unavailable_reason"]
    # zeros / negatives are filtered out before fitting
    fit = ac.severity_distribution_fit([0, -1] * 10)
    assert fit["status"] == "unavailable"


def test_severity_fit_pareto_degenerate_guard():
    fit = ac._fit_pareto([5.0] * 12)   # all equal → α infinite → declined
    assert fit is None


# ---------------------------------------------------------------------------
# Insurability screen
# ---------------------------------------------------------------------------

def test_insurability_screen_scoring_and_bands():
    perils = [
        ac.build_peril_actuarial(
            hazard_id="wildfire", peril_label="Wildfire",
            events_status="ok", events_count=15,
            events=[{"date": f"{2000 + i}-06-01"} for i in range(15)],
            temporal_coverage=_COVERAGE, radius_km=50.0,
        )
    ]
    ins = ac.insurability_screen(perils, {"wildfire": "High"})
    assert ins["status"] == "ok"
    # λ = 15/25 = 0.6 → tier "high" → pressure 70; level High → 75.
    # score = 0.6·70 + 0.4·75 = 72 → enhanced_review.
    assert ins["attention_score"] == pytest.approx(72.0)
    assert ins["attention_band"] == "enhanced_review"
    assert ins["confidence"] == "high"
    assert ins["components"]["frequency_pressure"]["worst_peril"] == "wildfire"
    assert ins["rubric"]["tier_pressure"]["high"] == 70


def test_insurability_screen_missing_data_never_raises_score():
    # 4 perils, only 1 quantified, no levels: score comes from the single
    # frequency component renormalised (0.6 weight only), confidence is low.
    perils = [
        ac.build_peril_actuarial(
            hazard_id="flood", peril_label="Flood",
            events_status="ok", events_count=1,
            events=[{"date": "2020-01-01"}],
            temporal_coverage=_COVERAGE, radius_km=50.0,
        ),
        ac.build_peril_actuarial(hazard_id="wind", peril_label="Windstorm",
                                 events_status="unavailable", events_count=0),
        ac.build_peril_actuarial(hazard_id="heat", peril_label="Heatwave",
                                 events_status="unavailable", events_count=0),
        ac.build_peril_actuarial(hazard_id="drought", peril_label="Drought",
                                 events_status="unavailable", events_count=0),
    ]
    ins = ac.insurability_screen(perils, {})
    assert ins["status"] == "ok"
    # λ = 1/25 = 0.04 → tier "low" → pressure 20 → score 20 (not inflated).
    assert ins["attention_score"] == pytest.approx(20.0)
    assert ins["attention_band"] == "low_attention"
    assert ins["confidence"] == "low"
    assert "current_level_pressure" not in ins["components"]


def test_insurability_screen_nothing_to_screen():
    ins = ac.insurability_screen(
        [ac.build_peril_actuarial(hazard_id="wind", peril_label="Windstorm",
                                  events_status="unavailable", events_count=0)],
        {},
    )
    assert ins["status"] == "unavailable"
    assert ins["unavailable_reason"]


def test_account_summary_carries_insurability_and_trends():
    perils = [
        ac.build_peril_actuarial(
            hazard_id="wildfire", peril_label="Wildfire",
            events_status="ok", events_count=15,
            events=[{"date": f"{2000 + i}-06-01"} for i in range(15)],
            temporal_coverage=_COVERAGE, radius_km=50.0,
        ),
        _ok_peril("flood", 3),
    ]
    summary = ac.build_account_actuarial(perils, peril_levels={"wildfire": "High"})
    assert summary["insurability"]["status"] == "ok"
    assert "significant_trends" in summary


# ---------------------------------------------------------------------------
# Extended reference (vulnerability curve, premium principles, climate)
# ---------------------------------------------------------------------------

def test_reference_includes_user_guidance_additions():
    ref = ac.actuarial_reference()
    formula_ids = {f["id"] for f in ref["formulas"]}
    for required in ("expected_value_principle", "vulnerability_curve",
                     "negative_binomial", "climate_conditioning", "event_set_ep"):
        assert required in formula_ids
    term_ids = {t["id"] for t in ref["glossary"]}
    for required in ("non_stationarity", "glm", "stochastic_event_set",
                     "vulnerability_curve_term", "damage_ratio", "reporting_bias"):
        assert required in term_ids
    assert ref["term_count"] >= 60
    assert ref["formula_count"] >= 20


# ---------------------------------------------------------------------------
# PDF report with the actuarial section
# ---------------------------------------------------------------------------

def test_pdf_report_builds_with_actuarial_section(monkeypatch):
    pytest.importorskip("reportlab")
    _stub_registry(monkeypatch)
    from src.climate.insurance import build_risk_profile
    from src.dashboard.insurance_report import build_insurance_pdf

    profile = build_risk_profile(1.0, 2.0, name="Asset", radius_km=25)
    assert profile["actuarial_summary"]["status"] == "ok"
    pdf = build_insurance_pdf(profile)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000

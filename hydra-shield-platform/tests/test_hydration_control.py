"""Tests for the hydration_control module."""

import numpy as np
import pytest

from src.hydration_control.water_optimiser import WaterOptimiser, WaterUseEfficiency
from src.hydration_control.intervention import InterventionPlanner, InterventionPlan
from src.hydration_control.verification import HindcastValidator, HindcastResult


class TestWaterOptimiser:
    """Tests for WaterOptimiser."""

    def setup_method(self):
        self.optimiser = WaterOptimiser(water_available_m3=1000.0)

    def test_compute_wuer(self):
        wuer = self.optimiser.compute_wuer(
            risk_baseline=0.8, risk_hydrashield=0.3, water_volume_m3=100.0
        )
        assert isinstance(wuer, WaterUseEfficiency)
        assert wuer.wuer == pytest.approx(0.005)

    def test_compute_wuer_zero_volume(self):
        wuer = self.optimiser.compute_wuer(0.8, 0.3, 0.0)
        assert wuer.wuer == 0.0

    def test_allocate_water_priority(self):
        priorities = [1.0, 3.0, 2.0]
        areas = [1000.0, 1000.0, 1000.0]
        allocations = self.optimiser.allocate_water(priorities, areas)
        # Highest priority (index 1) gets full allocation first
        assert allocations[1] == pytest.approx(10.0)
        assert sum(allocations) <= self.optimiser.water_available_m3

    def test_allocate_water_budget_exhausted(self):
        priorities = [1.0, 1.0, 1.0]
        areas = [100000.0, 100000.0, 100000.0]
        allocations = self.optimiser.allocate_water(priorities, areas)
        assert sum(allocations) == pytest.approx(self.optimiser.water_available_m3)

    def test_water_savings(self):
        savings = self.optimiser.water_savings(1000.0, 200.0)
        assert savings == pytest.approx(80.0)


class TestInterventionPlanner:
    """Tests for InterventionPlanner."""

    def setup_method(self):
        self.planner = InterventionPlanner()

    def test_classify_recommendation(self):
        assert self.planner.classify_recommendation(0.9) == "green"
        assert self.planner.classify_recommendation(0.6) == "yellow"
        assert self.planner.classify_recommendation(0.3) == "red"

    def test_compute_duration(self):
        duration = self.planner.compute_duration(100.0, 50.0)
        assert duration == pytest.approx(2.0)

    def test_build_plan(self):
        plans = self.planner.build_plan(
            zone_ids=["z1", "z2"],
            water_volumes_m3=[100.0, 50.0],
            confidences=[0.9, 0.3],
        )
        assert len(plans) == 2
        assert all(isinstance(p, InterventionPlan) for p in plans)
        assert plans[0].recommendation == "green"
        assert plans[1].recommendation == "red"

    def test_evacuation_safety_margin(self):
        esm = self.planner.evacuation_safety_margin(
            evacuation_window_h=24.0,
            fire_arrival_h=12.0,
            operational_margin_h=2.0,
            uncertainty_h=1.0,
        )
        assert esm == pytest.approx(9.0)


class TestHindcastValidator:
    """Tests for HindcastValidator."""

    def setup_method(self):
        self.validator = HindcastValidator(threshold=0.5)

    def test_validate_event_perfect(self):
        pred = np.array([0.9, 0.9, 0.1, 0.1])
        obs = np.array([1, 1, 0, 0])
        result = self.validator.validate_event("event1", pred, obs)
        assert isinstance(result, HindcastResult)
        assert result.iou == pytest.approx(1.0)
        assert result.precision == pytest.approx(1.0)
        assert result.recall == pytest.approx(1.0)
        assert result.critical_success_index == pytest.approx(1.0)

    def test_validate_event_imperfect(self):
        pred = np.array([0.9, 0.1, 0.9, 0.1])
        obs = np.array([1, 1, 0, 0])
        result = self.validator.validate_event("event2", pred, obs)
        # tp=1, fp=1, fn=1, tn=1
        assert result.iou == pytest.approx(1 / 3)
        assert result.precision == pytest.approx(0.5)
        assert result.recall == pytest.approx(0.5)

    def test_validate_events_and_aggregate(self):
        events = [
            {"id": "e1", "predicted_probability": np.array([0.9, 0.1]), "observed_burned": np.array([1, 0])},
            {"id": "e2", "predicted_probability": np.array([0.9, 0.1]), "observed_burned": np.array([1, 0])},
        ]
        results = self.validator.validate_events(events)
        assert len(results) == 2
        agg = self.validator.aggregate_metrics(results)
        assert agg["mean_iou"] == pytest.approx(1.0)

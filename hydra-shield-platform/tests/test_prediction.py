"""Tests for the prediction module."""

import numpy as np
import pytest

from src.prediction.fuel_moisture import FuelMoistureModel
from src.prediction.fire_spread import FireSpreadModel, RateOfSpread
from src.prediction.risk_model import WildfireRiskModel, AdvancedWildfireRiskModel


class TestFuelMoistureModel:
    """Tests for FuelMoistureModel."""

    def setup_method(self):
        self.model = FuelMoistureModel()

    def test_estimate_fmc_from_ndmi_bounds(self):
        ndmi = np.array([-1.0, 0.0, 1.0])
        fmc = self.model.estimate_fmc_from_ndmi(ndmi)
        assert np.all(fmc >= 0.0)
        assert np.all(fmc <= 100.0)
        # Higher NDMI -> higher FMC
        assert fmc[2] > fmc[0]

    def test_estimate_fmc_from_ndwi_bounds(self):
        ndwi = np.array([-1.0, 0.0, 1.0])
        fmc = self.model.estimate_fmc_from_ndwi(ndwi)
        assert np.all(fmc >= 0.0)
        assert np.all(fmc <= 100.0)

    def test_capillary_transfer(self):
        soil_moisture = np.array([0.0, 0.225, 0.45])
        fmc = self.model.capillary_transfer(soil_moisture)
        # At saturation, FMC = 100 * coefficient
        assert fmc[2] == pytest.approx(100.0 * self.model.capillary_rise_coefficient)
        assert fmc[0] == 0.0
        assert fmc[1] > fmc[0]

    def test_minimum_effective_fmc_increase(self):
        mefmi = self.model.minimum_effective_fmc_increase(8.0, 15.0)
        assert mefmi == pytest.approx(7.0)

    def test_time_to_reach_target(self):
        # Achievable target
        t = self.model.time_to_reach_target(
            fmc_baseline=5.0,
            fmc_target=10.0,
            soil_moisture=0.45,
        )
        assert t >= 0.0
        assert np.isfinite(t)

    def test_time_to_reach_target_unachievable(self):
        # Target above achievable -> inf
        t = self.model.time_to_reach_target(
            fmc_baseline=5.0,
            fmc_target=90.0,
            soil_moisture=0.1,
        )
        assert t == float("inf")


class TestFireSpreadModel:
    """Tests for FireSpreadModel."""

    def setup_method(self):
        self.model = FireSpreadModel(fuel_model="TL3")

    def test_wind_factor(self):
        assert self.model.wind_factor(0.0) == pytest.approx(1.0)
        assert self.model.wind_factor(20.0) > 1.0

    def test_slope_factor(self):
        assert self.model.slope_factor(0.0) == pytest.approx(1.0)
        assert self.model.slope_factor(30.0) > 1.0

    def test_fmc_reduction_factor_bounds(self):
        assert self.model.fmc_reduction_factor(0.0) == pytest.approx(1.0)
        assert 0.0 <= self.model.fmc_reduction_factor(20.0) <= 1.0
        # Higher FMC -> lower factor
        assert self.model.fmc_reduction_factor(20.0) < self.model.fmc_reduction_factor(10.0)

    def test_probability_of_spread_bounds(self):
        p = self.model.probability_of_spread(fmc=10.0, wind_speed_kmh=20.0, slope_degrees=15.0)
        assert 0.0 <= p <= 1.0

    def test_compute_ros(self):
        ros = self.model.compute_ros(fmc=8.0, wind_speed_kmh=10.0, slope_degrees=10.0)
        assert isinstance(ros, RateOfSpread)
        assert ros.ros_baseline > 0.0
        assert ros.ros_reduced <= ros.ros_baseline
        assert 0.0 <= ros.reduction_factor <= 1.0

    def test_compute_ros_with_3d_wind(self):
        # Test with 3D wind components
        ros = self.model.compute_ros(
            fmc=8.0, 
            wind_speed_kmh=10.0, 
            slope_degrees=10.0,
            wind_u=8.0,
            wind_v=6.0,
            wind_w=2.0
        )
        assert isinstance(ros, RateOfSpread)
        assert ros.ros_baseline > 0.0
        assert ros.ros_reduced <= ros.ros_baseline
        assert 0.0 <= ros.reduction_factor <= 1.0
        # Check that 3D components are included
        assert hasattr(ros, 'ros_horizontal')
        assert hasattr(ros, 'ros_vertical')
        assert hasattr(ros, 'ros_crown')

    def test_wind_vector_factor(self):
        # Test 3D wind vector calculations
        horizontal_effect, vertical_effect, total_effect = self.model.wind_vector_factor(3.0, 4.0, 0.0)
        assert horizontal_effect >= 1.0  # Should be amplified by wind
        assert vertical_effect >= 1.0  # Should account for vertical component
        assert total_effect >= 1.0  # Combined effect

        # Test with vertical component
        horizontal_effect, vertical_effect, total_effect = self.model.wind_vector_factor(3.0, 4.0, 2.0)
        assert vertical_effect > 1.0  # Should be greater than 1 with vertical wind

    def test_horizontal_spread_factor(self):
        # Test horizontal spread based on wind-aspect alignment
        factor_aligned = self.model.horizontal_spread_factor(0.0, 0.0)  # Same direction
        factor_opposite = self.model.horizontal_spread_factor(0.0, 180.0)  # Opposite directions
        factor_perpendicular = self.model.horizontal_spread_factor(0.0, 90.0)  # Perpendicular
        
        # Aligned should be higher than perpendicular
        assert factor_aligned > factor_perpendicular
        # Opposite should be lower than aligned
        assert factor_aligned > factor_opposite

    def test_vertical_spread_potential(self):
        # Test vertical spread potential
        potential_no_spread = self.model.vertical_spread_potential(1.0, 1.0)  # Flame shorter than fuel
        potential_some_spread = self.model.vertical_spread_potential(1.0, 3.0)  # Flame longer than fuel
        
        assert potential_no_spread == 0.0
        assert 0.0 < potential_some_spread <= 1.0

    def test_fire_arrival_time(self):
        t = self.model.fire_arrival_time(
            distance_m=1000.0, fmc=8.0, wind_speed_kmh=10.0, slope_degrees=10.0
        )
        assert t > 0.0

    def test_fire_arrival_time_with_3d_wind(self):
        t = self.model.fire_arrival_time(
            distance_m=1000.0, 
            fmc=8.0, 
            wind_speed_kmh=10.0, 
            slope_degrees=10.0,
            wind_u=8.0,
            wind_v=6.0,
            wind_w=1.0
        )
        assert t > 0.0


class TestWildfireRiskModel:
    """Tests for WildfireRiskModel."""

    def test_train_and_predict(self):
        rng = np.random.RandomState(42)
        X = rng.rand(200, 4)
        y = (X[:, 0] + X[:, 1] > 1.0).astype(int)

        model = WildfireRiskModel(n_estimators=20, random_state=42)
        metrics = model.train(
            X, y, feature_names=["temp", "wind", "humidity", "fuel"]
        )

        assert 0.0 <= metrics.auc_score <= 1.0
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0

        probs = model.predict_proba(X[:5])
        assert probs.shape == (5,)
        assert np.all((probs >= 0.0) & (probs <= 1.0))

        importances = model.feature_importances()
        assert len(importances) == 4
        assert "temp" in importances

    def test_predict_before_train_raises(self):
        model = WildfireRiskModel()
        with pytest.raises(RuntimeError):
            model.predict(np.zeros((3, 4)))

    def test_advanced_wildfire_risk_model(self):
        rng = np.random.RandomState(42)
        X = rng.rand(200, 4)
        y = (X[:, 0] + X[:, 1] > 1.0).astype(int)

        model = AdvancedWildfireRiskModel(n_estimators=20, random_state=42)
        metrics = model.train(
            X, y, feature_names=["temp", "wind", "humidity", "fuel"]
        )

        assert 0.0 <= metrics.auc_score <= 1.0
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0

        probs = model.predict_proba(X[:5])
        assert probs.shape == (5,)
        assert np.all((probs >= 0.0) & (probs <= 1.0))

        # Test uncertainty prediction
        probs_with_uncertainty = model.predict_with_uncertainty(X[:5])
        assert len(probs_with_uncertainty) == 2  # (predictions, uncertainty)
        assert probs_with_uncertainty[0].shape == (5,)  # predictions
        assert probs_with_uncertainty[1].shape == (5,)  # uncertainty

        importances = model.feature_importances()
        assert len(importances) == 4
        assert "temp" in importances

    def test_advanced_model_single_model(self):
        rng = np.random.RandomState(42)
        X = rng.rand(100, 3)
        y = (X[:, 0] > 0.5).astype(int)

        # Test with single model instead of ensemble
        model = AdvancedWildfireRiskModel(use_ensemble=False, n_estimators=10, random_state=42)
        metrics = model.train(X, y)
        
        assert 0.0 <= metrics.auc_score <= 1.0
        assert isinstance(metrics.auc_score, float)

        probs = model.predict_proba(X[:3])
        assert probs.shape == (3,)
        assert np.all((probs >= 0.0) & (probs <= 1.0))

"""Tests for the gis_mapping module."""

import numpy as np
import pytest

from src.gis_mapping.indices import (
    compute_ndvi,
    compute_ndmi,
    compute_ndwi,
    _safe_normalized_difference,
)
from src.gis_mapping.data_fusion import DataFusionPipeline
from src.gis_mapping.mapping import ProtectionZoneMapper


class TestIndices:
    """Tests for spectral index computation."""

    def test_ndvi(self):
        red = np.array([0.1, 0.2, 0.3])
        nir = np.array([0.6, 0.7, 0.8])
        ndvi = compute_ndvi(nir, red)
        expected = np.array([0.714, 0.556, 0.455])  # Rounded to 3 decimals
        np.testing.assert_allclose(ndvi, expected, atol=0.001)

    def test_ndmi(self):
        nir = np.array([0.4, 0.5, 0.6])
        swir = np.array([0.2, 0.3, 0.4])
        ndmi = compute_ndmi(nir, swir)
        expected = np.array([0.333, 0.250, 0.200])
        np.testing.assert_allclose(ndmi, expected, atol=0.001)

    def test_ndwi(self):
        green = np.array([0.2, 0.3, 0.4])
        nir = np.array([0.6, 0.7, 0.8])
        ndwi = compute_ndwi(green, nir)
        # NDWI = (GREEN - NIR) / (GREEN + NIR)
        # (0.2-0.6)/(0.2+0.6) = -0.4/0.8 = -0.5
        # (0.3-0.7)/(0.3+0.7) = -0.4/1.0 = -0.4
        # (0.4-0.8)/(0.4+0.8) = -0.4/1.2 = -0.333
        expected = np.array([-0.500, -0.400, -0.333])
        np.testing.assert_allclose(ndwi, expected, atol=0.001)

    def test_zero_denominator_safe(self):
        # Test division by zero handling
        a = np.array([1.0, 2.0])
        b = np.array([-1.0, -2.0])  # Makes denominator 0
        result = _safe_normalized_difference(a, b)
        expected = np.array([0.0, 0.0])
        np.testing.assert_array_equal(result, expected)


class TestDataFusionPipeline:
    """Tests for data fusion pipeline."""

    def setup_method(self):
        self.pipeline = DataFusionPipeline()

    def test_fuse_soil_moisture(self):
        sar = np.array([0.2, 0.3, 0.4])
        rean = np.array([0.25, 0.35, 0.45])
        fused = self.pipeline.fuse_soil_moisture(sar, rean)
        # Equal weights, so average
        expected = np.array([0.225, 0.325, 0.425])
        np.testing.assert_allclose(fused, expected)

    def test_fuse_with_cloud_mask(self):
        sar = np.array([0.2, 0.3, 0.4])
        rean = np.array([0.25, 0.35, 0.45])
        cloud_mask = np.array([True, False, True])
        fused = self.pipeline.fuse_soil_moisture(sar, rean, cloud_mask=cloud_mask)
        # Where cloudy, use fused; where clear, use rean
        expected = np.array([0.225, 0.35, 0.425])  # Cloudy: average, Clear: rean
        np.testing.assert_allclose(fused, expected)

    def test_temporal_interpolate(self):
        series = np.array([1.0, 2.0, 3.0])
        timestamps = np.array([0.0, 1.0, 2.0])
        targets = np.array([0.5, 1.5])
        interpolated = self.pipeline.temporal_interpolate(series, timestamps, targets)
        expected = np.array([1.5, 2.5])
        np.testing.assert_allclose(interpolated, expected)

    def test_estimate_fmc_from_fused_moisture(self):
        fused = np.array([0.2, 0.3, 0.4])
        fmc = self.pipeline.estimate_fmc_from_fused_moisture(fused)
        # FMC = 100 * coeff * (fused / sat)
        expected = 100.0 * 0.35 * (fused / 0.45)
        np.testing.assert_allclose(fmc, expected)

    def test_weather_impact_factor(self):
        # Test with normal weather
        weather = {'precipitation': 2.0, 'humidity': 0.6}
        factor = self.pipeline.weather_impact_factor(weather)
        assert 0.1 <= factor <= 2.0
        
        # Test with heavy precipitation
        weather_heavy_rain = {'precipitation': 10.0, 'humidity': 0.6}
        factor_heavy_rain = self.pipeline.weather_impact_factor(weather_heavy_rain)
        # Should increase SAR reliability during heavy rain
        assert factor_heavy_rain > 1.0
        
        # Test with very dry conditions
        weather_dry = {'precipitation': 0.0, 'humidity': 0.2}
        factor_dry = self.pipeline.weather_impact_factor(weather_dry)
        # Should decrease factor in very dry conditions
        assert factor_dry < 1.1

    def test_terrain_visibility_factor(self):
        # Test different terrain types
        assert self.pipeline.terrain_visibility_factor('forest') == 1.1
        assert self.pipeline.terrain_visibility_factor('urban') == 1.0
        assert self.pipeline.terrain_visibility_factor('agricultural') == 0.9
        assert self.pipeline.terrain_visibility_factor('mountain') == 1.2
        assert self.pipeline.terrain_visibility_factor('desert') == 0.8
        assert self.pipeline.terrain_visibility_factor('water') == 1.0
        assert self.pipeline.terrain_visibility_factor('mixed') == 1.0
        # Unknown terrain defaults to 1.0
        assert self.pipeline.terrain_visibility_factor('unknown') == 1.0

    def test_adaptive_fusion_weights(self):
        # Test adaptive weights calculation
        sar_quality = 0.9
        rean_quality = 0.7
        weather = {'precipitation': 3.0, 'humidity': 0.5}
        terrain = 'forest'
        
        sar_weight, rean_weight = self.pipeline.adaptive_fusion_weights(
            sar_quality, rean_quality, weather, terrain
        )
        
        # Check that weights sum to approximately 1.0
        assert abs(sar_weight + rean_weight - 1.0) < 1e-10
        # Check that both weights are positive
        assert sar_weight > 0 and rean_weight > 0

    def test_fuse_soil_moisture_with_adaptive_weights(self):
        sar = np.array([0.2, 0.3, 0.4])
        rean = np.array([0.25, 0.35, 0.45])
        weather = {'precipitation': 5.0, 'humidity': 0.8}
        terrain = 'forest'
        
        fused = self.pipeline.fuse_soil_moisture(
            sar, rean, 
            sar_data_quality=0.9, 
            reanalysis_data_quality=0.7,
            weather_conditions=weather,
            terrain_type=terrain
        )
        
        # Result should be within bounds
        assert np.all(fused >= 0.0) and np.all(fused <= 1.0)
        
        # With cloud mask
        cloud_mask = np.array([True, False, True])
        fused_with_mask = self.pipeline.fuse_soil_moisture(
            sar, rean, cloud_mask=cloud_mask,
            sar_data_quality=0.9, 
            reanalysis_data_quality=0.7,
            weather_conditions=weather,
            terrain_type=terrain
        )
        
        # Results should still be within bounds
        assert np.all(fused_with_mask >= 0.0) and np.all(fused_with_mask <= 1.0)


class TestProtectionZoneMapper:
    """Tests for protection zone mapping."""

    def setup_method(self):
        self.mapper = ProtectionZoneMapper()

    def test_compute_zone_radius(self):
        radius = self.mapper.compute_zone_radius(fire_arrival_time_min=60.0, ros_m_per_min=5.0)
        assert radius == 300.0  # 60 * 5

    def test_classify_risk(self):
        # Low risk, sufficient lead time -> green
        risk = self.mapper.classify_risk(probability_of_spread=0.3, fire_arrival_time_min=90.0)
        assert risk == "green"

        # Moderate risk -> yellow
        risk = self.mapper.classify_risk(probability_of_spread=0.6, fire_arrival_time_min=90.0)
        assert risk == "yellow"

        # High risk -> red
        risk = self.mapper.classify_risk(probability_of_spread=0.85, fire_arrival_time_min=90.0)
        assert risk == "red"

        # Insufficient lead time -> red
        risk = self.mapper.classify_risk(probability_of_spread=0.3, fire_arrival_time_min=20.0)
        assert risk == "red"

    def test_build_protection_zones(self):
        assets = [
            {"id": "school", "type": "school", "centroid": (10.0, 20.0)},
            {"id": "hospital", "type": "hospital", "centroid": (11.0, 21.0)},
        ]
        zones = self.mapper.build_protection_zones(
            assets, ros_m_per_min=5.0, probability_of_spread=0.4, lead_time_min=60.0
        )
        assert len(zones) == 2
        assert zones[0].asset_id == "school"
        assert zones[0].radius_m == 300.0  # 60 * 5
        assert zones[1].asset_id == "hospital"

    def test_compute_critical_area(self):
        assets = [{"id": "asset1", "type": "type1", "centroid": (0.0, 0.0)}]
        zones = self.mapper.build_protection_zones(
            assets, ros_m_per_min=1.0, probability_of_spread=0.5, lead_time_min=10.0
        )
        area = self.mapper.compute_critical_area(zones)
        # Area = pi * r^2, r = 10 * 1 = 10
        expected_area = np.pi * 100
        assert area == pytest.approx(expected_area, rel=1e-3)

        # With max area constraint
        constrained_area = self.mapper.compute_critical_area(zones, max_area_m2=50.0)
        assert constrained_area == 50.0
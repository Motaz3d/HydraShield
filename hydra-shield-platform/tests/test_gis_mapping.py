"""Tests for the gis_mapping module."""

import numpy as np
import pytest

from src.gis_mapping.indices import compute_ndvi, compute_ndmi, compute_ndwi
from src.gis_mapping.data_fusion import DataFusionPipeline
from src.gis_mapping.mapping import ProtectionZoneMapper, ProtectionZone


class TestIndices:
    """Tests for spectral index computation."""

    def test_ndvi(self):
        nir = np.array([0.5, 0.8])
        red = np.array([0.1, 0.2])
        ndvi = compute_ndvi(nir, red)
        assert ndvi.shape == (2,)
        assert np.all((ndvi >= -1.0) & (ndvi <= 1.0))
        # NDVI = (0.5-0.1)/(0.5+0.1) = 0.667
        assert ndvi[0] == pytest.approx(0.4 / 0.6)

    def test_ndmi(self):
        nir = np.array([0.6])
        swir = np.array([0.3])
        ndmi = compute_ndmi(nir, swir)
        assert ndmi[0] == pytest.approx(0.3 / 0.9)

    def test_ndwi(self):
        green = np.array([0.4])
        nir = np.array([0.6])
        ndwi = compute_ndwi(green, nir)
        assert ndwi[0] == pytest.approx(-0.2 / 1.0)

    def test_zero_denominator_safe(self):
        nir = np.array([0.0])
        red = np.array([0.0])
        ndvi = compute_ndvi(nir, red)
        assert ndvi[0] == 0.0


class TestDataFusionPipeline:
    """Tests for DataFusionPipeline."""

    def setup_method(self):
        self.pipeline = DataFusionPipeline(sar_weight=0.5, reanalysis_weight=0.5)

    def test_fuse_soil_moisture(self):
        sar = np.array([0.2, 0.3])
        rean = np.array([0.4, 0.5])
        fused = self.pipeline.fuse_soil_moisture(sar, rean)
        # Weighted average: 0.5*0.2 + 0.5*0.4 = 0.3
        assert fused[0] == pytest.approx(0.3)
        assert np.all((fused >= 0.0) & (fused <= 1.0))

    def test_fuse_with_cloud_mask(self):
        sar = np.array([0.2, 0.3])
        rean = np.array([0.4, 0.5])
        cloud = np.array([True, False])
        fused = self.pipeline.fuse_soil_moisture(sar, rean, cloud)
        # Cloud pixel uses fusion, clear pixel uses reanalysis
        assert fused[0] == pytest.approx(0.3)
        assert fused[1] == pytest.approx(0.5)

    def test_temporal_interpolate(self):
        series = np.array([0.0, 10.0])
        times = np.array([0.0, 10.0])
        targets = np.array([5.0])
        result = self.pipeline.temporal_interpolate(series, times, targets)
        assert result[0] == pytest.approx(5.0)

    def test_estimate_fmc_from_fused_moisture(self):
        fused = np.array([0.45])
        fmc = self.pipeline.estimate_fmc_from_fused_moisture(fused)
        assert fmc[0] == pytest.approx(35.0)


class TestProtectionZoneMapper:
    """Tests for ProtectionZoneMapper."""

    def setup_method(self):
        self.mapper = ProtectionZoneMapper()

    def test_compute_zone_radius(self):
        radius = self.mapper.compute_zone_radius(60.0, 5.0)
        assert radius == pytest.approx(300.0)

    def test_classify_risk(self):
        assert self.mapper.classify_risk(0.2, 120.0) == "green"
        assert self.mapper.classify_risk(0.6, 40.0) == "yellow"
        assert self.mapper.classify_risk(0.9, 10.0) == "red"

    def test_build_protection_zones(self):
        assets = [
            {"id": "school", "type": "school", "centroid": (10.0, 20.0)},
            {"id": "hospital", "type": "hospital", "centroid": (11.0, 21.0)},
        ]
        zones = self.mapper.build_protection_zones(
            assets, ros_m_per_min=5.0, probability_of_spread=0.3, lead_time_min=60.0
        )
        assert len(zones) == 2
        assert all(isinstance(z, ProtectionZone) for z in zones)
        assert zones[0].radius_m == pytest.approx(300.0)

    def test_compute_critical_area(self):
        zones = [
            ProtectionZone("a", "school", (0, 0), 100.0, np.pi * 10000, "green", 60.0),
            ProtectionZone("b", "hospital", (0, 0), 100.0, np.pi * 10000, "green", 60.0),
        ]
        total = self.mapper.compute_critical_area(zones)
        assert total == pytest.approx(2 * np.pi * 10000)

        capped = self.mapper.compute_critical_area(zones, max_area_m2=np.pi * 10000)
        assert capped == pytest.approx(np.pi * 10000)

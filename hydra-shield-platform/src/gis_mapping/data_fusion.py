"""
Data fusion pipeline for cloud cover mitigation.

To address Sentinel-2 cloud cover limitations, this pipeline fuses:
    - Sentinel-1 SAR (all-weather, day/night) for soil moisture estimation.
    - ECMWF soil moisture reanalysis (ERA5-Land) for temporal interpolation.

The result is a gap-filled, cloud-free soil moisture / FMC product suitable
for downstream risk modelling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np


@dataclass
class DataFusionPipeline:
    """
    Fuse multiple EO data sources to produce a cloud-free moisture product.

    Parameters
    ----------
    sar_weight : float
        Weight given to Sentinel-1 SAR-derived soil moisture (0-1).
    reanalysis_weight : float
        Weight given to ERA5-Land reanalysis soil moisture (0-1).
    """

    sar_weight: float = 0.5
    reanalysis_weight: float = 0.5

    def __post_init__(self) -> None:
        total = self.sar_weight + self.reanalysis_weight
        if total <= 0:
            raise ValueError("Weights must sum to a positive value.")
        # Normalise weights
        self.sar_weight = self.sar_weight / total
        self.reanalysis_weight = self.reanalysis_weight / total

    def fuse_soil_moisture(
        self,
        sar_soil_moisture: np.ndarray,
        reanalysis_soil_moisture: np.ndarray,
        cloud_mask: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Fuse SAR and reanalysis soil moisture into a single product.

        Where cloud cover is present (cloud_mask == True), the SAR/reanalysis
        fusion fills the gap. Where no cloud is present, the optical-derived
        value is preferred.

        Parameters
        ----------
        sar_soil_moisture : np.ndarray
            Soil moisture from Sentinel-1 SAR (m^3/m^3).
        reanalysis_soil_moisture : np.ndarray
            Soil moisture from ERA5-Land reanalysis (m^3/m^3).
        cloud_mask : Optional[np.ndarray]
            Boolean mask where True indicates cloud-covered pixels.

        Returns
        -------
        np.ndarray
            Fused soil moisture product (m^3/m^3).
        """
        sar = np.asarray(sar_soil_moisture, dtype=float)
        rean = np.asarray(reanalysis_soil_moisture, dtype=float)

        # Weighted fusion of SAR and reanalysis
        fused = self.sar_weight * sar + self.reanalysis_weight * rean

        if cloud_mask is not None:
            cloud_mask = np.asarray(cloud_mask, dtype=bool)
            # Where no cloud, prefer the (higher-confidence) optical estimate.
            # Here we use the reanalysis as the "clear" reference.
            fused = np.where(cloud_mask, fused, rean)

        return np.clip(fused, 0.0, 1.0)

    def temporal_interpolate(
        self,
        series: np.ndarray,
        timestamps: np.ndarray,
        target_timestamps: np.ndarray,
    ) -> np.ndarray:
        """
        Linearly interpolate a time series to target timestamps.

        Parameters
        ----------
        series : np.ndarray
            Observed values at `timestamps`.
        timestamps : np.ndarray
            Observation times (numeric, e.g., hours since epoch).
        target_timestamps : np.ndarray
            Times at which to interpolate.

        Returns
        -------
        np.ndarray
            Interpolated values at target timestamps.
        """
        series = np.asarray(series, dtype=float)
        timestamps = np.asarray(timestamps, dtype=float)
        target_timestamps = np.asarray(target_timestamps, dtype=float)
        return np.interp(target_timestamps, timestamps, series)

    def estimate_fmc_from_fused_moisture(
        self,
        fused_soil_moisture: np.ndarray,
        soil_moisture_saturation: float = 0.45,
        capillary_coefficient: float = 0.35,
    ) -> np.ndarray:
        """
        Convert fused soil moisture to a surface fuel moisture estimate.

        Parameters
        ----------
        fused_soil_moisture : np.ndarray
            Fused soil moisture (m^3/m^3).
        soil_moisture_saturation : float
            Saturation soil moisture (m^3/m^3).
        capillary_coefficient : float
            Capillary transfer efficiency (0-1).

        Returns
        -------
        np.ndarray
            Estimated surface FMC (percent).
        """
        fused = np.asarray(fused_soil_moisture, dtype=float)
        rel_sat = np.clip(fused / soil_moisture_saturation, 0.0, 1.0)
        fmc = 100.0 * capillary_coefficient * rel_sat
        return np.clip(fmc, 0.0, 100.0)

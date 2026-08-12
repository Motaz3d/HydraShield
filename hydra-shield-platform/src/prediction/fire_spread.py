"""
Fire spread and Rate of Spread (ROS) modelling.

Implements physics-informed wildfire spread models based on established
landscape-scale approaches (e.g., Rothermel-style formulations adapted for
Mediterranean fuel models).

Key equations:
    - Probability of Spread:  P_spread(t) = f(FMC, wind, slope, fuel type)
    - Reduced Rate of Spread: ROS_reduced = ROS_baseline * R_FMC(MEFMI, ...)
      where R_FMC is a calibrated, non-linear reduction factor in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, Optional

import numpy as np



@dataclass
class RateOfSpread:
    """Container for a Rate of Spread calculation result."""

    ros_baseline: float
    ros_reduced: float
    reduction_factor: float
    fmc: float
    wind_speed: float
    slope_degrees: float

    @property
    def reduction_percent(self) -> float:
        """Percentage reduction in ROS due to moisture intervention."""
        if self.ros_baseline <= 0:
            return 0.0
        return (1.0 - self.ros_reduced / self.ros_baseline) * 100.0


@dataclass
class FireSpreadModel:
    """
    Physics-informed fire spread model.

    Parameters
    ----------
    fuel_model : str
        Scott & Burgan fuel model identifier (e.g., 'GR1', 'TL3', 'SH5').
    base_ros_m_per_min : float
        Baseline Rate of Spread (m/min) for the fuel model under reference
        conditions (FMC = reference_fmc).
    reference_fmc : float
        Reference FMC (percent) at which base_ros_m_per_min applies.
    fmc_sensitivity : float
        Exponent controlling the sensitivity of ROS to FMC reduction.
    """

    fuel_model: str = "TL3"
    base_ros_m_per_min: float = 5.0
    reference_fmc: float = 8.0
    fmc_sensitivity: float = 1.5

    # Fuel model reference table (Scott & Burgan style, simplified)
    FUEL_MODELS: ClassVar[Dict[str, Dict[str, float]]] = {

        "GR1": {"base_ros": 8.0, "reference_fmc": 6.0},
        "GR2": {"base_ros": 10.0, "reference_fmc": 6.0},
        "TL1": {"base_ros": 3.0, "reference_fmc": 8.0},
        "TL2": {"base_ros": 4.0, "reference_fmc": 8.0},
        "TL3": {"base_ros": 5.0, "reference_fmc": 8.0},
        "SH5": {"base_ros": 6.0, "reference_fmc": 7.0},
        "TU1": {"base_ros": 2.5, "reference_fmc": 9.0},
        "TU2": {"base_ros": 3.5, "reference_fmc": 9.0},
    }

    def __post_init__(self) -> None:
        if self.fuel_model in self.FUEL_MODELS:
            ref = self.FUEL_MODELS[self.fuel_model]
            self.base_ros_m_per_min = ref["base_ros"]
            self.reference_fmc = ref["reference_fmc"]

    def wind_factor(self, wind_speed_kmh: float) -> float:
        """
        Wind speed multiplier on ROS.

        A simplified exponential wind influence factor.

        Parameters
        ----------
        wind_speed_kmh : float
            Wind speed in km/h.

        Returns
        -------
        float
            Wind multiplier (>= 1.0).
        """
        wind_speed_kmh = max(wind_speed_kmh, 0.0)
        return float(1.0 + 0.15 * wind_speed_kmh)

    def slope_factor(self, slope_degrees: float) -> float:
        """
        Slope multiplier on ROS.

        Parameters
        ----------
        slope_degrees : float
            Terrain slope in degrees.

        Returns
        -------
        float
            Slope multiplier (>= 1.0).
        """
        slope_degrees = max(slope_degrees, 0.0)
        slope_rad = np.radians(slope_degrees)
        return float(1.0 + 2.0 * np.tan(slope_rad))

    def fmc_reduction_factor(self, fmc: float) -> float:
        """
        Non-linear FMC reduction factor R_FMC in [0, 1].

        As FMC increases above the reference value, ROS is reduced. The factor
        is bounded between 0 and 1.

        Parameters
        ----------
        fmc : float
            Fuel moisture content (percent).

        Returns
        -------
        float
            Reduction factor in [0, 1].
        """
        fmc = max(fmc, 0.0)
        if fmc <= self.reference_fmc:
            return 1.0
        # Exponential decay beyond reference FMC
        ratio = (fmc - self.reference_fmc) / self.reference_fmc
        factor = np.exp(-self.fmc_sensitivity * ratio)
        return float(np.clip(factor, 0.0, 1.0))

    def probability_of_spread(
        self,
        fmc: float,
        wind_speed_kmh: float,
        slope_degrees: float,
    ) -> float:
        """
        Probability of fire spread P_spread(t).

        A logistic function of FMC, wind, and slope.

        Parameters
        ----------
        fmc : float
            Fuel moisture content (percent).
        wind_speed_kmh : float
            Wind speed (km/h).
        slope_degrees : float
            Terrain slope (degrees).

        Returns
        -------
        float
            Probability of spread in [0, 1].
        """
        # Logistic regression on a composite risk score
        z = (
            3.0
            - 0.25 * fmc
            + 0.10 * wind_speed_kmh
            + 0.05 * slope_degrees
        )
        return float(1.0 / (1.0 + np.exp(-z)))

    def compute_ros(
        self,
        fmc: float,
        wind_speed_kmh: float,
        slope_degrees: float,
    ) -> RateOfSpread:
        """
        Compute baseline and reduced Rate of Spread.

        Parameters
        ----------
        fmc : float
            Fuel moisture content (percent).
        wind_speed_kmh : float
            Wind speed (km/h).
        slope_degrees : float
            Terrain slope (degrees).

        Returns
        -------
        RateOfSpread
            Result containing baseline and reduced ROS.
        """
        wind_f = self.wind_factor(wind_speed_kmh)
        slope_f = self.slope_factor(slope_degrees)
        r_fmc = self.fmc_reduction_factor(fmc)

        ros_baseline = self.base_ros_m_per_min * wind_f * slope_f
        ros_reduced = ros_baseline * r_fmc

        return RateOfSpread(
            ros_baseline=float(ros_baseline),
            ros_reduced=float(ros_reduced),
            reduction_factor=float(r_fmc),
            fmc=float(fmc),
            wind_speed=float(wind_speed_kmh),
            slope_degrees=float(slope_degrees),
        )

    def fire_arrival_time(
        self,
        distance_m: float,
        fmc: float,
        wind_speed_kmh: float,
        slope_degrees: float,
    ) -> float:
        """
        Estimate fire arrival time (minutes) at a given distance.

        Parameters
        ----------
        distance_m : float
            Distance from fire front (metres).
        fmc : float
            Fuel moisture content (percent).
        wind_speed_kmh : float
            Wind speed (km/h).
        slope_degrees : float
            Terrain slope (degrees).

        Returns
        -------
        float
            Estimated arrival time in minutes.
        """
        ros = self.compute_ros(fmc, wind_speed_kmh, slope_degrees)
        if ros.ros_reduced <= 0:
            return float("inf")
        return float(distance_m / ros.ros_reduced)

    def evacuation_safety_margin(
        self,
        evacuation_window_min: float,
        fire_arrival_min: float,
        operational_margin_min: float,
        uncertainty_min: float,
    ) -> float:
        """
        Compute the Evacuation Safety Margin (ESM).

            ESM = t_evacuation_window - t_fire_arrival
                  - t_operational_margin - t_uncertainty

        A positive margin indicates that the evacuation can be completed with
        the required safety buffer before the fire front arrives. A negative
        margin signals an insufficient safety margin, requiring earlier
        evacuation or additional intervention.

        Parameters
        ----------
        evacuation_window_min : float
            Time available for evacuation (minutes).
        fire_arrival_min : float
            Fire arrival time (minutes).
        operational_margin_min : float
            Operational margin (minutes).
        uncertainty_min : float
            Uncertainty buffer (minutes).

        Returns
        -------
        float
            Evacuation Safety Margin (minutes). Negative indicates an
            insufficient safety margin.
        """
        return float(
            evacuation_window_min
            - fire_arrival_min
            - operational_margin_min
            - uncertainty_min
        )


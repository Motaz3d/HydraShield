"""
Raster/vector processing and protection zone mapping.

Computes the Critical Protection Zone (CPZ) around vulnerable assets and
evacuation corridors, based on fire arrival time and risk thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ProtectionZone:
    """A computed protection zone around an asset."""

    asset_id: str
    asset_type: str
    centroid: Tuple[float, float]
    radius_m: float
    area_m2: float
    risk_level: str  # 'green', 'yellow', 'red'
    fire_arrival_time_min: float

    def to_dict(self) -> Dict[str, object]:
        """Return zone as a dictionary."""
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "centroid": self.centroid,
            "radius_m": self.radius_m,
            "area_m2": self.area_m2,
            "risk_level": self.risk_level,
            "fire_arrival_time_min": self.fire_arrival_time_min,
        }


@dataclass
class ProtectionZoneMapper:
    """
    Compute Critical Protection Zones around vulnerable assets.

    Parameters
    ----------
    risk_threshold : float
        Probability-of-spread threshold theta for zone inclusion.
    min_lead_time_min : float
        Minimum acceptable fire arrival lead time (minutes).
    """

    risk_threshold: float = 0.5
    min_lead_time_min: float = 60.0

    def compute_zone_radius(
        self,
        fire_arrival_time_min: float,
        ros_m_per_min: float,
    ) -> float:
        """
        Compute the protection zone radius (metres) for a given lead time.

        radius = ROS * lead_time

        Parameters
        ----------
        fire_arrival_time_min : float
            Desired fire arrival lead time (minutes).
        ros_m_per_min : float
            Rate of spread (m/min).

        Returns
        -------
        float
            Protection zone radius in metres.
        """
        return float(max(fire_arrival_time_min, 0.0) * max(ros_m_per_min, 0.0))

    def classify_risk(
        self,
        probability_of_spread: float,
        fire_arrival_time_min: float,
    ) -> str:
        """
        Classify a zone into a traffic-light risk level.

        - 'green': low risk, sufficient lead time.
        - 'yellow': moderate risk, review required.
        - 'red': high risk, hold / manual reassessment.

        Parameters
        ----------
        probability_of_spread : float
            Probability of spread in [0, 1].
        fire_arrival_time_min : float
            Fire arrival lead time (minutes).

        Returns
        -------
        str
            Risk level: 'green', 'yellow', or 'red'.
        """
        if probability_of_spread < self.risk_threshold and fire_arrival_time_min >= self.min_lead_time_min:
            return "green"
        if probability_of_spread < 0.8 and fire_arrival_time_min >= self.min_lead_time_min * 0.5:
            return "yellow"
        return "red"

    def build_protection_zones(
        self,
        assets: List[Dict[str, object]],
        ros_m_per_min: float,
        probability_of_spread: float,
        lead_time_min: float,
    ) -> List[ProtectionZone]:
        """
        Build protection zones for a list of assets.

        Parameters
        ----------
        assets : List[Dict[str, object]]
            Each asset dict must contain 'id', 'type', and 'centroid'
            (a (lon, lat) tuple).
        ros_m_per_min : float
            Rate of spread (m/min).
        probability_of_spread : float
            Probability of spread in [0, 1].
        lead_time_min : float
            Fire arrival lead time (minutes).

        Returns
        -------
        List[ProtectionZone]
            Computed protection zones.
        """
        zones: List[ProtectionZone] = []
        radius = self.compute_zone_radius(lead_time_min, ros_m_per_min)
        risk = self.classify_risk(probability_of_spread, lead_time_min)

        for asset in assets:
            asset_id = str(asset.get("id", "unknown"))
            asset_type = str(asset.get("type", "asset"))
            centroid = tuple(asset.get("centroid", (0.0, 0.0)))

            zones.append(
                ProtectionZone(
                    asset_id=asset_id,
                    asset_type=asset_type,
                    centroid=centroid,
                    radius_m=radius,
                    area_m2=np.pi * radius * radius,
                    risk_level=risk,
                    fire_arrival_time_min=lead_time_min,
                )
            )
        return zones

    def compute_critical_area(
        self,
        zones: List[ProtectionZone],
        max_area_m2: Optional[float] = None,
    ) -> float:
        """
        Compute the total critical protection area.

        Optionally constrained by a maximum available area (water-scarce mode).

        Parameters
        ----------
        zones : List[ProtectionZone]
            Protection zones.
        max_area_m2 : Optional[float]
            Maximum allowable area (m^2).

        Returns
        -------
        float
            Total critical area (m^2).
        """
        total = sum(z.area_m2 for z in zones)
        if max_area_m2 is not None:
            total = min(total, max_area_m2)
        return float(total)

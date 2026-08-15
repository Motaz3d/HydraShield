"""
Real Earth Observation / weather / terrain / fire data fetchers.

Verified integrations used by HydraShield:

    - Geocoding ............ Nominatim (OpenStreetMap)            — free, no key
    - Weather (current) .... Open-Meteo forecast API              — free tier
    - Daily fire weather ... Open-Meteo daily series (past+forecast)
    - Reanalysis (ERA5) .... Open-Meteo archive API
    - Elevation / DEM ...... OpenTopoData (EU-DEM 25 m / SRTM)    — free, no key
    - Sentinel-2 EO ........ Element84 Earth Search STAC (real)   — free, no key
    - Active fires ......... NASA FIRMS (VIIRS/MODIS)  — free key (env var)

Every returned field carries an explicit ``source`` label so the UI never
confuses an observation, a reanalysis product, a DEM value, or a value that
was derived by a HydraShield model. There is no simulated data here: when a
source cannot answer, the field is reported as unavailable instead of being
invented.

All fetchers are cached (see ``cache.py``) to respect upstream rate limits
and to keep the API responsive.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .cache import cached, TTL_GEOCODE, TTL_TERRAIN, TTL_WEATHER_CURRENT, TTL_WEATHER_DAILY, TTL_FIRES

_UA = "HydraShield/1.0 (Earth Observation Decision Support; contact motaz3d@gmail.com)"
_TIMEOUT = 15.0
_RETRIES = 2


def _get_json(url: str, timeout: float = _TIMEOUT, retries: int = _RETRIES) -> Dict:
    """HTTP GET with JSON parsing, small retry loop and honest errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network / parse errors are retried
            last_exc = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Upstream request failed after {retries + 1} attempts: {last_exc}")


def _get_text(url: str, timeout: float = _TIMEOUT, retries: int = _RETRIES) -> str:
    """HTTP GET returning raw text (for CSV endpoints)."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Upstream request failed after {retries + 1} attempts: {last_exc}")


def _valid_point(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


# --------------------------------------------------------------------------
# Geocoding — Nominatim (OpenStreetMap)
# --------------------------------------------------------------------------

@cached("geocode", TTL_GEOCODE)
def geocode_location(query: str) -> Dict:
    """
    Resolve a free-text location name to a point.

    Uses Nominatim (OpenStreetMap). Returns ``{"name", "lat", "lon", "source"}``
    or ``{"error": ...}`` when the location cannot be resolved.
    """
    query = (query or "").strip()[:200]
    if not query:
        return {"error": "Empty location query"}
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    try:
        data = _get_json(f"https://nominatim.openstreetmap.org/search?{params}")
    except RuntimeError as exc:
        return {"error": f"Geocoding service unavailable: {exc}"}
    if not data:
        return {"error": f"Location not found: {query}"}
    top = data[0]
    return {
        "name": top.get("display_name", query),
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "source": "Nominatim (OpenStreetMap)",
    }


# --------------------------------------------------------------------------
# Elevation / terrain — OpenTopoData (EU-DEM 25 m, SRTM fallback)
# --------------------------------------------------------------------------

def _opentopodata_lookup(points: List[str], dataset: str) -> Optional[List[Optional[float]]]:
    """Query OpenTopoData for a list of 'lat,lon' strings; None on failure."""
    locations = "|".join(points)
    try:
        data = _get_json(
            f"https://api.opentopodata.org/v1/{dataset}?locations={locations}",
            timeout=20.0,
            retries=1,
        )
    except RuntimeError:
        return None
    if data.get("status") != "OK":
        return None
    out: List[Optional[float]] = []
    for r in data.get("results") or []:
        elev = r.get("elevation")
        out.append(float(elev) if elev is not None else None)
    return out


@cached("terrain", TTL_TERRAIN)
def fetch_terrain(lat: float, lon: float, step_deg: float = 0.002) -> Dict:
    """
    Fetch a 3x3 elevation grid and derive slope and aspect from it.

    Uses OpenTopoData. EU-DEM 25 m is tried first (Europe); outside its
    coverage the global SRTM 90 m dataset is used. ``step_deg`` controls grid
    spacing (0.002 deg ~ 220 m, matched to the DEM resolution). Slope is
    returned in degrees (0 == flat) and aspect in compass degrees.
    """
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}

    points: List[str] = []
    for i in range(3):
        lat_i = lat + (1 - i) * step_deg
        for j in range(3):
            lon_j = lon + (j - 1) * step_deg
            points.append(f"{lat_i:.6f},{lon_j:.6f}")

    dataset_used = None
    elevations: Optional[List[Optional[float]]] = None
    for dataset in ("eudem25m", "srtm90m"):
        elevations = _opentopodata_lookup(points, dataset)
        if elevations and all(e is not None for e in elevations):
            dataset_used = dataset
            break

    if dataset_used is None or elevations is None:
        return {"error": "No elevation data available for this location"}

    grid = [
        [float(elevations[i * 3 + j]) for j in range(3)]  # type: ignore[arg-type]
        for i in range(3)
    ]

    # Ground distance per degree (approximate, adequate at these scales).
    dx_m = 111_320.0 * step_deg * math.cos(math.radians(lat))
    dy_m = 110_540.0 * step_deg

    dz_dx = (grid[1][2] - grid[1][0]) / (2.0 * dx_m)
    dz_dy = (grid[0][1] - grid[2][1]) / (2.0 * dy_m)

    slope_deg = math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))
    aspect_rad = math.atan2(dz_dx, -dz_dy)
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0

    resolution = "25 m" if dataset_used == "eudem25m" else "90 m"
    return {
        "elevation_m": grid[1][1],
        "slope_degrees": round(slope_deg, 3),
        "aspect_degrees": round(aspect_deg, 2),
        "grid_elevations_m": grid,
        "cell_size_m": round((dx_m + dy_m) / 2.0, 1),
        "dataset": dataset_used,
        "resolution": resolution,
        "source": f"DEM (OpenTopoData {dataset_used}, {resolution})",
    }


@cached("elevation", TTL_TERRAIN)
def fetch_elevation(lat: float, lon: float) -> Dict:
    """Return elevation at a single point (OpenTopoData)."""
    terrain = fetch_terrain(lat, lon)
    if "error" in terrain:
        return {"error": terrain["error"]}
    return {"elevation_m": terrain["elevation_m"], "source": terrain["source"]}


# --------------------------------------------------------------------------
# Weather (current + daily fire-weather series + reanalysis)
# --------------------------------------------------------------------------

@cached("weather_current", TTL_WEATHER_CURRENT)
def fetch_weather_current(lat: float, lon: float) -> Dict:
    """
    Latest available weather for a point from Open-Meteo.

    Returns current temperature, relative humidity, wind speed/direction,
    precipitation, and surface soil moisture. These are weather-model output
    (labelled accordingly), not station observations.
    """
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                "wind_direction_10m,precipitation,soil_moisture_0_to_7cm"
            ),
            "timezone": "auto",
        }
    )
    try:
        data = _get_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    except RuntimeError as exc:
        return {"error": f"Weather service unavailable: {exc}"}
    cur = data.get("current") or {}
    units = data.get("current_units") or {}

    return {
        "temperature_c": cur.get("temperature_2m"),
        "relative_humidity_pct": cur.get("relative_humidity_2m"),
        "wind_speed_kmh": cur.get("wind_speed_10m"),
        "wind_direction_deg": cur.get("wind_direction_10m"),
        "precipitation_mm": cur.get("precipitation"),
        "soil_moisture_m3m3": cur.get("soil_moisture_0_to_7cm"),
        "timestamp": cur.get("time"),
        "units": units,
        "source": "Weather model (Open-Meteo)",
    }


@cached("weather_daily", TTL_WEATHER_DAILY)
def fetch_daily_fire_weather(lat: float, lon: float, past_days: int = 21, forecast_days: int = 7) -> Dict:
    """
    Daily fire-weather series (past + forecast) from Open-Meteo.

    One call returns daily aggregates for the recent past and the forecast,
    used to run the Canadian FWI System. Screening approximation for the
    noon-standard inputs: T_max, RH_min, mean wind, 24 h precipitation sum.
    """
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "relative_humidity_2m_min,relative_humidity_2m_mean,"
                "wind_speed_10m_mean,wind_speed_10m_max,precipitation_sum"
            ),
            "timezone": "auto",
            "past_days": min(max(past_days, 1), 92),
            "forecast_days": min(max(forecast_days, 1), 16),
        }
    )
    try:
        data = _get_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    except RuntimeError as exc:
        return {"error": f"Daily weather service unavailable: {exc}"}
    daily = data.get("daily") or {}
    times = daily.get("time") or []

    days: List[Dict] = []
    for i, t in enumerate(times):
        def _val(name: str):
            series = daily.get(name) or []
            return series[i] if i < len(series) else None

        days.append(
            {
                "date": t,
                "temp_max_c": _val("temperature_2m_max"),
                "temp_min_c": _val("temperature_2m_min"),
                "rh_min_pct": _val("relative_humidity_2m_min"),
                "rh_mean_pct": _val("relative_humidity_2m_mean"),
                "wind_mean_kmh": _val("wind_speed_10m_mean"),
                "wind_max_kmh": _val("wind_speed_10m_max"),
                "precipitation_mm": _val("precipitation_sum"),
            }
        )

    return {
        "days": days,
        "units": data.get("daily_units", {}),
        "source": "Weather model daily aggregates (Open-Meteo)",
        "note": (
            "FWI screening approximation: daily T_max / RH_min / mean wind / "
            "precipitation sum used in place of noon-standard inputs."
        ),
    }


@cached("weather_archive", TTL_WEATHER_DAILY)
def fetch_weather_archive(lat: float, lon: float, start_date: str, end_date: str) -> Dict:
    """
    Historical (reanalysis) daily weather from Open-Meteo archive (ERA5-based).

    Provides the temperature, relative humidity, wind and precipitation series
    needed for hindcasting and fire-danger context.
    """
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "relative_humidity_2m_mean,wind_speed_10m_max,precipitation_sum"
            ),
            "timezone": "auto",
        }
    )
    try:
        data = _get_json(f"https://archive-api.open-meteo.com/v1/archive?{params}")
    except RuntimeError as exc:
        return {"error": f"Reanalysis service unavailable: {exc}"}
    daily = data.get("daily") or {}
    return {
        "time": daily.get("time", []),
        "temperature_2m_max": daily.get("temperature_2m_max", []),
        "temperature_2m_min": daily.get("temperature_2m_min", []),
        "relative_humidity_2m_mean": daily.get("relative_humidity_2m_mean", []),
        "wind_speed_10m_max": daily.get("wind_speed_10m_max", []),
        "precipitation_sum": daily.get("precipitation_sum", []),
        "units": data.get("daily_units", {}),
        "source": "Reanalysis (ERA5 via Open-Meteo archive)",
    }


# --------------------------------------------------------------------------
# Active fires — NASA FIRMS (requires free MAP_KEY in env FIRMS_MAP_KEY)
# --------------------------------------------------------------------------

def firms_key_configured() -> bool:
    """Return True when a NASA FIRMS API key is configured."""
    return bool(os.environ.get("FIRMS_MAP_KEY"))


@cached("firms_fires", TTL_FIRES)
def fetch_active_fires(lat: float, lon: float, radius_km: float = 50.0, days: int = 5) -> Dict:
    """
    Fetch recent active-fire detections near a point from NASA FIRMS.

    Uses the FIRMS area CSV API (VIIRS S-NPP near-real-time, 375 m).
    Requires the free ``FIRMS_MAP_KEY`` environment variable (register at
    https://firms.modaps.eosdis.nasa.gov/api/area/). When no key is configured
    the layer is reported as unavailable — never fabricated.
    """
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        return {
            "error": "NASA FIRMS API key not configured (set FIRMS_MAP_KEY)",
            "fires": [],
            "available": False,
            "source": "NASA FIRMS (VIIRS S-NPP NRT)",
            "signup": "https://firms.modaps.eosdis.nasa.gov/api/area/",
        }
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}

    # Bounding box around the point (1 deg lat ~ 110.6 km).
    d_lat = radius_km / 110.6
    d_lon = radius_km / (111.3 * max(math.cos(math.radians(lat)), 0.01))
    bbox = f"{lon - d_lon:.3f},{lat - d_lat:.3f},{lon + d_lon:.3f},{lat + d_lat:.3f}"
    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{key}/VIIRS_SNPP_NRT/{bbox}/{min(max(days, 1), 10)}"
    )
    try:
        text = _get_text(url, timeout=30.0, retries=1)
    except RuntimeError as exc:
        return {
            "error": f"FIRMS service unavailable: {exc}",
            "fires": [],
            "available": False,
            "source": "NASA FIRMS (VIIRS S-NPP NRT)",
        }

    fires: List[Dict] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                fires.append(
                    {
                        "lat": float(row["latitude"]),
                        "lon": float(row["longitude"]),
                        "brightness_k": float(row.get("bright_ti4") or 0),
                        "frp_mw": float(row.get("frp") or 0),
                        "acq_date": row.get("acq_date"),
                        "acq_time_utc": row.get("acq_time"),
                        "confidence": row.get("confidence"),
                        "daynight": row.get("daynight"),
                    }
                )
            except (KeyError, ValueError):
                continue
    except Exception:
        return {
            "error": "Unexpected FIRMS response format",
            "fires": [],
            "available": False,
            "source": "NASA FIRMS (VIIRS S-NPP NRT)",
        }

    return {
        "fires": fires,
        "count": len(fires),
        "radius_km": radius_km,
        "days": days,
        "available": True,
        "resolution": "375 m (VIIRS)",
        "source": "NASA FIRMS (VIIRS S-NPP NRT)",
    }


# --------------------------------------------------------------------------
# Satellite — real Sentinel-2 via the Copernicus data access module
# --------------------------------------------------------------------------

def classify_source_label(kind: str) -> str:
    """Return a human-readable source label for the UI."""
    labels = {
        "weather": "Weather model",
        "reanalysis": "Reanalysis (ERA5)",
        "dem": "DEM",
        "model": "Model-derived",
        "satellite": "Satellite observation (Sentinel-2)",
        "fire": "Active fire detection (NASA FIRMS)",
    }
    return labels.get(kind, kind)


def fetch_satellite_data(lat: float, lon: float, days_back: int = 30) -> Dict:
    """
    Fetch the latest real Sentinel-2 observation for a location.

    Goes to the Copernicus data access module, which queries a public STAC
    catalog for real Level-2A scenes and computes NDVI/NDMI/NDWI from the
    actual spectral bands. Returns an ``error`` entry when no usable scene
    exists (e.g. persistent cloud cover) — nothing is fabricated.
    """
    from ..gis_mapping.copernicus_data import CopernicusDataAccess

    try:
        copernicus_access = CopernicusDataAccess()
        observation = copernicus_access.get_latest_observation(
            lat, lon, days_back=days_back, max_cloud_cover=40.0
        )

        if observation is None:
            return {
                "error": "No recent cloud-free Sentinel-2 scene available",
                "source": "Sentinel-2 L2A (Earth Search STAC)",
                "note": "Cloud cover or revisit gap may prevent observation in this area",
            }

        return {
            "ndvi": observation.ndvi,
            "ndmi": observation.ndmi,
            "ndwi": observation.ndwi,
            "cloud_cover_pct": observation.cloud_cover_pct,
            "observation_date": observation.timestamp.isoformat(),
            "source": f"Satellite observation ({observation.source})",
            "processing_level": observation.processing_level,
            "product_id": getattr(observation, "product_id", None),
            "resolution_m": getattr(observation, "resolution_m", None),
            "ndvi_grid": getattr(observation, "ndvi_grid", None),
            "ndmi_grid": getattr(observation, "ndmi_grid", None),
            "grid_bounds": getattr(observation, "grid_bounds", None),
        }
    except Exception as exc:
        return {
            "error": f"Satellite data fetch failed: {exc}",
            "source": "Sentinel-2 L2A (Earth Search STAC)",
        }

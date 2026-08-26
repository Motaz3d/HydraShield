"""
Real Earth Observation / weather / terrain / fire data fetchers.

Verified integrations used by Talaix:

    - Geocoding ............ Nominatim (OpenStreetMap)            — free, no key
    - Weather (current) .... Open-Meteo forecast API              — free tier
    - Daily fire weather ... Open-Meteo daily series (past+forecast)
    - Reanalysis (ERA5) .... Open-Meteo archive API
    - Elevation / DEM ...... OpenTopoData (EU-DEM 25 m / SRTM)    — free, no key
    - Sentinel-2 EO ........ Element84 Earth Search STAC (real)   — free, no key
    - Active fires ......... NASA FIRMS (VIIRS/MODIS)  — free key (env var)

Every returned field carries an explicit ``source`` label so the UI never
confuses an observation, a reanalysis product, a DEM value, or a value that
was derived by a Talaix model. There is no simulated data here: when a
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

from .cache import cached, TTL_GEOCODE, TTL_TERRAIN, TTL_WEATHER_CURRENT, TTL_WEATHER_DAILY, TTL_FIRES, TTL_CLIMATE_SERIES

_UA = "Talaix/1.0 (Climate Extreme Intelligence; contact info@talaix.com)"
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


@cached("geocode_rev", TTL_GEOCODE)
def reverse_geocode(lat: float, lon: float) -> Dict:
    """
    Resolve a point to its place name.

    Uses Nominatim (OpenStreetMap) reverse geocoding at settlement zoom.
    Returns ``{"name", "lat", "lon", "source"}`` or ``{"error": ...}`` —
    failures are returned, never raised, and a point with no named place
    nearby honestly falls back to its formatted coordinates as the name.
    """
    if not _valid_point(lat, lon):
        return {"error": "lat/lon out of range"}
    params = urllib.parse.urlencode(
        {"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "format": "jsonv2", "zoom": 14})
    try:
        data = _get_json(f"https://nominatim.openstreetmap.org/reverse?{params}")
    except RuntimeError as exc:
        return {"error": f"Reverse geocoding unavailable: {exc}"}
    name = (data or {}).get("display_name")
    if not name:
        # Ocean / unnamed terrain: the honest label is the coordinate itself.
        name = f"{lat:.4f}, {lon:.4f}"
    return {
        "name": name,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "source": "Nominatim (OpenStreetMap) reverse",
    }


# --------------------------------------------------------------------------
# Active tropical cyclones — GDACS (UN-OCHA / EU JRC), global, no key
# --------------------------------------------------------------------------

@cached("gdacs_tc", TTL_WEATHER_CURRENT)
def fetch_active_cyclones() -> Dict:
    """
    Active / ongoing tropical cyclones worldwide.

    Source: GDACS (Global Disaster Alert and Coordination System — UN-OCHA
    / EU JRC) event-list API, GeoJSON FeatureCollection of current ``TC``
    events with alert level, affected countries, validity window and the
    originating warning centre (``properties.source``, e.g. JTWC). Free,
    no key. Honest error dict on failure — never an invented storm list.
    """
    url = ("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
           "?eventtypes=TC")
    # NOTE: the GDACS edge blocks the branded Talaix User-Agent (HTTP
    # 403 to any UA containing the brand string, live-checked 2026-08-22),
    # so this request goes out with the default urllib UA. No Accept-based
    # or branded header is sent.
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"GDACS event list unavailable: {exc}"}
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return {"error": "GDACS returned an unexpected payload"}
    return {
        "features": data["features"],
        "source": "GDACS — Global Disaster Alert and Coordination System (UN-OCHA / EU JRC)",
        "request_url": url,
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


@cached("wind_profile", TTL_WEATHER_CURRENT)
def fetch_wind_profile(lat: float, lon: float, hours: int = 24) -> Dict:
    """
    Hourly wind profile for smoke-transport screening from Open-Meteo.

    Returns the 10 m wind plus the 850 hPa pressure-level wind (~1.5 km,
    a standard smoke-transport level) for the next ``hours`` hours. All
    values are numerical-weather-model output (labelled accordingly).

    ``transport_*`` is the wind level Talaix uses for transport
    screening: 850 hPa when available, else the 10 m wind with an explicit
    note that surface wind poorly represents a buoyant plume.
    """
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    hours = min(max(int(hours), 1), 48)
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": (
                "wind_speed_10m,wind_direction_10m,"
                "wind_speed_850hPa,wind_direction_850hPa"
            ),
            # The series starts at 00:00 UTC today; callers slice "from now",
            # so request enough days to cover the remaining day + horizon and
            # keep a generous slice of the series (not just the first hours).
            "forecast_days": min((hours // 24) + 2, 16),
            "timezone": "UTC",
        }
    )
    try:
        data = _get_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    except RuntimeError as exc:
        return {"error": f"Wind profile service unavailable: {exc}"}
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []

    def _series(name: str):
        return hourly.get(name) or []

    s10, d10 = _series("wind_speed_10m"), _series("wind_direction_10m")
    s850, d850 = _series("wind_speed_850hPa"), _series("wind_direction_850hPa")

    def _at(series, i):
        return series[i] if i < len(series) else None

    steps: List[Dict] = []
    for i, t in enumerate(times[: 24 + hours + 1]):
        sp850, dr850 = _at(s850, i), _at(d850, i)
        sp10, dr10 = _at(s10, i), _at(d10, i)
        if sp850 is not None and dr850 is not None:
            t_speed, t_dir, level = float(sp850), float(dr850), "850 hPa"
        elif sp10 is not None and dr10 is not None:
            t_speed, t_dir, level = float(sp10), float(dr10), "10 m"
        else:
            continue
        steps.append(
            {
                "time": t,
                "wind_10m_kmh": sp10,
                "wind_10m_dir_deg": dr10,
                "wind_850hPa_kmh": sp850,
                "wind_850hPa_dir_deg": dr850,
                "transport_speed_kmh": t_speed,
                "transport_dir_deg": t_dir,
                "transport_level": level,
            }
        )

    if not steps:
        return {"error": "No usable wind profile data returned"}

    level = steps[0]["transport_level"]
    return {
        "steps": steps,
        "hours": len(steps),
        "transport_level": level,
        "level_note": (
            "Transport uses the 850 hPa wind (~1.5 km), a standard smoke-transport level."
            if level == "850 hPa"
            else "Transport uses the 10 m surface wind (850 hPa unavailable) — surface "
                 "wind poorly represents a buoyant plume; treat direction as weaker guidance."
        ),
        "units": data.get("hourly_units", {}),
        "source": "Weather model hourly profile (Open-Meteo)",
    }


# --------------------------------------------------------------------------
# Active fires — NASA FIRMS (requires free MAP_KEY in env FIRMS_MAP_KEY)
# --------------------------------------------------------------------------

def firms_key_configured() -> bool:
    """Return True when a NASA FIRMS API key is configured."""
    return bool(os.environ.get("FIRMS_MAP_KEY"))


# Supported FIRMS area-CSV products: (product id, sensor label, resolution,
# brightness column).
FIRMS_PRODUCTS = {
    "VIIRS_SNPP_NRT": {
        "sensor": "VIIRS S-NPP",
        "resolution": "375 m",
        "brightness_col": "bright_ti4",
        "label": "NASA FIRMS (VIIRS S-NPP NRT)",
    },
    "MODIS_NRT": {
        "sensor": "MODIS (Terra/Aqua)",
        "resolution": "1 km",
        "brightness_col": "brightness",
        "label": "NASA FIRMS (MODIS NRT)",
    },
}


@cached("firms_fires", TTL_FIRES)
def fetch_active_fires(lat: float, lon: float, radius_km: float = 50.0,
                       days: int = 5, sensor: str = "VIIRS_SNPP_NRT") -> Dict:
    """
    Fetch recent active-fire detections near a point from NASA FIRMS.

    Uses the FIRMS area CSV API (near-real-time). Requires the free
    ``FIRMS_MAP_KEY`` environment variable (register at
    https://firms.modaps.eosdis.nasa.gov/api/area/). When no key is configured
    the layer is reported as unavailable — never fabricated.

    These are ACTIVE-FIRE DETECTIONS (hotspots with acquisition time,
    confidence and FRP): a detection is not an exact fire perimeter.
    """
    product = FIRMS_PRODUCTS.get(sensor, FIRMS_PRODUCTS["VIIRS_SNPP_NRT"])
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        return {
            "error": "NASA FIRMS API key not configured (set FIRMS_MAP_KEY)",
            "fires": [],
            "available": False,
            "sensor": sensor,
            "source": product["label"],
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
        f"{key}/{sensor}/{bbox}/{min(max(days, 1), 10)}"
    )
    try:
        text = _get_text(url, timeout=30.0, retries=1)
    except RuntimeError as exc:
        return {
            "error": f"FIRMS service unavailable: {exc}",
            "fires": [],
            "available": False,
            "sensor": sensor,
            "source": product["label"],
        }

    fires: List[Dict] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        bright_col = product["brightness_col"]
        for row in reader:
            try:
                fires.append(
                    {
                        "lat": float(row["latitude"]),
                        "lon": float(row["longitude"]),
                        "brightness_k": float(row.get(bright_col) or 0),
                        "frp_mw": float(row.get("frp") or 0),
                        "acq_date": row.get("acq_date"),
                        "acq_time_utc": row.get("acq_time"),
                        "confidence": row.get("confidence"),
                        "daynight": row.get("daynight"),
                        "sensor": product["sensor"],
                        "satellite": row.get("satellite"),
                        "product": sensor,
                        "version": row.get("version"),
                    }
                )
            except (KeyError, ValueError):
                continue
    except Exception:
        return {
            "error": "Unexpected FIRMS response format",
            "fires": [],
            "available": False,
            "sensor": sensor,
            "source": product["label"],
        }

    return {
        "fires": fires,
        "count": len(fires),
        "radius_km": radius_km,
        "days": days,
        "available": True,
        "sensor": sensor,
        "resolution": product["resolution"],
        "source": product["label"],
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


# --------------------------------------------------------------------------
# Multi-hazard climate fetchers (Stage 4)
#
#    - River discharge ... Open-Meteo Flood API (GloFAS, Copernicus EMS/JRC)
#    - Daily climate ...... Open-Meteo archive (ERA5 / ERA5-Land), generalised
#    - Ocean waves ........ Open-Meteo Marine API (ECMWF WAM)
#
# Recency-dependent caching is implemented by delegating to two cached
# helpers: ranges ending inside the recent window are cached briefly (6 h,
# the data is still being extended), settled historical ranges are cached
# long (24 h–30 d). Same error-dict convention as every fetcher above:
# callers never see an exception.
# --------------------------------------------------------------------------

TTL_ARCHIVE_SETTLED = 30 * 24 * 3600.0   # reanalysis ranges fully in the settled past
TTL_FLOOD_HISTORICAL = 24 * 3600.0       # GloFAS discharge history (daily updates)
_RECENT_SLACK_DAYS = 7                   # a range ending within this window is "recent"


def _date_or_none(value: str):
    """Parse an ISO date (YYYY-MM-DD), None when unparseable."""
    from datetime import date as _date

    try:
        return _date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _valid_range(start: str, end: str) -> bool:
    s, e = _date_or_none(start), _date_or_none(end)
    return s is not None and e is not None and s <= e


def _is_recent_end(end: str) -> bool:
    from datetime import date, timedelta

    e = _date_or_none(end)
    if e is None:
        return False
    return e >= date.today() - timedelta(days=_RECENT_SLACK_DAYS)


def _align_series(times: List, series: List) -> List:
    """Pad/trim a daily series to the time axis; values become float|None."""
    out: List = []
    for i in range(len(times)):
        v = series[i] if i < len(series) else None
        out.append(float(v) if v is not None else None)
    return out


# --------------------------------------------------------------------------
# River discharge — Open-Meteo Flood API (GloFAS, Copernicus EMS / EC JRC)
# --------------------------------------------------------------------------

FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"
FLOOD_DISCHARGE_SOURCE = (
    "GloFAS river discharge (Copernicus EMS / EC JRC via Open-Meteo Flood API)"
)


def _flood_discharge(lat: float, lon: float, start: str, end: str) -> Dict:
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    if not _valid_range(start, end):
        return {"error": "Invalid date range (expected ISO start_date <= end_date)"}
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge",
            "start_date": start,
            "end_date": end,
        }
    )
    url = f"{FLOOD_API_URL}?{params}"
    try:
        data = _get_json(url, timeout=30.0)
    except RuntimeError as exc:
        return {"error": f"Flood discharge service unavailable: {exc}"}
    if data.get("error"):
        return {
            "error": f"Flood discharge API error: {data.get('reason', 'unknown')}",
            "source": FLOOD_DISCHARGE_SOURCE,
        }
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    discharge = _align_series(times, daily.get("river_discharge") or [])
    if not times or all(v is None for v in discharge):
        return {
            "error": (
                "No modelled river discharge for this coordinate "
                "(no GloFAS river cell nearby or outside coverage)"
            ),
            "source": FLOOD_DISCHARGE_SOURCE,
        }
    return {
        "time": times,
        "river_discharge": discharge,
        "units": (data.get("daily_units") or {}).get("river_discharge", "m³/s"),
        "source": FLOOD_DISCHARGE_SOURCE,
        "request_url": url,
        "note": "Hydrological model output (GloFAS), not gauge observations.",
    }


@cached("flood_discharge_hist", TTL_FLOOD_HISTORICAL)
def _fetch_flood_discharge_hist(lat: float, lon: float, start: str, end: str) -> Dict:
    return _flood_discharge(lat, lon, start, end)


@cached("flood_discharge_recent", TTL_WEATHER_DAILY)
def _fetch_flood_discharge_recent(lat: float, lon: float, start: str, end: str) -> Dict:
    return _flood_discharge(lat, lon, start, end)


def fetch_flood_discharge(lat: float, lon: float, start: str, end: str) -> Dict:
    """
    Daily river discharge (m³/s) from the Open-Meteo Flood API.

    GloFAS-based (Copernicus EMS / EC JRC); historical record from 1984 per
    the API documentation. Ranges ending in the recent window are cached 6 h,
    settled historical ranges 24 h. Returns an honest error dict when the
    coordinate has no modelled river (e.g. no GloFAS cell nearby) — the
    caller must treat that as "no river discharge data here", not as zero.
    """
    if _is_recent_end(end):
        return _fetch_flood_discharge_recent(lat, lon, start, end)
    return _fetch_flood_discharge_hist(lat, lon, start, end)


# --------------------------------------------------------------------------
# Generalised daily archive — Open-Meteo archive API (ERA5 / ERA5-Land)
# --------------------------------------------------------------------------

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_CLIMATE_SOURCE = "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)"

#: Daily variables the multi-hazard modules rely on (validated server-side;
#: requesting anything else returns an honest error rather than a surprise).
DAILY_CLIMATE_VARIABLES = (
    "precipitation_sum",
    "temperature_2m_max",
    "wind_gusts_10m_max",
    "soil_moisture_0_to_7cm_mean",
    "et0_fao_evapotranspiration",
)


def _daily_climate(lat: float, lon: float, start: str, end: str, variables) -> Dict:
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    if not _valid_range(start, end):
        return {"error": "Invalid date range (expected ISO start_date <= end_date)"}
    variables = list(variables)
    if not variables:
        return {"error": "No daily variables requested"}
    unsupported = [v for v in variables if v not in DAILY_CLIMATE_VARIABLES]
    if unsupported:
        return {
            "error": (
                f"Unsupported daily variables: {', '.join(unsupported)}. "
                f"Supported: {', '.join(DAILY_CLIMATE_VARIABLES)}"
            )
        }
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "daily": ",".join(variables),
            "timezone": "auto",
        }
    )
    url = f"{ARCHIVE_API_URL}?{params}"
    try:
        data = _get_json(url, timeout=60.0)
    except RuntimeError as exc:
        return {"error": f"Reanalysis service unavailable: {exc}"}
    if data.get("error"):
        return {
            "error": f"Archive API error: {data.get('reason', 'unknown')}",
            "source": DAILY_CLIMATE_SOURCE,
        }
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    if not times:
        return {
            "error": "Archive returned no daily data for this range",
            "source": DAILY_CLIMATE_SOURCE,
        }
    out: Dict = {
        "time": times,
        "units": data.get("daily_units") or {},
        "source": DAILY_CLIMATE_SOURCE,
        "variables": variables,
        "request_url": url,
    }
    for var in variables:
        out[var] = _align_series(times, daily.get(var) or [])
    empty = [v for v in variables if all(x is None for x in out[v])]
    if empty:
        # Honest per-variable availability (e.g. soil moisture over the ocean).
        out["unavailable_variables"] = empty
    return out


@cached("daily_climate_hist", TTL_ARCHIVE_SETTLED)
def _fetch_daily_climate_hist(lat: float, lon: float, start: str, end: str, variables) -> Dict:
    return _daily_climate(lat, lon, start, end, variables)


@cached("daily_climate_recent", TTL_WEATHER_DAILY)
def _fetch_daily_climate_recent(lat: float, lon: float, start: str, end: str, variables) -> Dict:
    return _daily_climate(lat, lon, start, end, variables)


def fetch_daily_climate(lat: float, lon: float, start: str, end: str, variables) -> Dict:
    """
    Generalised daily archive fetcher (ERA5 / ERA5-Land via Open-Meteo).

    ``variables`` is a sequence of daily variable names (see
    ``DAILY_CLIMATE_VARIABLES``). Returns one aligned series per variable
    keyed by variable name. Settled ranges are cached 30 days, ranges ending
    in the recent window 6 h. Variables the archive does not expose for the
    point come back as null series listed under ``unavailable_variables`` —
    never silently filled.
    """
    variables = tuple(variables or ())
    if _is_recent_end(end):
        return _fetch_daily_climate_recent(lat, lon, start, end, variables)
    return _fetch_daily_climate_hist(lat, lon, start, end, variables)


# --------------------------------------------------------------------------
# Ocean waves — Open-Meteo Marine API (ECMWF WAM)
# --------------------------------------------------------------------------

MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"
MARINE_SOURCE = "Ocean wave analysis/forecast (ECMWF WAM via Open-Meteo Marine API)"


def _marine(lat: float, lon: float, start: str, end: str) -> Dict:
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    if not _valid_range(start, end):
        return {"error": "Invalid date range (expected ISO start_date <= end_date)"}
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "wave_height_max,wave_period_max",
            "start_date": start,
            "end_date": end,
            "timezone": "auto",
        }
    )
    url = f"{MARINE_API_URL}?{params}"
    try:
        data = _get_json(url, timeout=30.0)
    except RuntimeError as exc:
        return {"error": f"Marine service unavailable: {exc}"}
    if data.get("error"):
        return {
            "error": f"Marine API error: {data.get('reason', 'unknown')}",
            "source": MARINE_SOURCE,
        }
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    wave_height = _align_series(times, daily.get("wave_height_max") or [])
    wave_period = _align_series(times, daily.get("wave_period_max") or [])
    if not times or all(v is None for v in wave_height):
        return {
            "error": (
                "No marine data for this coordinate "
                "(likely over land or outside wave-model coverage)"
            ),
            "source": MARINE_SOURCE,
        }
    return {
        "time": times,
        "wave_height_max": wave_height,
        "wave_period_max": wave_period,
        "units": data.get("daily_units") or {},
        "source": MARINE_SOURCE,
        "request_url": url,
        "note": (
            "Wave-model output; dates up to the analysis time are a nowcast, "
            "later dates are a forecast."
        ),
    }


@cached("marine_hist", TTL_ARCHIVE_SETTLED)
def _fetch_marine_hist(lat: float, lon: float, start: str, end: str) -> Dict:
    return _marine(lat, lon, start, end)


@cached("marine_recent", TTL_WEATHER_DAILY)
def _fetch_marine_recent(lat: float, lon: float, start: str, end: str) -> Dict:
    return _marine(lat, lon, start, end)


def fetch_marine(lat: float, lon: float, start: str, end: str) -> Dict:
    """
    Daily wave height max (m) and wave period max (s) from the Open-Meteo
    Marine API (ECMWF WAM). Ranges ending in the recent window cached 6 h,
    settled ranges 30 days. Honest error dict for land points.
    """
    if _is_recent_end(end):
        return _fetch_marine_recent(lat, lon, start, end)
    return _fetch_marine_hist(lat, lon, start, end)


# --------------------------------------------------------------------------
# Climate series — long annual temperature / precipitation context (ERA5)
# --------------------------------------------------------------------------

@cached("climate_series", TTL_CLIMATE_SERIES)
def fetch_climate_series(lat: float, lon: float, start_year: int = 1991) -> Dict:
    """
    Annual temperature and precipitation series from the Open-Meteo archive
    (ERA5 / ERA5-Land). Computes a 1991–2020 baseline by default and reports
    the most recent complete year versus that baseline.

    Returns a dict with ``annual`` series, ``baseline``, and ``current``
    anomaly values, or an ``error`` key when the upstream service cannot
    answer.
    """
    if not _valid_point(lat, lon):
        return {"error": "Coordinates out of range"}
    from datetime import date

    today = date.today()
    end_year = today.year
    start_date = f"{int(start_year)}-01-01"
    end_date = f"{today.isoformat()}"

    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_max,precipitation_sum",
            "timezone": "auto",
        }
    )
    try:
        data = _get_json(f"{ARCHIVE_API_URL}?{params}", timeout=60.0)
    except RuntimeError as exc:
        return {"error": f"Reanalysis service unavailable: {exc}"}
    if data.get("error"):
        return {
            "error": f"Archive API error: {data.get('reason', 'unknown')}",
            "source": DAILY_CLIMATE_SOURCE,
        }

    daily = data.get("daily") or {}
    times = daily.get("time", [])
    tmax_series = daily.get("temperature_2m_max", [])
    precip_series = daily.get("precipitation_sum", [])
    if not times:
        return {"error": "Archive returned no daily data", "source": DAILY_CLIMATE_SOURCE}

    min_days_for_year = 300
    baseline_start, baseline_end = 1991, 2020

    years: Dict[int, Dict[str, Any]] = {}
    for i, t in enumerate(times):
        try:
            year = int(str(t)[:4])
        except (ValueError, TypeError):
            continue
        bucket = years.setdefault(year, {"tmax_values": [], "precip_values": [], "days": 0})
        tmax = tmax_series[i] if i < len(tmax_series) else None
        precip = precip_series[i] if i < len(precip_series) else None
        if tmax is not None:
            bucket["tmax_values"].append(float(tmax))
        if precip is not None:
            bucket["precip_values"].append(float(precip))
        bucket["days"] += 1

    annual: List[Dict[str, Any]] = []
    baseline_tmax: List[float] = []
    baseline_precip: List[float] = []
    for year in sorted(years):
        bucket = years[year]
        if bucket["days"] < min_days_for_year:
            continue
        if not bucket["tmax_values"] or not bucket["precip_values"]:
            continue
        mean_tmax = sum(bucket["tmax_values"]) / len(bucket["tmax_values"])
        total_precip = sum(bucket["precip_values"])
        record = {
            "year": year,
            "mean_tmax_c": round(mean_tmax, 2),
            "total_precip_mm": round(total_precip, 1),
            "days_used": bucket["days"],
        }
        annual.append(record)
        if baseline_start <= year <= baseline_end:
            baseline_tmax.append(mean_tmax)
            baseline_precip.append(total_precip)

    if not annual:
        return {"error": "No complete years of climate data", "source": DAILY_CLIMATE_SOURCE}

    current = annual[-1]
    baseline: Dict[str, Any] = {"period": f"{baseline_start}–{baseline_end}"}
    if baseline_tmax:
        baseline["mean_tmax_c"] = round(sum(baseline_tmax) / len(baseline_tmax), 2)
        baseline["precip_mm"] = round(sum(baseline_precip) / len(baseline_precip), 1)
        baseline["years_used"] = len(baseline_tmax)
    else:
        baseline["mean_tmax_c"] = None
        baseline["precip_mm"] = None
        baseline["years_used"] = 0

    current_anomaly: Dict[str, Any] = {"year": current["year"]}
    if baseline["mean_tmax_c"] is not None:
        current_anomaly["mean_tmax_anomaly_c"] = round(
            current["mean_tmax_c"] - baseline["mean_tmax_c"], 2
        )
    else:
        current_anomaly["mean_tmax_anomaly_c"] = None
    if baseline["precip_mm"] is not None and baseline["precip_mm"] > 0:
        current_anomaly["precip_pct_of_baseline"] = round(
            100.0 * current["total_precip_mm"] / baseline["precip_mm"], 1
        )
    else:
        current_anomaly["precip_pct_of_baseline"] = None

    return {
        "annual": annual,
        "baseline": baseline,
        "current": current_anomaly,
        "series_end_year": current["year"],
        "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
        "variables": {"temperature": "daily maximum 2 m temperature", "precipitation": "daily sum"},
    }

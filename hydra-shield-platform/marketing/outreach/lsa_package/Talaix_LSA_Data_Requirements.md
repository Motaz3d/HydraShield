# Talaix — Earth-Observation Data Requirements

Prepared for the Luxembourg Space Agency · September 2026
Motaz Omarien, Founder · info@talaix.com · talaix.com

## 1. Purpose

This document answers one question precisely: what information does Talaix need from satellites. The platform is live today and already runs on open Earth-observation (EO) data. Section 2 lists what is integrated in production; Section 3 lists exactly what we need next — sensor, resolution, revisit and the reason for each item.

## 2. What the platform uses today (integrated, in production)

| Variable | Mission / sensor | Resolution | Revisit / latency | Used for |
|---|---|---|---|---|
| Vegetation & fuel state, burn scars | Sentinel-2 L2A | 10–20 m | 5 days | wildfire, drought, land-use |
| Optical fallback archive | Landsat 8/9 Coll. 2 L2 | 30 m | 8 days combined | gap filling, history |
| Active fires (NRT) | VIIRS S-NPP (NASA FIRMS) | 375 m | ~3 h latency | wildfire detection & alerts |
| Active fires (NRT) | MODIS (NASA FIRMS) | 1 km | ~3 h latency | wildfire detection |
| Land cover | ESA WorldCover v200 | 10 m | annual | exposure & fuel models |
| Elevation (Europe) | EU-DEM (Copernicus/EEA) | 25 m | static | flood, slope, fire spread |
| Elevation (global) | SRTM (NASA) | 90 m | static | same, outside Europe |
| Fire weather & climate history | ERA5 / ERA5-Land (C3S) | 25 / 11 km | hourly, 1940 to now | FWI, drought, heat, wind |
| Soil moisture 0–7 cm | ERA5-Land (C3S) | 11 km | hourly | drought |
| River discharge | GloFAS (EMS/JRC) + GEOGLOWS | ~10 km / river reaches | daily forecasts | flood |
| Aerosols / dust | CAMS (ECMWF) | 10–40 km | forecasts | dust & smoke exposure |
| Cyclone tracks | IBTrACS + GDACS (JRC) | storm fixes | 3-hourly | tropical cyclones |

Note: ERA5, GloFAS and CAMS are model/reanalysis products fed by satellite and in-situ observations — EO-derived data. Together with official non-satellite sources (Open-Meteo, USGS, WorldPop, OpenStreetMap), the platform integrates ~25 datasets selected from a 168-source audited observatory.

## 3. What we need next — the precise requirements

| Priority | Requirement | Mission / sensor | Resolution | Revisit | Why |
|---|---|---|---|---|---|
| P1 | Flood extent through clouds, all-weather | Sentinel-1 SAR (IW, VV/VH) | 10 m | 6 days | flood mapping & damage evidence — our #1 gap |
| P2 | Better terrain for flood & slope | Copernicus DEM GLO-30 | 30 m | static | replaces 90 m SRTM outside Europe |
| P3 | Land-surface temperature for heat | Landsat 8/9 TIRS; later ESA LSTM | 100 m | 8–16 days | urban-heat evidence at asset level |
| P4 | Daily coarse fire & temperature coverage | Sentinel-3 SLSTR | 500 m–1 km | daily | fills VIIRS gaps, fire radiative power |
| P5 | Smoke & dust exposure (NO2, aerosol) | Sentinel-5P TROPOMI | ~5 km | daily | health-relevant exposure evidence |
| P6 | Burned-area history (training labels) | MODIS MCD64A1 | 500 m | monthly | fire-severity validation |
| P7 | Very-high-resolution optical for asset validation | Pléiades / Pléiades Neo (Airbus, via ESA TPM) | 0.3–0.5 m | on demand | verifies site findings for paying customers |
| P8 | NRT SAR tasking during flood events | ICEYE or equivalent (commercial) | 1–3 m | hours | event-response evidence while floods unfold |

P1–P6 are open Copernicus/NASA products — the work is integration, plus guidance on doing it right. P7–P8 are commercial; we need them only for paid validation cases, and they are unaffordable for a bootstrapped pre-company project without an access scheme.

## 4. Latency and refresh requirements by product

| Product | Refresh needed | Latency tolerance |
|---|---|---|
| Compliance evidence packs (CSRD/ESRS E1, EUDR) | annual + on request | days are acceptable |
| Monitoring subscriptions | weekly | 24–48 h |
| Event alerts (wildfire, flood) | per event | max 3 h (near-real-time) |

## 5. Volumes

Analysis is on demand per site coordinate via STAC/APIs — no bulk archive is required. Initial volume is hundreds of scenes per month and scales with customers. Cloud-native access (Copernicus Data Space Ecosystem, Element84 Earth Search, Microsoft Planetary Computer) is preferred.

## 6. What we ask the Luxembourg Space Agency to help with

1. Guidance on CDSE integration and on any national data-access support for early-stage companies (vouchers, ESA schemes).
2. An access route for the commercial VHR items (P7–P8) — ESA Third Party Missions, contributing missions, or vouchers — for paid validation cases only.
3. A validation partner (LIST, SnT) to raise the flood and wildfire layers from screening-level to validated.
4. Programme fit: ESA BIC Luxembourg or LuxIMPULSE — and whether a pre-company project can apply before incorporation.

## 7. Honest status

Our assessments are screening-level today; every value the platform produces carries its source, reference date and evidence status, and "unavailable" is stated rather than filled in. The requirements listed above are exactly what raises the platform to a validated, commercial tier — that is the purpose of this document.

# HydraShield Earth Observation Source Audit

**Date:** 2026-08-17 · **Registry:** `config/source_registry.json` (served at `GET /api/sources`)

## Method

Every candidate dataset was evaluated against: scientific quality, spatial
resolution, temporal resolution, coverage, latency, historical depth,
license, API/access method, reliability, documentation, uncertainty, and
relevance to wildfire prevention/validation. A source is listed as
**integrated** only when it is actually wired into the live pipeline —
never for branding.

## Decisions

### Integrated (in production, real)
- **Copernicus Sentinel-2 L2A** (Earth Search STAC) — NDVI/NDMI, fuel moisture, 10 m.
- **Open-Meteo forecast** — current/forecast weather, soil moisture, FWI inputs (~11 km); hourly 10 m + 850 hPa wind profiles for smoke-transport screening.
- **ERA5/ERA5-Land via Open-Meteo archive** (Copernicus C3S) — history, change detection, validation.
- **EU-DEM 25 m / SRTM 90 m** (OpenTopoData) — terrain, slope, aspect.
- **ESA WorldCover v200** — land cover, burnability, fuel model (10 m).
- **NASA FIRMS VIIRS/MODIS** — active-fire detections, observed-fire locations for smoke transport, and validation labels; **activates with `FIRMS_MAP_KEY`** (currently unavailable — no key configured; see docs/VALIDATION.md).
- **OpenStreetMap** (ohsome API; Overpass fallback) — exposure/vulnerability/access features.
- **Nominatim** — geocoding + reverse country lookup for the population raster.
- **WorldPop** (Global 2 R2025A constrained 100 m; Global 1 2020 UN-adjusted fallback) — gridded population estimates for human-exposure analysis and smoke-corridor population overlay. Per-country GeoTIFF downloaded **once** into `data/population/` (400 MB guard); all reads are local afterwards. Always reported with its reference year; never as an exact count.

### Population candidates (evaluated 2026-08-17, honestly not yet integrated)
- **GHSL / GHS-POP (JRC)** — global 100 m/1 km population + built-up grid; candidate cross-check for WorldPop and settlement/built-up exposure.
- **GPWv4 (NASA SEDAC)** — ~1 km census grid; Earthdata login; coarser and older than WorldPop — fallback candidate only.
- **Eurostat GEOSTAT 1 km grid** — authoritative EU census grid (2021); Europe-only — candidate European reference cross-check.

### Smoke / atmospheric candidates (evaluated 2026-08-17)
- **CAMS (ECMWF Copernicus Atmosphere Monitoring Service)** — global/regional aerosol + PM forecasts via the Atmosphere Data Store; requires free CDS credentials (`CAMS_ADS_URL`/`CAMS_ADS_KEY`). Candidate for smoke context and future validation of transport estimates. Not wired: credentials not configured.
- **NOAA HYSPLIT** — reference-grade Lagrangian transport model; READY web is interactive-only and programmatic use needs a local install plus a meteorological data pipeline. Candidate as an optional offline/reference comparison, not in the request path.
- **Sentinel-5P TROPOMI** — daily aerosol index / NO2 (~5 km). Moved from rejected to candidate: Smoke Intelligence now defines a purpose (observed cross-check of smoke transport); requires CDSE credentials.

### Other candidates (evaluated, honestly not yet integrated)
- **EFFIS/GWIS** — probed 2026-08-16: the public WMS is view-only
  (GetFeatureInfo disabled on danger layers). Candidate for reference
  comparison and burned-area perimeters once a genuine access path exists.
- **Copernicus Data Space Ecosystem** — enables Sentinel-1 SAR and
  Sentinel-3 SLSTR LST; requires OAuth2 credentials. Candidate.
- **CLMS Global Burnt Area (300 m)** — validation labels + post-fire
  recovery; requires CLMS/WEkEO credentials. Candidate.
- **MODIS MCD64A1** — monthly burned area; requires NASA Earthdata login.
  Candidate (validation).
- **Copernicus DEM GLO-30** (AWS open data) — global DEM upgrade for
  non-European areas. Candidate.
- **Global Forest Watch** — largely duplicates FIRMS (same VIIRS source).
  Backup candidate only.

### Rejected (with reasons)
- **FY-3/FY-4 (CMA)** — registration/approval barrier, programmatic API
  unclear, license verification needed; no unique gap filled for the
  current European monitored areas.
- **National Tibetan Plateau Data Center** — regional coverage mismatch.
- **Blitzortung / lightning networks** — raw data requires a contributor
  agreement; no open operational API. Lightning is a declared gap in the
  ignition-likelihood indicator (natural ignitions are not predicted).

## Fire-evidence architecture

Multiple fire sources can contribute evidence **without merging identity**:
`fire_evidence` in the analysis lists one entry per source (FIRMS VIIRS,
FIRMS MODIS) with its own status, resolution, freshness and detections.
When sources disagree, the disagreement is shown with an interpretation
note (e.g. VIIRS 375 m detects smaller fires than MODIS 1 km). Active-fire
detections, burned-area products and historical fire labels are kept as
strictly distinct observation types.

## Configuring NASA FIRMS

1. Register a free key at https://firms.modaps.eosdis.nasa.gov/api/area/
2. Locally: `export FIRMS_MAP_KEY=...`
3. Production: add `FIRMS_MAP_KEY=...` to `.env` next to
   `docker-compose.yml` (already wired into the `api` and `watch_checker`
   services), then `docker compose up -d`.
4. The key is never printed, logged, committed or returned by any endpoint
   (only the boolean `firms_configured` is exposed via `/api/health`).

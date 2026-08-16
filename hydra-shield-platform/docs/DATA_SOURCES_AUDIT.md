# HydraShield Earth Observation Source Audit

**Date:** 2026-08-16 · **Registry:** `config/source_registry.json` (served at `GET /api/sources`)

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
- **Open-Meteo forecast** — current/forecast weather, soil moisture, FWI inputs (~11 km).
- **ERA5/ERA5-Land via Open-Meteo archive** (Copernicus C3S) — history, change detection, validation.
- **EU-DEM 25 m / SRTM 90 m** (OpenTopoData) — terrain, slope, aspect.
- **ESA WorldCover v200** — land cover, burnability, fuel model (10 m).
- **NASA FIRMS VIIRS/MODIS** — active-fire detections and validation labels; **activates with `FIRMS_MAP_KEY`** (currently unavailable — no key configured; see docs/VALIDATION.md).
- **OpenStreetMap** (ohsome API; Overpass fallback) — exposure/vulnerability/access features.
- **Nominatim** — geocoding.

### Candidates (evaluated, honestly not yet integrated)
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
- **Sentinel-5P** — atmospheric composition; no defined purpose in the
  current fire-danger model.
- **FY-3/FY-4 (CMA)** — registration/approval barrier, programmatic API
  unclear, license verification needed; no unique gap filled for the
  current European monitored areas.
- **National Tibetan Plateau Data Center** — regional coverage mismatch.

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

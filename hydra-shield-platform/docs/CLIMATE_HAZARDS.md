# Talaix — Climate Hazards

**Status:** hazard ontology + per-hazard data foundations.
Implements the "common hazard architecture" of `PRODUCT_VISION.md`.

---

## 1. Ontology

The platform models every hazard with the same ten concepts:

| Concept | Meaning | Example (wildfire) |
|---|---|---|
| **Hazard** | A class of climate extreme | wildfire |
| **Event** | A concrete occurrence in space and time | fire near X, 2024-08-12 → 2024-08-15 |
| **Observation** | A measured fact from an instrument/authority | VIIRS detection, FRP 42 MW, 375 m |
| **Forecast** | A short-horizon prediction from a model chain | Open-Meteo 7-day wind/rain |
| **Exposure** | Who/what is in the affected area | 214 buildings, 1 hospital, WUI signal |
| **Impact** | Documented consequence (never invented) | documented burned area where available |
| **Response** | Containment/intervention information | documented suppression actions |
| **Solution** | A measure that reduces exposure/susceptibility | fuel management, early warning |
| **Evidence** | A traceable record behind any claim | source, dataset, date, method, link |
| **Uncertainty** | Explicit limits of knowledge | sensor disagreement, resolution, gaps |

Classification vocabulary (applies to events and claims):

- `OBSERVED` — measured by an instrument or authority at the time/place.
- `DOCUMENTED` — established in an authoritative report/record.
- `REPORTED` — stated by a credible secondary source (incl. media); never
  overrides OBSERVED/DOCUMENTED.
- `MODELLED` — produced by a declared model from declared inputs.
- `INFERRED` — derived by reasoning over other evidence; method stated.
- `UNKNOWN` — no adequate evidence. A valid, respected answer.

Temporal vocabulary: `OBSERVED` (now/current window) · `HISTORICAL` (past
record) · `FORECAST` (short-horizon model) · `PROJECTED` (long-horizon
climate projection) · `SCENARIO` (conditional what-if). Projections and
scenarios are never presented as observations.

## 2. Hazard registry

Hazards are plugins (`src/climate/hazards/`). A hazard is registered only
when wired to at least one real, documented data source. Current registry:

| Hazard | Status | Primary real sources (key-free unless noted) |
|---|---|---|
| Wildfire | **operational** | Open-Meteo + ERA5, Sentinel-2 (Element84 STAC), ESA WorldCover, EU-DEM/SRTM, NASA FIRMS (**free key**), OSM/ohsome |
| Flood | foundation | Open-Meteo Flood API (GloFAS river discharge, Copernicus EMS/JRC) + GEOGLOWS ECMWF streamflow as second provider (side-by-side, never merged), ERA5 precipitation (accumulation + antecedent index), DEM (flow-relevant terrain), OSM waterway context, GDACS FL current flood alerts (events layer) |
| Drought | foundation | ERA5/ERA5-Land via Open-Meteo archive: precipitation deficit, standardized anomaly (declared method), soil moisture (0–7 cm), ET₀, NDMI (Sentinel-2), WorldCover agriculture exposure |
| Extreme heat | foundation | ERA5 daily Tmax series: percentile vs same-location climatology, heatwave spell detection (WMO-style ≥5 days above climatological threshold, declared method) |
| Extreme wind | foundation | ERA5/Open-Meteo daily wind gust maxima: percentile vs climatology, storm spell detection |
| Coastal / sea | foundation | Open-Meteo Marine API (wave height/period, observed + forecast), DEM coastal elevation, OSM coastline/infrastructure exposure; sea-level rise only as labelled `PROJECTED/SCENARIO` with published-source figures |
| Other hazards | gated | added only when a real documented source is integrated |

**No fake placeholders.** A hazard without a real wired source does not
appear in the registry, the navigation, or the map.

## 3. Historical depth

The map and the events engine support **every year the underlying datasets
contain** — never a hardcoded year list:

- ERA5/ERA5-Land via Open-Meteo archive: 1940 → near-present (daily).
- NASA FIRMS archive queries (with key): VIIRS 2012 → present,
  MODIS 2000 → present (10-day query windows).
- GloFAS via Open-Meteo Flood API: historical discharge record as exposed
  by the API (from 1984, per Open-Meteo documentation).
- Sentinel-2: 2017 → present (EO evidence windows).

The API exposes the actually-available temporal coverage per dataset
(`GET /api/v2/hazards` → `temporal_coverage`), and the UI builds its year
selector from that response.

## 4. Per-hazard analysis foundations

### 4.1 Wildfire (existing — wrapped, not rewritten)

Full pipeline: FWI System (Van Wagner 1987), FMC from NDMI, Rothermel-style
spread, composite risk 0–100, FIRMS evidence, exposure, recommendations,
hydration scenarios. See README and `src/dashboard/real_analysis.py`.

### 4.2 Flood

Foundation analyses (all real-data):

- **River discharge intelligence** — daily river discharge from the
  Open-Meteo Flood API (GloFAS, Copernicus EMS / EC JRC): current + long
  historical series; return-period context where the dataset provides it;
  high-discharge spell detection with declared thresholds.
- **Extreme precipitation analysis** — ERA5 daily precipitation: event
  totals, antecedent precipitation index (declared decay), percentile vs
  climatology.
- **Terrain context** — DEM elevation/slope (existing OpenTopoData
  fetchers) as flow-relevant context, clearly labelled as terrain only —
  **not** a hydraulic flood model.
- **Exposure** — OSM waterway proximity, buildings, critical facilities in
  the analysis radius (existing exposure layer).
- **Explicitly not claimed:** flood extent maps, flood *forecasts*, depth
  grids. Where only historical/modelled data exists, labels say so.
  Sentinel-1 flood extent and EFAS are registry candidates for a later
  stage.

### 4.3 Drought

- **Precipitation deficit** — ERA5 daily precipitation: accumulated
  deficit vs climatological normal over 30/90/180-day windows (declared
  method; not a full SPEI unless the fitting is implemented and declared).
- **Soil moisture** — ERA5-Land soil moisture 0–7 cm via Open-Meteo
  archive: current anomaly vs climatology.
- **Atmospheric demand** — FAO ET₀ (Open-Meteo daily) vs precipitation
  balance.
- **Vegetation stress** — NDMI from the existing Sentinel-2 pipeline
  (10 m, observed).
- **Agricultural exposure** — WorldCover cropland class in the analysis
  window (observed land cover), OSM farmland context.
- **Severity/duration/trend** — spell detection on the deficit series;
  comparison to the same window in previous years (historical comparison).

### 4.4 Extreme heat

- ERA5 daily Tmax: climatological percentile of recent/current values
  (same grid point, same day-of-year window, declared baseline period).
- Heatwave spells: runs of days above the climatological 90th percentile
  (declared method, WMO-style).
- Historical comparison: hottest events on record at the location (from
  the ERA5 series itself).
- Exposure: population-proxy (OSM buildings/places), urban land cover
  (WorldCover built-up), cooling-relevant context.

### 4.5 Extreme wind

- ERA5/Open-Meteo daily wind-gust maxima: percentile vs climatology,
  storm spell detection, historical extreme-wind event windows from the
  series.
- Exposure: OSM infrastructure context (power lines, towers where mapped).

### 4.6 Coastal / sea exposure

- **Observed/historical:** Open-Meteo Marine API wave height/period
  (observed + forecast, labelled); DEM elevation at the coast
  (low-elevation exposure screening, declared as screening); OSM coastal
  infrastructure exposure (ports, tourism, industry where mapped).
- **Projected/scenario:** sea-level-rise figures only from published
  authoritative sources (e.g. IPCC AR6), stored as sourced constants with
  scenario labels (`PROJECTED`/`SCENARIO`) — never mixed into observations.
- **Not claimed:** storm-surge modelling, erosion rates, flood extents.

## 5. Data source matrix

| Source | Hazards | Access | Status |
|---|---|---|---|
| Open-Meteo forecast + archive (ERA5/ERA5-Land) | all | key-free | integrated |
| Open-Meteo Flood API (GloFAS) | flood | key-free | integrated (foundation) |
| Open-Meteo Marine API | coastal | key-free | integrated (foundation) |
| Open-Meteo Climate API (CMIP6 scenarios) | projections | key-free | candidate — projected layer |
| NASA FIRMS | wildfire | free key | integrated |
| Sentinel-2 via Element84 STAC | wildfire, drought | key-free | integrated |
| ESA WorldCover | all (exposure) | key-free | integrated |
| OpenTopoData (EU-DEM/SRTM) | all (terrain) | key-free | integrated |
| OSM Nominatim / Overpass / ohsome | all (exposure) | key-free | integrated |
| EFAS / EFFIS / GWIS | flood, wildfire | open (Copernicus EMS) | candidate |
| Sentinel-1 SAR (flood extent) | flood | open (CDSE/ASF) | candidate — credential required |
| Copernicus Marine / C3S | coastal | open (registration) | candidate — credential required |
| GHSL / WorldPop population | exposure | open | research required |

Every integrated source is registered in `config/source_registry.json`
with provider, resolution, update frequency, license, limitations and
`hydrashield_use` — and is served at `/api/sources`.

## 6. Expansion candidates (registered, honestly unavailable)

The registry also carries two expansion hazards with real sources but no
integrated pipeline yet — they appear in `/api/v2/hazards` with
`analysis.available: false` and the reason stated, never as working
features:

- **dust** (dust / sandstorm) — candidate sources: CAMS (requires ADS
  credentials) and WMO SDS-WAS. Regional terms (Sirocco, Khamsin, dust
  transport) are related but not identical; any pipeline must classify by
  the source's own terminology. Analysis and events both unavailable.
- **volcanic** — the **events layer went live 2026-09** via the GDACS
  ``VO`` feed (current volcanic-activity alerts worldwide — monitoring
  context only, `events.available: true`). **Analysis stays honestly
  unavailable**: the authoritative historical source (Smithsonian/USGS
  Global Volcanism Program) is bot-protected for automated access and
  needs a dataset export path. Talaix never predicts eruptions; current
  capability is alert-monitoring context only.

Enabling dust or volcanic analysis requires a real, tested fetch path first.

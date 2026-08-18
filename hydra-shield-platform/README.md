# HydraShield Platform

**HydraShield — Climate Extreme Intelligence + Economic Decision Support.**

HydraShield brings together science, earth observation, open data and
historical evidence to understand climate extremes — wildfire, flood,
drought, extreme heat, extreme wind and coastal exposure — who and what
they affect, what they mean economically, and which sustainable solutions
fit each exact place. The central promise:

> "We bring together the best available evidence to understand environmental
> extremes, their consequences, their economic meaning, and the actions that
> can reduce exposure."

The platform began as — and continues to develop as a clearly-labelled
R&D track — a wildfire protection programme combining DeepTech,
AI/satellite data, and environmental protection via subsurface hydration
barriers. That programme is powered by the intelligence platform and
claims no validated prevention capability (see `docs/PRODUCT_STORY.md`).

**Product evolution docs** (read these first):
`docs/PRODUCT_STORY.md` · `docs/STRATEGIC_EVOLUTION_PLAN.md` ·
`docs/PRODUCT_VISION.md` · `docs/PLATFORM_ARCHITECTURE.md` ·
`docs/CLIMATE_HAZARDS.md` · `docs/EVIDENCE_ARCHITECTURE.md` ·
`docs/ECONOMIC_INTELLIGENCE.md` · `docs/FINANCIAL_INTELLIGENCE.md` ·
`docs/SOLUTIONS_INTELLIGENCE.md` · `docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md` ·
`docs/IMPLEMENTATION_ROADMAP.md` · `docs/QGIS_INTEGRATION_ARCHITECTURE.md`

**Business/operations docs:**
`docs/SOLUTIONS_INTELLIGENCE.md` · `docs/PRODUCT_ANALYTICS.md` ·
`docs/MARKETING_INTELLIGENCE.md` · `docs/CUSTOMER_SEGMENTATION.md` ·
`docs/LINKEDIN_STRATEGY.md` · `docs/CONTENT_STRATEGY.md` ·
`docs/CONVERSION_STRATEGY.md` · `docs/EXTERNAL_INTEGRATIONS.md` ·
`docs/COMMERCIAL_INTELLIGENCE.md` · `docs/ANNUAL_CLIMATE_EXTREME_REPORT.md` ·
`docs/SUSTAINABILITY_INTELLIGENCE.md`

## Project Structure

```
hydra-shield-platform/
├── docs/          # Product/architecture docs + proposal and pitch documents
├── data/          # Raw and processed fire data and Copernicus maps
├── src/           # Main source code
│   ├── climate/           # Multi-hazard intelligence core: ontology, evidence,
│   │                      # event model, hazard plugins (wildfire/flood/drought/
│   │                      # heat/wind/coastal), economic exposure, solutions
│   ├── prediction/        # Fire risk & spread prediction (ML + physics)
│   ├── gis_mapping/       # Earth Observation ingestion & GIS processing
│   ├── hydration_control/ # Protection optimisation & water planning
│   ├── dashboard/         # API, analysis engine, reports, accounts, mailer
│   └── security/          # Auth/token/GDPR/encryption primitives
├── notebooks/     # Jupyter notebooks for data analysis
│   ├── 01_fire_risk_analysis.ipynb — FMC estimation, fire spread modelling, ML risk assessment with ensemble methods and uncertainty quantification, and dynamic data fusion with adaptive weights.
│   ├── 02_protection_optimisation.ipynb — Protection zones, water allocation, and intervention planning.
│   └── dashboard.html — Interactive dashboard with real-time monitoring and decision support system.
├── tests/         # Testing files
└── website/       # Public website: intelligence, map, events, solutions, economy, reports
```

## Climate-intelligence core (`src/climate/`)

- **`ontology.py`** — the platform vocabulary: hazard types, claim status
  (`OBSERVED | DOCUMENTED | REPORTED | MODELLED | INFERRED | UNKNOWN`),
  temporal classes (`OBSERVED | HISTORICAL | FORECAST | PROJECTED | SCENARIO`),
  evidence classes, cause discipline (cause is DOCUMENTED or UNKNOWN — never
  inferred from media or models).
- **`evidence.py`** — one typed `EvidenceRecord` behind every claim (source,
  dataset, period, method, resolution, confidence, license, limitations,
  content hash) + legacy provenance upgrade (`modeled`→`modelled` aliases).
- **`events.py`** — the historical event model (`ClimateEvent`) + SQLite
  `EventStore`: observed conditions structurally separated from modelled
  context; evidence attached per event; years never hardcoded.
- **`registry.py` + `hazards/`** — hazard plugin architecture. A hazard is
  registered only when wired to real, documented data sources:
  `wildfire.py` (wraps the proven engine), `flood.py` (GloFAS discharge +
  extreme precipitation), `drought.py` (precipitation anomaly, soil
  moisture, ET₀ balance), `heat.py`/`wind.py` (climatological percentiles +
  spell detection), `coastal.py` (marine waves + elevation screening +
  labelled sea-level projections).
- **`fire_events.py`** — historical wildfire event intelligence: real NASA
  FIRMS detections clustered into event records + ERA5 observed conditions +
  modelled FWI context + lessons extracted strictly from the event's data.
- **`exposure_econ.py`** — economic exposure from real mapped data
  (OSM/WorldCover); monetary quantification honestly `not_quantified`.
- **`solutions.py`** — Solutions Intelligence engine: site-fitted,
  curated, sourced solutions across all hazards with limitations and a
  no-guarantee disclaimer (`config/solutions_knowledge.json`).
- **`api_v2.py`** — the multi-hazard REST API (`/api/v2/…`).

## Source Modules

### `src/prediction/`
- **`fuel_moisture.py`** — Fuel Moisture Content (FMC) estimation from EO indices (NDMI, NDWI), capillary transfer modelling, and Minimum Effective FMC Increase (MEFMI) calculation.
- **`fire_spread.py`** — Rate of Spread (ROS) modelling, probability of spread, and fire arrival time estimation.
- **`fwi.py`** — Canadian Fire Weather Index System (FFMC/DMC/DC/ISI/BUI/FWI/DSR, Van Wagner 1987 equations, verified against the cffdrs reference implementation) with EFFIS danger classes.
- **`risk_model.py`** — ML-based wildfire risk assessment with ensemble methods (Random Forest, XGBoost, Neural Networks) with validation metrics (AUC, precision/recall, CSI) and uncertainty quantification.
- **`training.py`** — Trains the risk model on REAL fire history (NASA FIRMS detections + ERA5 weather via Open-Meteo). See `scripts/train_risk_model.py`.
- **`validation.py`** — Validation foundation: confusion matrix, precision/recall/F1/CSI, calibration bins, Brier score, leakage-free temporal splits and the self-describing `ValidationReport`. See `docs/VALIDATION.md` and `scripts/run_validation.py`. The model is not validated until this pipeline has run on real historical data.

### `src/gis_mapping/`
- **`indices.py`** — Spectral index computation (NDVI, NDMI, NDWI) from Sentinel-2 bands.
- **`copernicus_data.py`** — REAL Sentinel-2 Level-2A access via the Element84 Earth Search public STAC catalog (no credentials): scene search, windowed COG band reads (B03/B04/B08/B11 + SCL cloud mask), NDVI/NDMI/NDWI computation and overlay grids.
- **`landcover.py`** — ESA WorldCover 10 m land-cover lookup (public COG bucket) and fuel-model mapping.
- **`data_fusion.py`** — Cloud cover mitigation via dynamic Sentinel-1 SAR + ERA5-Land reanalysis fusion with adaptive weighting based on data quality, weather conditions, and terrain type.
- **`mapping.py`** — Critical Protection Zone (CPZ) computation around vulnerable assets.

### `src/hydration_control/`
- **`water_optimiser.py`** — Water-Use Efficiency Ratio (WUER) and water-scarce resource allocation.
- **`intervention.py`** — Adaptive water intervention planning with Human-in-the-Loop decision gate.
- **`verification.py`** — Hindcasting validation against historical burned-area observations (EFFIS).

### `src/dashboard/`
- **`real_data.py`** — Real-data fetchers: Nominatim geocoding, Open-Meteo current/daily/archive weather, OpenTopoData DEM (EU-DEM 25 m / SRTM), NASA FIRMS active fires. All cached, all source-labelled.
- **`real_analysis.py`** — The analysis engine: FWI fire danger + fuel moisture + fire spread + baseline-vs-intervention comparison, with a structured provenance record per component (observed / derived / modeled / forecast / unavailable).
- **`api.py`** — Public REST API: `GET /api/analyze`, `GET /api/risk-grid`, `GET /api/risk-snapshot`, `GET /api/history`, `GET /api/report`, `GET /api/health`, `POST /api/analysis-jobs` + `GET /api/analysis-jobs/<id>`, `POST /api/watch`, `POST /api/spread`, `POST /api/allocation`.
- **`jobs.py`** — Progressive analysis jobs: honest stage transitions (pending/running/complete/unavailable) driven by the real staged pipeline, SQLite job store, concurrent-request deduplication, and cache handoff (a finished job populates the shared analysis cache; a fresh cached analysis completes instantly with `from_cache`).
- **`cache.py`** — SQLite TTL cache bounding upstream call rates and keeping the API responsive.
- **`grid.py`** — Batched grid-level fire-danger computation for map display.
- **`snapshot.py`** — Public risk-intelligence snapshot: top-risk ranking over the configured monitored areas (`config/monitored_areas.json`), built from the same cached real analyses as `/api/analyze`; honest "unavailable" when no real snapshot can be produced. Kept warm by `scripts/build_risk_snapshot.py`.
- **`explain.py`** — "Why this score?": decomposes the composite risk score into its real contributing factors (FWI, fuel dryness, terrain, land cover, wind) with declared thresholds and the composite-indicator disclaimer.
- **`change.py`** — "What changed?": 24 h / 7 d temporal comparison of risk drivers from the real daily series, with a generated explanation of the drivers that actually changed.
- **`ecology.py`** — Environmental Solutions: site-fitted vegetation/restoration recommendations from real site conditions (climate signal, moisture regime, elevation, land cover) matched to a curated, sourced species knowledge base (`config/species_knowledge.json`). Honest "insufficient data" path; no "fireproof" claims.
- **`exposure.py`** — Exposure/vulnerability/access intelligence from real OpenStreetMap data (Overpass): mapped buildings, critical facilities, roads, water features, WUI signal — reported separately from the score.
- **`population.py`** — Population exposure intelligence from real WorldPop gridded estimates (100 m, reference-year labelled, one-time country raster download into `data/population/`): estimated population/density, population-by-hazard-class overlay (real spatial join with the risk grid), corridor polygon population for smoke — always "estimated …, reference year XXXX", never exact counts.
- **`ignition.py`** — Relative Ignition-Likelihood Indicator: declared-threshold screening indicator from real FFMC (FWI System), WorldPop density, OSM roads and fuel dryness. Explicitly NOT a probability and NOT validated (see `docs/VALIDATION.md`); hazard ≠ ignition ≠ observed fire are kept strictly separate.
- **`smoke.py`** — Smoke Intelligence: atmospheric transport guidance from real Open-Meteo hourly wind profiles (850 hPa transport level). OBSERVED mode (NASA FIRMS detections, requires key) and SCENARIO mode (hypothetical fire, clearly labelled) are never mixed; output is a widening corridor envelope with declared uncertainty — never a deterministic smoke path. Population/facility overlays via the real WorldPop grid and OSM polygon queries.
- **`learning.py`** — Prediction-vs-observation record store (SQLite): model version, prediction/observation times, outcomes, lessons — evidence only, never auto-promotion.
- **`micro.py`** — Micro-area context: measured 10 m NDMI scene variability + an honest per-layer resolution table (micro/local/regional).
- **`scenarios.py`** — Intervention scenario framework: model-supported scenarios (hydration, fuel management, combined) computed by the real models; everything else explicitly "not quantified".
- **`report.py`** — Professional PDF reports (`GET /api/report?type=simple|decision|scientific`) rendered from the same real analysis object for three audiences, with provenance, limitations and validation status.
- **`recommendations.py`** — Proactive protection: evidence-linked preventive recommendations (rules fire only on real detected conditions) plus the automation framework's action-plan generation (recommended vs automated actions; nothing external without `config/operations.json`) with a SQLite audit trail of every generated plan.
- **`history.py`** — "Lessons from the Past": recent high-risk periods reconstructed from real ERA5 + FWI, observed fires (FIRMS when configured), and what HydraShield would have recommended — strictly labelled OBSERVED / MODELLED / RECOMMENDED / UNKNOWN.
- **`monitoring.py`** — Alert watches (Phase 5): threshold checks via `scripts/check_watches.py`.

## Installation (macOS / Linux)

The project uses a `src/` layout and is installable as a proper Python package.
It is strongly recommended to use a virtual environment so that dependencies
are isolated and reproducible.

> **Important:** The `.venv/` directory must **never** be committed to Git.
> It is already excluded via `.gitignore`.

```bash
cd hydra-shield-platform

# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the package in editable mode (with development/test tooling)
pip install -e ".[dev]"

# (Optional) Install GIS / Earth Observation extras
pip install -e ".[gis]"

# (Optional) Install Jupyter notebook extras
pip install -e ".[notebook]"

# (Optional) Install advanced ML models
pip install -e ".[ml_advanced]"
```

Alternatively, install from the requirements files:

```bash
pip install -r requirements-dev.txt   # runtime + test tooling
```

## Usage

### Run the tests

```bash
cd hydra-shield-platform
source .venv/bin/activate
python -m pytest tests/ -v
```

### Explore the notebooks

```bash
cd hydra-shield-platform
source .venv/bin/activate
jupyter notebook notebooks/
```

- `01_fire_risk_analysis.ipynb` — FMC estimation, fire spread modelling, ML risk assessment with ensemble methods and uncertainty quantification, and dynamic data fusion with adaptive weights.
- `02_protection_optimisation.ipynb` — Protection zones, water allocation, and intervention planning.
- `dashboard.html` — Interactive dashboard with real-time monitoring and decision support system.
- `src/dashboard/` — Advanced dashboard module with interactive visualizations and decision support.
- `src/dashboard/standard_formats_api.py` — API endpoints for standard data formats (GeoJSON, GML, CSV) for integration with civil protection systems.

### Quick example

```python
from src.prediction.fire_spread import FireSpreadModel

model = FireSpreadModel(fuel_model="TL3")
ros = model.compute_ros(fmc=15.0, wind_speed_kmh=20.0, slope_degrees=10.0)
print(f"Baseline ROS: {ros.ros_baseline:.2f} m/min")
print(f"Reduced ROS:  {ros.ros_reduced:.2f} m/min")
print(f"Reduction:    {ros.reduction_percent:.1f}%")
```

### Advanced risk model example

The ML model must be trained on real fire history before use. Use the real
training pipeline (requires a free NASA FIRMS key):

```bash
FIRMS_MAP_KEY=... python scripts/train_risk_model.py \
    --bbox -9.5,36.0,-6.0,39.5 --fire-days 10 --out data/models
```

### REST API (real data)

```bash
# Full real-data analysis for a location (cached, provenance-annotated)
curl "http://localhost:8051/api/analyze?location=Clervaux,%20Luxembourg"
curl "http://localhost:8051/api/analyze?lat=49.9&lon=6.03"

# Fire-danger grid for map display (GeoJSON)
curl "http://localhost:8051/api/risk-grid?south=49.9&west=5.9&north=50.1&east=6.1&n=5"

# Public risk snapshot: highest-risk monitored areas (real data, cached 30 min)
curl "http://localhost:8051/api/risk-snapshot"

# Lessons from the past: real ERA5 fire-danger history + observed fires
curl "http://localhost:8051/api/history?lat=37.6&lon=-6.5&days=90"

# Population exposure: WorldPop estimate + population-by-hazard-class overlay
curl "http://localhost:8051/api/population-exposure?lat=37.6&lon=-6.5&radius_km=3"

# Relative Ignition-Likelihood Indicator (screening — NOT a probability)
curl "http://localhost:8051/api/ignition-risk?lat=37.6&lon=-6.5"

# Smoke transport: observed fires (needs FIRMS_MAP_KEY) / scenario for a
# hypothetical fire under current conditions (clearly labelled SCENARIO)
curl "http://localhost:8051/api/smoke?lat=37.6&lon=-6.5&radius_km=50&days=3"
curl "http://localhost:8051/api/smoke-scenario?lat=37.6&lon=-6.5&hours=24"

# Combined human-exposure summary (hazard/population/ignition/OSM/smoke,
# kept strictly separate)
curl "http://localhost:8051/api/exposure-summary?lat=37.6&lon=-6.5"

# Health
curl "http://localhost:8051/api/health"
```

### Multi-hazard API (`/api/v2`, real data)

```bash
# Registered hazards (a hazard appears only when wired to real data sources)
curl "http://localhost:8051/api/v2/hazards"

# Per-hazard analysis (wildfire|flood|drought|heat|wind|coastal)
curl "http://localhost:8051/api/v2/analyze?hazard=flood&lat=49.75&lon=6.64"

# Historical wildfire events for any year the datasets cover (FIRMS key-gated)
curl "http://localhost:8051/api/v2/events?hazard=wildfire&lat=37.6&lon=-6.5&year=2024"

# Economic exposure (monetary values honestly not quantified)
curl "http://localhost:8051/api/v2/economy?lat=49.6&lon=6.1"

# Site-fitted sustainable solutions
curl "http://localhost:8051/api/v2/solutions?lat=49.6&lon=6.1"

# Accounts: register / verify / login, saved locations, history, alerts
curl -X POST "http://localhost:8051/api/v2/auth/register" \
     -H "Content-Type: application/json" \
     -d '{"email":"you@example.org","password":"a-long-password"}'
```

### Developer interfaces

HydraShield is API-first: the same real-data engine serves every interface
(see `docs/API_FIRST_STRATEGY.md`). The stable public contract is documented
in **`docs/API_V2.md`** (additive-only `/api/v2`; breaking changes ship as v3).

- **REST API** — public GETs (hazards, analyze, events, economy, solutions,
  sources, risk grid/snapshot, PDF reports) plus authenticated
  account/alert endpoints. Errors are stable JSON: `{"error", "status"}`.
- **Python SDK** — `sdk/python/hydrashield/` (stdlib-only, no dependencies):
  `HydraShieldClient(base_url, api_key, timeout)` covering all public GETs.
- **JavaScript SDK** — `sdk/js/hydrashield.js` (fetch-based, zero deps,
  UMD-lite) with the same method set and error semantics.
- **`<hydrashield-risk>` web component** — embeddable shadow-DOM risk card
  (attribution + provenance chips, honest loading/error/unavailable
  states); demo page: `website/embed.html`.
- **Webhooks** — outbound-only, HMAC-SHA256 signed
  (`X-HydraShield-Signature`), at-least-once with recorded delivery status
  (contract in `docs/API_V2.md` §6; delivery engine in progress).

### Model validation (scientific layer)

```bash
# Requires FIRMS_MAP_KEY (free): https://firms.modaps.eosdis.nasa.gov/api/area/
FIRMS_MAP_KEY=... python scripts/run_validation.py \
    --bbox -10,36,3,44 --start 2026-07-01 --end 2026-08-10 --threshold 65
# Writes data/validation/validation_report_<start>_<end>.json — see docs/VALIDATION.md

# Separate evaluation of the ignition-likelihood indicator (same discipline,
# plus ROC-AUC / PR-AUC with prevalence baseline):
FIRMS_MAP_KEY=... python scripts/evaluate_ignition.py \
    --bbox -10,36,3,44 --start 2026-07-01 --end 2026-08-10
# Writes data/validation/ignition_evaluation_<start>_<end>.json
```

### Environment variables

See `.env.example`. All optional; missing configuration is reported as an
unavailable layer, never replaced with invented data.

- `FIRMS_MAP_KEY` — free NASA FIRMS key, enables the real active-fire layer,
  the historical fire-events endpoint and observed-fire smoke transport.
- `SMTP_HOST/PORT/USER/PASSWORD/FROM` — enable email delivery (accounts,
  alerts, reports). `SMTP_FROM=info@hydrashield.earth`. Without SMTP config,
  emails go to the safe dev outbox (`data/outbox/`) and are never sent.
  Legacy `SMTP_PASS` is still honoured.
- `HYDRASHIELD_SECRET_KEY` — HMAC key for session/verification tokens
  (set in production; a documented machine-stable fallback is used in dev).
- `HYDRASHIELD_CACHE_DB` — SQLite cache/watch/accounts database path.
- `HYDRASHIELD_POPULATION_DIR` — where the one-time WorldPop country rasters are cached (default `data/population/`).

### Dynamic data fusion example

```python
from src.gis_mapping.data_fusion import DataFusionPipeline
import numpy as np

# Sample soil moisture data from different sources
sar_moisture = np.array([0.2, 0.3, 0.4])
reanalysis_moisture = np.array([0.25, 0.35, 0.45])

# Initialize the enhanced data fusion pipeline
fusion_pipeline = DataFusionPipeline(sar_weight=0.5, reanalysis_weight=0.5)

# Define weather conditions and terrain type
weather_conditions = {
    'precipitation': 2.5,  # mm/hour
    'humidity': 0.65       # fraction
}
terrain_type = 'forest'

# Perform fusion with adaptive weights based on data quality, weather, and terrain
fused_result = fusion_pipeline.fuse_soil_moisture(
    sar_moisture, 
    reanalysis_moisture,
    sar_data_quality=0.8,
    reanalysis_data_quality=0.7,
    weather_conditions=weather_conditions,
    terrain_type=terrain_type
)

print('Fused moisture (adaptive weights):', fused_result)
```

## Key Scientific Equations

- **Water-Use Efficiency Ratio:** `WUER = (Risk_baseline - Risk_HydraShield) / Volume of water applied`
- **Minimum Effective FMC Increase:** `MEFMI = FMC_target - FMC_baseline`
- **Reduced Rate of Spread:** `ROS_reduced = ROS_baseline × R_FMC(MEFMI, fuel type, weather, slope)`
- **Evacuation Safety Margin:** `ESM = t_evacuation_window - t_fire_arrival - t_operational_margin - t_uncertainty`

## Advanced Features

### Ensemble Modeling
The AdvancedWildfireRiskModel combines multiple ML algorithms (Random Forest, XGBoost, Neural Networks) to improve prediction accuracy and provide uncertainty estimates.

### Uncertainty Quantification
Models now provide uncertainty estimates alongside predictions, allowing for more informed decision-making in critical scenarios.

### Enhanced Feature Importances
Aggregated feature importance across multiple models in the ensemble for better interpretability.

### Dynamic Data Fusion
The DataFusionPipeline now incorporates adaptive weighting based on:
- Data quality metrics for each source
- Current weather conditions (affecting sensor reliability)
- Terrain type (affecting sensor performance)
- Real-time adjustment of SAR vs. reanalysis weights

### Interactive Dashboard
The system includes an advanced dashboard with:
- Real-time monitoring and visualization
- Interactive scenario modeling
- Explainable AI recommendations
- Water resource optimization
- Decision support system with risk assessment

### Continuous Verification System
The system includes a continuous verification system with:
- Performance tracking based on live data
- Adaptive strategy generation
- Feedback loops for model improvement
- Retraining suggestions when accuracy drops below threshold
- Error reduction analysis and improvement recommendations

### Enhanced Fire Spread Modeling
The FireSpreadModel now includes:
- 3D wind effects (horizontal and vertical components)
- Horizontal and vertical fire spread components
- Wind-direction and terrain-aspect alignment factors
- Vertical spread potential calculations (ground to canopy)
- Crown fire spread modeling

## License

© 2026 HydraShield Earth Systems. All rights reserved.
Built on Copernicus Data · Aligned with EU Climate Goals
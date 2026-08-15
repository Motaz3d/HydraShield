# HydraShield Platform

An integrated 3-layer system combining DeepTech, AI/satellite data, and environmental protection to prevent wildfires via subsurface hydration barriers.

HydraShield is an AI-driven Digital Twin that transforms Copernicus satellite data into actionable, water-optimized protection blueprints for communities at risk of catastrophic wildfires.

## Project Structure

```
hydra-shield-platform/
├── docs/          # Proposal and Pitch documents
├── data/          # Raw and processed fire data and Copernicus maps
├── src/           # Main source code
│   ├── prediction/        # Fire risk & spread prediction (ML + physics)
│   ├── gis_mapping/       # Earth Observation ingestion & GIS processing
│   └── hydration_control/ # Protection optimisation & water planning
├── notebooks/     # Jupyter notebooks for data analysis
│   ├── 01_fire_risk_analysis.ipynb — FMC estimation, fire spread modelling, ML risk assessment with ensemble methods and uncertainty quantification, and dynamic data fusion with adaptive weights.
│   ├── 02_protection_optimisation.ipynb — Protection zones, water allocation, and intervention planning.
│   └── dashboard.html — Interactive dashboard with real-time monitoring and decision support system.
├── tests/         # Testing files
└── website/       # Public marketing website
```

## Source Modules

### `src/prediction/`
- **`fuel_moisture.py`** — Fuel Moisture Content (FMC) estimation from EO indices (NDMI, NDWI), capillary transfer modelling, and Minimum Effective FMC Increase (MEFMI) calculation.
- **`fire_spread.py`** — Rate of Spread (ROS) modelling, probability of spread, and fire arrival time estimation.
- **`fwi.py`** — Canadian Fire Weather Index System (FFMC/DMC/DC/ISI/BUI/FWI/DSR, Van Wagner 1987 equations, verified against the cffdrs reference implementation) with EFFIS danger classes.
- **`risk_model.py`** — ML-based wildfire risk assessment with ensemble methods (Random Forest, XGBoost, Neural Networks) with validation metrics (AUC, precision/recall, CSI) and uncertainty quantification.
- **`training.py`** — Trains the risk model on REAL fire history (NASA FIRMS detections + ERA5 weather via Open-Meteo). See `scripts/train_risk_model.py`.

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
- **`api.py`** — Public REST API: `GET /api/analyze`, `GET /api/risk-grid`, `GET /api/health`, `POST /api/watch`, `POST /api/spread`, `POST /api/allocation`.
- **`cache.py`** — SQLite TTL cache bounding upstream call rates and keeping the API responsive.
- **`grid.py`** — Batched grid-level fire-danger computation for map display.
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

# Health
curl "http://localhost:8051/api/health"
```

### Environment variables

See `.env.example`. All optional; missing configuration is reported as an
unavailable layer, never replaced with invented data.

- `FIRMS_MAP_KEY` — free NASA FIRMS key, enables the real active-fire layer.
- `SMTP_HOST/PORT/USER/PASS/FROM` — enable email delivery for watch alerts.
- `HYDRASHIELD_CACHE_DB` — SQLite cache/watch database path.

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
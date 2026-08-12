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
├── tests/         # Testing files
└── website/       # Public marketing website
```

## Source Modules

### `src/prediction/`
- **`fuel_moisture.py`** — Fuel Moisture Content (FMC) estimation from EO indices (NDMI, NDWI), capillary transfer modelling, and Minimum Effective FMC Increase (MEFMI) calculation.
- **`fire_spread.py`** — Rate of Spread (ROS) modelling, probability of spread, and fire arrival time estimation.
- **`risk_model.py`** — ML-based wildfire risk assessment (Random Forest) with validation metrics (AUC, precision/recall, CSI).

### `src/gis_mapping/`
- **`indices.py`** — Spectral index computation (NDVI, NDMI, NDWI) from Sentinel-2 bands.
- **`data_fusion.py`** — Cloud cover mitigation via Sentinel-1 SAR + ERA5-Land reanalysis fusion.
- **`mapping.py`** — Critical Protection Zone (CPZ) computation around vulnerable assets.

### `src/hydration_control/`
- **`water_optimiser.py`** — Water-Use Efficiency Ratio (WUER) and water-scarce resource allocation.
- **`intervention.py`** — Adaptive water intervention planning with Human-in-the-Loop decision gate.
- **`verification.py`** — Hindcasting validation against historical burned-area observations (EFFIS).

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

- `01_fire_risk_analysis.ipynb` — FMC estimation, fire spread modelling, and ML risk assessment.
- `02_protection_optimisation.ipynb` — Protection zones, water allocation, and intervention planning.

### Quick example

```python
from src.prediction.fire_spread import FireSpreadModel

model = FireSpreadModel(fuel_model="TL3")
ros = model.compute_ros(fmc=15.0, wind_speed_kmh=20.0, slope_degrees=10.0)
print(f"Baseline ROS: {ros.ros_baseline:.2f} m/min")
print(f"Reduced ROS:  {ros.ros_reduced:.2f} m/min")
print(f"Reduction:    {ros.reduction_percent:.1f}%")
```

## Key Scientific Equations

- **Water-Use Efficiency Ratio:** `WUER = (Risk_baseline - Risk_HydraShield) / Volume of water applied`
- **Minimum Effective FMC Increase:** `MEFMI = FMC_target - FMC_baseline`
- **Reduced Rate of Spread:** `ROS_reduced = ROS_baseline × R_FMC(MEFMI, fuel type, weather, slope)`
- **Evacuation Safety Margin:** `ESM = t_evacuation_window - t_fire_arrival - t_operational_margin - t_uncertainty`

## License

© 2026 HydraShield Earth Systems. All rights reserved.
Built on Copernicus Data · Aligned with EU Climate Goals

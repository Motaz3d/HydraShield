# HydraShield / Talaix — Project Map

Read this file FIRST. It exists to save exploration time: do not re-scan the tree for information already stated here. Keep it updated when structure or commands change.

## Session protocol (automatic — do every session)
1. **At session start**: read `PLAN.md` to know current work status before doing anything; do not re-investigate what it already records.
2. **During work**: prefer the paths in this map over searching; search only when the map lacks what you need.
3. **Before finishing any task that changed structure, commands, or progress**: update this `AGENTS.md` (map changes) and `PLAN.md` (status changes) in the same session, without waiting to be asked. Keep both files short — they are loaded every session and cost tokens.

## What this is
Talaix (formerly HydraShield): climate-extreme intelligence & economic decision-support platform. Aggregates earth-observation data to analyse multi-hazard risks (wildfire, flood, drought, heat, wind, coastal, cyclone, earthquake) and produce evidence-linked reports for finance, insurance, government, and investment users.

## Top-level layout
- `hydra-shield-platform/` — the main codebase (everything below). Work happens here.
- `docs/` — regional opportunity briefs + `DEVELOPMENT_OPERATIONS.md`.
- `pic/` — logos and screenshots.
- `PLAN.md` — living operator/AI-copilot work plan with status tracker.
- `DEEPSEEK.md` — AI model-routing config notes.
- `TXEng.md`, `txac.txt` — Arabic-language strategic docs (TX Engine, Talaix Academy).

## Inside hydra-shield-platform/
- `src/` — main Python package (importable as `src`):
  - `src/climate/` — multi-hazard core
  - `src/dashboard/` — Flask API (`api.py`, port 8051), cache, jobs, reports, accounts; runner: `run_dashboard.py`
  - `src/gis_mapping/` — earth-observation ingestion
  - `src/prediction/` — FWI, spread, risk ML
  - `src/hydration_control/`, `src/security/`, `src/ai/`
- `tx_core/` — TX Engine: `cli.py` (console script `tx`), `engine.py`, models, adapters, jobs.
- `config/` — JSON registries: CSRD rules, species/solutions knowledge, stripe prices.
- `db/` — SQLite schema: `db/migrations/0001_init.sql`. Runtime cache/accounts DB path via env `HYDRASHIELD_CACHE_DB`.
- `tests/` — pytest suite (~100 files).
- `scripts/` — operational scripts (training, validation, snapshots, outreach, billing).
- `sdk/python/`, `sdk/js/` — client SDKs.
- `qgis-plugin/hydrashield/` — QGIS plugin.
- `website/` — static site (HTML/CSS/JS).
- `notebooks/` — Jupyter: fire-risk, protection optimisation.
- `docs/` — product, architecture, API, validation, strategy docs.
- `marketing/` — campaigns, segments, EU funding, leads.
- `data/` — cache, validation sets, rasters, IBTrACS, dev outbox.

## Commands (run from hydra-shield-platform/)
- Install: `pip install -e ".[dev]"` (or `pip install -r requirements-dev.txt`)
- Tests: `python -m pytest tests/ -v`
- CLI: `tx analyze --lat <lat> --lon <lon>`
- API: Flask on `localhost:8051` (see `src/dashboard/api.py`)

## Key facts
- Python >= 3.10 (3.10–3.12). Package `hydrashield-platform` (pyproject.toml); imports: `src`, `tx_core`.
- Core deps: numpy, pandas, scikit-learn, xgboost, flask, dash, plotly, rasterio, geopandas, shapely, pystac-client, reportlab, stripe, requests.
- Virtualenvs exist at `.venv/` (root) and `hydra-shield-platform/.venv/`.

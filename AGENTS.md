# HydraShield / Talaix — Project Map

Read this file FIRST. It exists to save exploration time: do not re-scan the tree for information already stated here. Keep it updated when structure or commands change.

## Session protocol (automatic — do every session)
1. **At session start**: read `PLAN.md` to know current work status before doing anything; do not re-investigate what it already records.
2. **During work**: prefer the paths in this map over searching; search only when the map lacks what you need.
3. **Before finishing any task that changed structure, commands, or progress**: update this `AGENTS.md` (map changes) and `PLAN.md` (status changes) in the same session, without waiting to be asked. Keep both files short — they are loaded every session and cost tokens.

## Operator paste-ready text rule (binding, operator directive 2026-09-09)
- When giving the operator text to paste into webforms/emails, output it as **plain continuous text**: no blockquote bars (`>`, `│`), no table cells, no code fences, no mid-sentence line wraps. Each snippet must be copyable in one action, exactly as it will be pasted.
- Canonical approved snippets live in `hydra-shield-platform/marketing/outreach/paste_kit.txt` — quote from it instead of re-drafting, and update it when approved wording changes.
- Founder LinkedIn: https://www.linkedin.com/in/motaz-omarien-8394359/ · Company page: https://www.linkedin.com/company/talaix/ (always share without `?viewAsMember=true`).

## What this is
Talaix (formerly HydraShield): climate-extreme intelligence & economic decision-support platform. Aggregates earth-observation data to analyse multi-hazard risks (wildfire, flood, drought, heat, wind, coastal, cyclone, earthquake) and produce evidence-linked reports for finance, insurance, government, and investment users. **Market-facing identity since 2026-09-06: climate-risk compliance evidence for EU disclosure (CSRD/ESRS E1, EU Taxonomy DNSH, EUDR)** — engine unchanged underneath; decisions + competitor study in `hydra-shield-platform/docs/COMPLIANCE_STRATEGY.md`, phase tracker in `docs/GRC_COMPLIANCE.md`.

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
- `scripts/` — operational scripts (training, validation, snapshots, outreach, billing, `sync_tore.sh`, investor-deck builder `build_deeptechxl_deck.py` → default generic `marketing/outreach/talaix_preseed_deck.pdf`, `--fund deeptechxl` → `deeptechxl_pitch_deck.pdf`, `--fund lsa` → `marketing/outreach/lsa_pitch_deck.pdf`, `md_to_pdf.py` — generic Markdown→A4 PDF renderer for proposals/prep docs). Outreach: `scripts/backfill_daily.py` (dry-run default, `--schedule`) tops up `scheduled_outreach` to the daily cap; called from `scripts/email_cron.sh` after `process_scheduled_outreach.py`.

## Open-source engine mirror — tore (binding)
- Public repo: `../tore` (outside this project root, at `~/Documents/work/tore`) → https://github.com/Motaz3d/tore — "Talaix Open Risk Engine", EUPL-1.2, created 2026-09-06 for the NLnet Restack application.
- **Rule: every change to the analytical engine must be mirrored to tore.** Engine = `tx_core/`, `src/climate/` (minus `api_*.py` web blueprints), `src/prediction/`, `src/gis_mapping/`, the analytical data-pipeline modules of `src/dashboard/` (cache, change, crime_stats, ecology, explain, exposure, fire_evidence, grid, history, ignition, micro, population, real_analysis, real_data, recommendations, scenarios, site_image, smoke, snapshot, verification_store), `src/hydration_control/`, 4 knowledge registries (`config/loss_registry.json`, `model_registry.json`, `loss_estimate_benchmarks.json`, `cascading_graph.json`), `docs/TX_ENGINE.md`.
- How: `hydra-shield-platform/scripts/sync_tore.sh --push -m "<message>"` (run from anywhere; `TORE_REPO` env overrides the checkout path). The web layer (Flask app, accounts, billing, marketing, `src/climate/api_*.py`) never goes to tore.
- Engine changes are not done until the mirror is synced. tore's own files (README, pyproject, CI, examples, `tests/fakes.py`, `tests/test_engine_smoke.py`, its `AGENTS.md`) are edited in the tore checkout directly.
- `sdk/python/`, `sdk/js/` — client SDKs.
- `qgis-plugin/hydrashield/` — QGIS plugin.
- `website/` — static site (HTML/CSS/JS).
- `notebooks/` — Jupyter: fire-risk, protection optimisation.
- `docs/` — product, architecture, API, validation, strategy docs.
- `marketing/` — campaigns, segments, EU funding, leads, `research/` (incl. global investor landscape `.md` + interactive `.html`).
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

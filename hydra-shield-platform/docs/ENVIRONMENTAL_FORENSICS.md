# Environmental Security & Forensic Verification

Talaix Environmental Forensic Evidence Packs cross-match a structured claim
about a site against observed physical evidence (satellite, land cover,
Hansen/UMD GFC forest-loss time series, active fires) and document
consistency / inconsistency / cannot_assess for qualified investigators.

## Audience

- Regulators and enforcement agencies
- Financial Intelligence Units (FIUs) building AML environmental-crime files
- NGOs and investigative journalists
- Legal / compliance teams needing a physical-evidence annex

## Honesty contract

The engine **never** outputs:

- a determination of legality or illegality,
- a finding of criminal conduct or guilt,
- a forensic-lab certification,
- exoneration,
- financial analysis or transaction data.

The three possible consistency results are:

| Result | Meaning |
|--------|---------|
| `consistent` | The observed evidence supports the declared claim within the declared limitations. |
| `inconsistent` | The observed evidence contradicts the declared claim within the declared limitations. |
| `cannot_assess` | The required dataset is missing or ambiguous. |

The overall `case_verdict` is one of:

- `inconsistencies_found`
- `partially_assessable`
- `no_inconsistency_detected_with_current_evidence`

## Typologies

| ID | Label | Relevant evidence | Declared gaps |
|----|-------|-------------------|---------------|
| `illegal_logging` | Suspected unauthorised timber extraction | Land cover, GFC forest-loss time series, active fires, NDVI | Concession boundaries, chain-of-custody docs |
| `illegal_mining` | Suspected unauthorised extraction / land disturbance | Land cover snapshot, NDVI/NDWI | Dedicated mining/disturbance detection, concession boundaries, ground inspection |
| `unlicensed_clearing` | Land clearing without a permit | Land cover, GFC forest-loss time series, active fires, NDVI | Permit / land-title register |
| `waste_dumping` | Illegal waste disposal | Land cover, spectral indices | Dedicated waste/dump detection, ground inspection, regulatory records |
| `other` | Other environmental-crime suspicion | Depends on claim | Missing layers declared explicitly |

## Subject claim types & consistency rules

- `site_forested` — "The site is forested / intact"
  - Land-cover dominant label contains "tree" (case-insensitive) → **consistent**
  - Land-cover dominant class is present and not tree cover → **inconsistent**
  - Land-cover data unavailable → **cannot_assess**
  - Caveat: single-year ESA WorldCover snapshot, not a forest-loss time series.

- `no_recent_clearing` — "No recent tree-cover clearing (e.g., post-2020)"
  - GFC available, `loss_after_2020` is false → **consistent**
  - GFC available, `loss_after_2020` is true → **inconsistent**
  - GFC unavailable / fetch error → **cannot_assess**
  - Caveats: 30 m resolution misses small clearings; GFC 2023 v1.11 covers
    through 2023, so 2024+ loss is not included.

- `no_burning` — "No open burning occurs at the site"
  - FIRMS available, 0 detections within `radius_km` / `days` → **consistent**
  - FIRMS available, >0 detections → **inconsistent**
  - FIRMS unavailable / key missing / fetch error → **cannot_assess**
  - Caveat: hotspot points, not fire perimeters; small/low-temp fires may be missed.

- `vegetation_present` — "Vegetation / restoration is present and active"
  - Sentinel-2 NDVI ≥ 0.3 → **consistent**
  - Sentinel-2 NDVI < 0.2 → **inconsistent**
  - Sentinel-2 NDVI 0.2–0.3 or unavailable → **cannot_assess**
  - Caveat: scene-specific, affected by cloud, soil and season.

- `free_text` — Any other claim
  - Always **cannot_assess**; the evidence bundle is provided for investigator assessment.

## Datasets used

- `src.gis_mapping.landcover.fetch_landcover` — ESA WorldCover 10 m 2021 v200.
- `src.gis_mapping.forest_loss.fetch_forest_loss` — Hansen/UMD GFC 2023 v1.11, 30 m, 2001–2023 loss years.
- `src.dashboard.real_data.fetch_satellite_data` — Sentinel-2 L2A NDVI/NDMI/NDWI.
- `src.dashboard.real_data.fetch_active_fires` — NASA FIRMS VIIRS/MODIS active-fire detections (requires `FIRMS_MAP_KEY`; honestly unavailable when missing).
- `src.climate.evidence.EvidenceRecord` — typed, content-hashed evidence items.

## Declared gaps

Every pack includes:

- **GFC vintage limitation** — Hansen/UMD GFC 2023 v1.11 covers through 2023
  only; 2024+ loss is not included.
- **Financial data boundary** — Talaix holds no transaction data.
- Typology-specific gaps (mining/waste detection, permit registers, etc.).
- Data-unavailability gaps for any failed fetcher (land cover, GFC, Sentinel-2, FIRMS).

## Chain of custody

Each evidence record is a typed `EvidenceRecord` with `evidence_id` and
`content_hash`. The pack exposes a `chain_of_custody` block listing:

- `case_id`
- `generated_at`
- `engine_version`
- `evidence_records` with `evidence_id`, `source`, `dataset`, `acquired_at`, `content_hash`

The hash is derived from the record content (excluding `acquired_at`) so the
same source observation yields the same identifier.

## Frameworks

- **FATF "Money Laundering from Environmental Crime" (2021)** — physical-evidence
  annex for AML/FIU case files; Talaix holds no financial data.
- **EU Environmental Crime Directive (EU) 2024/1203** — legal context; Talaix
  does not determine criminal conduct.
- **INTERPOL / UNEP environmental-crime enforcement** — operational support,
  not a substitute for warrants or expert analysis.

## API

- `GET /api/v2/forensics/frameworks` — public, 60 req/min.
- `POST /api/v2/forensics/cases` — registered+, 6 req/min.
- `POST /api/v2/forensics/cases/pdf` — registered+, 6 req/min.
- `GET /api/v2/forensics/cases/<case_id>` — owner or admin only.

## Relation to Supply Chain

Both products share the same integrated remote-sensing datasets (ESA
WorldCover, Sentinel-2, and Hansen/UMD GFC through 2023). Forensics adds
active-fire detections and structured claim–evidence consistency checks for
investigative use.

## Roadmap

- Integrate near-real-time disturbance alerting (e.g., RADD) for 2024+ loss.
- Add export formats for case-file systems (JSON-LD, STIX-like packages).
- Support multi-site cases and temporal claim windows.

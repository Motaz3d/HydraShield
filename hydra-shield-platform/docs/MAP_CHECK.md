# Talaix — Map Check

> **Website UI retired (2026-09):** the `map.html?mode=check` mode and
> `website/js/mapcheck.js` were removed from the site as it narrowed its
> identity to insurance and finance. The engine described here remains fully
> available through the API (`/api/v2/mapcheck/`) and the MCP tool
> (`talaix_mapcheck`); `mapcheck.html` redirects to `map.html`.

Map Check is a cartographic cross-verification model: for any point it compares
what open map sources **say** (OpenStreetMap green features) with what
satellite observation **shows** (Sentinel-2 NDVI + ESA WorldCover land-cover
class), and reports discrepancies together with rule-based possible causes.

## Purpose

Users — real-estate developers, investors, auditors and operators — often need
to know whether a map can be trusted for a specific claim ("this area is green
space", "the asset is next to a park"). Map Check does not answer that
question directly; it surfaces **signals to verify** by showing when two
independent open sources disagree and why that disagreement might exist.

## The two checks

### 1. `green_mapped_vs_satellite`

When OpenStreetMap records a green feature (`leisure`, `landuse` or `natural`
tags such as park / forest / grassland / wood) within the radius:

- **consistent** — satellite agrees: NDVI ≥ 0.35 and/or the dominant WorldCover
  class is Tree cover (10), Shrubland (20), Grassland (30), Wetland (90) or
  Mangrove (95).
- **discrepancy_detected** — satellite does not agree: NDVI < 0.35 and the
  dominant WorldCover class is not one of the green classes.
- **cannot_assess** — satellite observation is unavailable (clouds, no recent
  scene, WorldCover read failure).

### 2. `satellite_green_vs_map`

When satellite observation indicates green vegetation (NDVI ≥ 0.35 or a green
WorldCover class) but OpenStreetMap records **no** green feature within the
radius:

- **consistent** — no disagreement: either satellite also does not indicate
  green, or OSM already records a green feature.
- **discrepancy_detected** — satellite says green, the map does not.
- **cannot_assess** — satellite input is missing.

## Thresholds and inputs

| Input | Source | Threshold / rule |
|-------|--------|------------------|
| Green features | OpenStreetMap via Overpass API | `leisure` ∈ {park, garden, nature_reserve}; `landuse` ∈ {forest, grass, meadow, recreation_ground, village_green}; `natural` ∈ {wood, scrub, grassland} |
| Green by NDVI | Sentinel-2 L2A (Earth Search STAC) | NDVI ≥ 0.35 on the latest cloud-free scene within 30 days |
| Green by land cover | ESA WorldCover 10 m 2021 v200 | Dominant class ∈ {10 Tree cover, 20 Shrubland, 30 Grassland, 90 Wetland, 95 Mangrove} |
| Default radius | — | 300 m (range: 50–2000 m) |
| Outdated-edit heuristic | OSM element `timestamp` | Edit older than 5 years triggers a possible-cause note |

## Verdict vocabulary (hard rule)

Only three verdicts are ever emitted:

- `consistent`
- `discrepancy_detected`
- `cannot_assess`

Map Check **never** claims "map error" or "the map is wrong". A discrepancy is
a signal to verify, not proof of an error in any single source.

## Rule-based possible causes

### When mapped green is not seen by satellite

- OSM feature data may be outdated (last edit `<year>`) if the oldest mapped
  element is more than 5 years old.
- Satellite revisit / cloud cover / seasonal vegetation low.
- 10–30 m resolution thresholds may miss small mapped features.
- Real land-use change since the OSM edit.

### When satellite green is not mapped

- OSM completeness gap — feature may simply be unmapped (very common).
- Private or informal green space not recorded in OSM.
- Recent planting or regeneration after the OSM edit.
- Resolution / scale mismatch between 10 m pixels and OSM geometry.

## Open-source / terms-of-service boundary

Map Check compares only open sources:

- OpenStreetMap (Overpass API)
- ESA WorldCover 10 m 2021 v200
- Sentinel-2 L2A via Earth Search STAC

Proprietary maps (Google, Apple, Bing, etc.) are **not fetched or compared**
because their terms do not allow automated extraction. Users may compare those
sources manually and should do so for high-stakes decisions.

## API reference

`GET /api/v2/mapcheck/?lat=<lat>&lon=<lon>&radius_m=300`

Public, rate-limited to 10 requests/minute per client IP.

Parameters:

- `lat`, `lon` — required, numeric, WGS-84.
- `radius_m` — optional, integer 50–2000, default 300.

Response (JSON):

```json
{
  "check_id": "a1b2c3d4...",
  "location": {"lat": 46.0542, "lon": 14.4707, "radius_m": 300},
  "generated_at": "2026-08-26T12:00:00Z",
  "status": "ok",
  "checks": [
    {
      "id": "green_mapped_vs_satellite",
      "result": "discrepancy_detected",
      "basis": "OpenStreetMap records green features, but satellite observation does not: ...",
      "map_claim": {"green_mapped": true, "feature_summaries": [...], ...},
      "satellite_observation": {"ndvi": 0.12, "green_by_ndvi": false, ...},
      "possible_causes": ["OSM feature data may be outdated (last edit 2013)", ...],
      "evidence": [{"evidence_class": "OPEN_DATA_OFFICIAL", ...}, {"evidence_class": "SATELLITE_EO", ...}]
    },
    {
      "id": "satellite_green_vs_map",
      "result": "consistent",
      ...
    }
  ],
  "discrepancies_count": 1,
  "recommendations": [...],
  "declared_gaps": [],
  "disclaimer": "...",
  "honesty_contract": "..."
}
```

Errors:

- `400` — missing or invalid `lat`/`lon`, or `radius_m` out of range.
- `429` — rate limit exceeded.
- `502` — engine failure after input validation.

## Frontend

Map Check lives inside `website/map.html` as a mode (`map.html?mode=check`),
merged from the legacy standalone `mapcheck.html`; `website/js/mapcheck.js`
provides:

- Location input (place name or `lat,lon`) with the shared location component.
- Radius selector (50–2000 m, default 300).
- Pre-loaded one-click examples (Clervaux, Serra da Estrela, Attica) so a
  first-time visitor sees a real check before typing anything.
- Per-check two-column card: "Map says" vs "Satellite shows".
- Verdict chip (`consistent` green, `discrepancy_detected` amber,
  `cannot_assess` grey).
- Basis line, possible-causes list, expandable evidence table.
- Recommendations panel + "Why discrepancies happen" explainer + audience
  note card linking to Green Finance and Insurance products.
- Post-result "Need this documented?" panel linking the checked coordinates
  into the Insurance profile, Green Finance check and contact page.

Navigation:

- `website/js/chrome.js` — Map Check is the first item under **Explore**.
- `website/js/map.js` — the map "Act on this point" panel links to
  `map.html?mode=check&location=lat,lon`.

## Engine location

- `src/climate/mapcheck.py` — engine, no Flask imports.
- `src/climate/api_mapcheck.py` — Flask blueprint `/api/v2/mapcheck`.

## Tests

`tests/test_mapcheck.py` covers:

- Mapped green + low NDVI + built-up land cover → `discrepancy_detected` with
  outdated-edit cause.
- Mapped green + high NDVI → `consistent`.
- No mapped green + high NDVI + tree-cover class → `discrepancy_detected` with
  OSM-completeness cause.
- No mapped green + low NDVI + built-up class → `consistent`.
- Satellite unavailable → `cannot_assess` + declared gap.
- Overpass failure → degraded/cannot-assess response.
- Vocabulary: no "map error" / absolute "wrong" wording; disclaimer mentions
  open sources only and proprietary maps not fetched; possible causes are
  non-empty on every discrepancy.
- Endpoint validation and happy-path structure.
- Optional live smoke against Ljubljana (Tivoli park) reported honestly.

## Roadmap (out of scope for this phase)

- Feature-level area comparison (polygons vs pixel fractions, not just point
  radius).
- More open map layers — national open topographic services on a per-country
  basis.
- Historical NDVI change vs element edit history.
- User-reported discrepancy feedback loop into the OpenStreetMap community.

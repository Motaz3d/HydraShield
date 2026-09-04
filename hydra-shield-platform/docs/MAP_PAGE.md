# Talaix — the Map page (`website/map.html`)

The map is the core product surface: open-source hazard, environment, evidence
and exposure layers around a place, with every layer declaring its source,
resolution, temporal class and provenance. It is a **screening tool** — evidence
to verify, never a probability of loss — and it shares the platform honesty
contract: open sources only, no invented data, honest loading / empty /
unavailable / key_required / error states everywhere.

## Page layout (compact, progressive disclosure)

The page deliberately does **not** show everything at once:

1. **Page head** — title and a one-paragraph lead (screening disclaimer).
   The map is Explore-only: the Map Check mode was retired from the website
   (the engine remains available via API/MCP — see `docs/MAP_CHECK.md`).
2. **Map shell** — a reduced-height Leaflet canvas
   (`clamp(400px, 58vh, 640px)`, never full-viewport) beside a fixed-width
   simplified control sidebar (350 px). Below roughly 900 px the two stack.
3. **Advanced strip** — a collapsed bar under the shell that expands into the
   deeper tools. The toggle bar doubles as the live evidence readout
   ("Active evidence: N observed · M modelled — screening only").

### Simplified sidebar (left, always visible)

Location search → Hazard selector → Year selector → Evidence filter
(observed-only / modelled-only) → Layers panel. The "Act on this point" panel
(injected by `js/map.js`) deep-links the map centre into Green
Finance, Insurance, Forensics, Press and Sustainability products.

### Layers panel

- Layers come from `GET /api/v2/hazards/<id>` (`map_layers`) plus platform-wide
  layers appended client-side (OSM exposure features, WorldPop population,
  trade ports; wildfire adds FIRMS active fires and smoke corridors).
- Groups (HAZARD / ENVIRONMENT / EVIDENCE / EXPOSURE / PROJECTION) are
  **collapsible**; a group starts open when it contains a `default_on` layer or
  is first.
- Every row shows a **temporal-class chip** (OBSERVED / MODELLED / SCENARIO …)
  at a glance, plus an `info` expander with legend swatches, source link,
  resolution, status chips and provenance note.
- The on-map legend (bottom-right) is rebuilt from **every active loaded layer
  that declares a legend** — one block per layer.

### Advanced strip sections

- **Multi-hazard snapshot** — screens the map centre against every available
  hazard via `GET /api/v2/analyze?hazard=<id>&lat&lon` (point screening, not a
  spatial grid); each row links "Layers →" to load that hazard's layers.
- **Compare with another location** — the selected hazard at the map centre vs
  a second resolved site, side by side.
- **Share & export** — copy a view link (restores `location`, `hazard`, `year`,
  `mode`), copy centre coordinates, or export the active layers as GeoJSON
  (each feature keeps `talaix_layer` / `talaix_temporal` / `talaix_source`).
- **Key terms in plain language** — FWI, NDMI/NDVI, FIRMS, ESA WorldCover and
  observed-vs-modelled explained for non-GIS readers.

## Reliability behaviour

- `GET /api/v2/hazards` (the registry every layer depends on) is retried
  automatically twice with backoff, then shows a manual **Retry** button —
  the page never dies silently on "Hazard registry unavailable".
- The per-hazard layer-definition fetch shows an honest error notice with a
  **Retry** button.
- Cheap viewport-bound layers refresh (debounced) after the map moves;
  `map.invalidateSize()` keeps Leaflet in sync on window resizes.

## URL contract

`map.html?location=<place|lat,lon>&hazard=<id>&year=<yyyy>`

- `location` — geocoded and centred on load.
- `hazard` — preselects the hazard (falls back to `wildfire` when unavailable).
- `year` — applied once the hazard's year options exist (years always derive
  from the hazard's declared `temporal_coverage`, never hardcoded).

## Endpoints used

`GET /api/v2/hazards` · `GET /api/v2/hazards/<id>` ·
`GET /api/risk-grid` (fire-danger grid) · `GET /api/v2/events` (historical
events, cyclones) · `GET /api/analyze` (geocode + NDMI scene) ·
`GET /api/exposure-features` (OSM) · `GET /api/fires` (FIRMS) ·
`GET /api/v2/analyze` (point screening) · `GET /api/reverse` (centre place
name) · `GET /api/trade-infrastructure` · `GET /api/population-exposure` ·
`GET /api/smoke-scenario` / `GET /api/smoke`.

## Files

- `website/map.html` — shell, sidebar, advanced strip.
- `website/js/map.js` — map init, selectors, layer panel,
  per-layer fetchers, advanced strip logic.
- `website/css/style.css` — "Map page" + "Advanced strip" sections.

## Tests

No dedicated map-page suite; coverage is indirect —
`tests/test_mapcheck.py` (Map Check engine — backend only now),
`tests/test_press_pages.py` (map "Act on this point" links),
`tests/test_hazard_snapshot.py` (`map.html?hazard=` links from the homepage).

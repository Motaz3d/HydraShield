# Talaix Climate Intelligence — QGIS plugin (Phase 0 spike)

Minimal, honest spike per `docs/QGIS_INTEGRATION_ARCHITECTURE.md` §16
Phase 0. **Not yet submitted to the QGIS plugin repository.**

## What it does

- **Hazard browser dock** — loads `GET /api/v2/hazards` (background
  `QgsTask`, never the GUI thread) and shows per hazard: enabled,
  analysis availability, events availability, official sources with URLs,
  and provenance.
- **`hydrashield:analyze_point` Processing algorithm** — analyzes a
  clicked/selected point via `GET /api/v2/analyze`, transforming any CRS
  to EPSG:4326 first. Output is a one-feature layer carrying hazard,
  status, level, score, summary, basis, validated and unavailable_reason.
  The API's honest states pass through untouched.

## Architecture rules (enforced)

- `QgsNetworkAccessManager.blockingGet` for all HTTP (QGIS proxy/SSL
  settings apply); network only on worker threads.
- No third-party Python dependencies — stdlib + PyQGIS only.
- No credentials in code or project files; an optional API key is
  referenced only as a QGIS **authcfg** id (`QgsSettings
  hydrashield/authcfg`), stored in the QGIS Authentication System.
- Provenance and screening-indicator honesty travel with every result.

## Compatibility status

- **QGIS 3.40 (LTR)**: target minimum (`qgisMinimumVersion=3.40`). Uses
  only long-stable APIs (QgsTask, QgsProcessingAlgorithm,
  QgsNetworkAccessManager.blockingGet since 3.6, QgsMapToolEmitPoint).
- **QGIS 4.x (Qt6)**: imports go through `qgis.PyQt` (the Qt5/Qt6
  abstraction); no Qt5-only APIs used; `QNetworkReply.NoError` avoided in
  favour of the numeric comparison. **Not yet machine-verified inside a
  QGIS 4.x runtime** — Phase 0 exit requires a manual smoke run in both
  (load plugin → registry loads → analyze_point produces a feature).
- Local CI covers: metadata contract, syntax compilation, the pure
  API-client functions, and the no-secrets rule (tests/test_qgis_plugin.py).

## Local install (development)

Symlink or copy `qgis-plugin/hydrashield/` into the QGIS profile's
`python/plugins/` directory, restart QGIS, enable "Talaix Climate
Intelligence" in the Plugin Manager.

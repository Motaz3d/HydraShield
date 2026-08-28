# Talaix Analytical Model (TAM) — the unified development template

Talaix is **not** one monolithic model, and it is not a pile of independent
models either. It is a **unified core with specialised engines**
(hub-and-spoke). This document is the binding contract every analytical
engine follows, so all of them evolve inside one development template.

## Layers

```
data fetchers            hazard plugins              product engines
src/dashboard/           src/climate/hazards/        src/climate/
real_data.py  ─────────▶ HazardModule (base.py) ───▶ ProductEngine (engine.py)
gis_mapping/             registry.py                 insurance · forensics · …
cache.py                 HazardAnalysis              ProductResult
```

1. **Data fetchers** (`src/dashboard/real_data.py`, `src/gis_mapping/`) —
   the only layer that performs I/O. Everything is cached through
   `src/dashboard/cache.py`. A fetcher never fabricates: a failed source
   returns an error/unavailable marker.
2. **Hazard plugins** (`src/climate/hazards/base.py`) — one `HazardModule`
   per hazard (wildfire, flood, drought, heat, wind, coastal, …), returning
   the uniform `HazardAnalysis`. Registered in `src/climate/registry.py`;
   a hazard without real, documented data sources is not registered.
3. **Product engines** (`src/climate/engine.py`) — combine hazard analyses
   into decision-facing products (insurance, forensics, sustainability,
   supply chain, verification, compound, …). Each returns the uniform
   `ProductResult` envelope.

## The shared vocabulary (never re-invented)

- **Evidence** — every claim carries an `EvidenceRecord`
  (`src/climate/evidence.py`) built on the controlled vocabularies of
  `src/climate/ontology.py`: `ClaimStatus` (OBSERVED / DOCUMENTED /
  REPORTED / MODELLED / INFERRED / UNKNOWN), `TemporalClass`, `EvidenceClass`,
  `Confidence`.
- **Clock** — `utcnow_iso()` from `src/climate/evidence.py` is the single
  timestamp source. Re-declaring it in any module is a contract violation
  (enforced by `tests/test_product_contract.py`).
- **Honesty contract** — unavailable data is stated (`status="unavailable"`
  + reason), never invented. `UNKNOWN` is a first-class status.
- **Versioning** — `TAM_VERSION` (in `src/climate/engine.py`) versions the
  contract itself; each engine keeps its own `ENGINE_VERSION` semver.

## Product engine contract

Every product engine subclasses `ProductEngine` (or, during migration,
exposes the same surface) and returns `ProductResult`:

| key | meaning |
|---|---|
| `product` | engine id, e.g. `"insurance"` |
| `status` | `ok` \| `partial` \| `unavailable` |
| `summary` | one-paragraph human summary |
| `blocks` | product-specific payload (merged at top level by `to_dict()`) |
| `evidence` | list of `EvidenceRecord` dicts |
| `disclaimer` | the engine's honesty disclaimer — part of the envelope |
| `engine_version` / `generated_at` / `tam_version` | provenance stamps |
| `unavailable_reason` | set iff `status="unavailable"` |

Reference implementation: `src/climate/insurance.py` (`InsuranceEngine`).
Remaining engines migrate to this shape one by one, each in its own commit
with its tests.

## Checklist for a new engine (hazard or product)

1. Subclass `HazardModule` / `ProductEngine`; import the clock and evidence
   vocabulary — never re-declare them.
2. Every claim carries `EvidenceRecord` provenance.
3. Unavailable inputs → declared `unavailable` + reason; never padded.
4. `ENGINE_VERSION` present; result passes through the uniform envelope.
5. Contract tests stay green: `pytest tests/test_product_contract.py`.
6. Significant scoring changes are recorded via `src/climate/evaluation.py`
   and, where ground truth exists, exercised through `src/climate/benchmark.py`.

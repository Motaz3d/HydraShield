#!/usr/bin/env python
"""
Live integration test: verify that the platform really uses real data.

Requires network access. Run from the hydra-shield-platform directory:

    python test_real_integration.py

Checks, for a European location:
    1. Real Sentinel-2 scene discovery + band-derived NDVI/NDMI (STAC).
    2. The full analysis pipeline (terrain, weather, FWI, land cover, risk).
    3. The population/ignition/smoke intelligence blocks (real sources or
       honest unavailability — never fabricated content).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.gis_mapping.copernicus_data import CopernicusDataAccess
from src.dashboard.real_analysis import HydraShieldRealAnalyser


def test_copernicus_integration() -> bool:
    """Real Sentinel-2 via the Earth Search STAC catalog."""
    print("Testing real Sentinel-2 (STAC) integration...")
    access = CopernicusDataAccess()
    lat, lon = 49.9, 6.03  # Clervaux area, Luxembourg

    observation = access.get_latest_observation(lat, lon, days_back=30, max_cloud_cover=40.0)
    if observation is None:
        print("⚠ No usable Sentinel-2 scene in the last 30 days (cloud cover).")
        print("  This is a valid outcome — the platform reports it as unavailable.")
        return True

    print(f"  Product:   {observation.product_id}")
    print(f"  Date:      {observation.timestamp.date()}")
    print(f"  NDVI:      {observation.ndvi}")
    print(f"  NDMI:      {observation.ndmi}")
    print(f"  Cloud:     {observation.cloud_cover_pct}%")
    print(f"  Source:    {observation.source}")
    if observation.ndvi is None or observation.ndmi is None:
        print("✗ Missing indices"); return False
    print("✓ Real Sentinel-2 indices retrieved")
    return True


def test_full_analysis_integration() -> bool:
    """Full pipeline on real data."""
    print("\nTesting full analysis pipeline...")
    result = HydraShieldRealAnalyser().analyse("Clervaux, Luxembourg")
    if "error" in result:
        print(f"✗ Analysis error: {result['error']}"); return False

    analysis = result["analysis"]
    fd = result.get("fire_danger") or {}
    print(f"  Location:     {result['location']['name']}")
    print(f"  Terrain:      {result['terrain'].get('elevation_m')} m ({result['terrain'].get('source')})")
    print(f"  Fuel moisture:{analysis['fuel_moisture_baseline_pct']}% — {analysis['fuel_moisture_source']}")
    print(f"  FWI:          {fd.get('fwi')} ({fd.get('class')}) on {fd.get('date')}")
    print(f"  Land cover:   {result['landcover'].get('dominant_label')} -> fuel {analysis['fire_spread']['fuel_model']}")
    print(f"  Risk:         {analysis['risk']['baseline']}/100 ({analysis['risk']['class']})")
    print(f"  Provenance:   {len(result.get('provenance', {}))} components documented")

    ok = (
        result["terrain"].get("elevation_m") is not None
        and fd.get("available")
        and analysis["risk"]["baseline"] is not None
    )
    print("✓ Full real-data analysis completed" if ok else "✗ Incomplete analysis")
    return (result if ok else None)


def test_intelligence_blocks(result) -> bool:
    """Population / ignition / smoke blocks: real data or honest unavailability."""
    print("\nTesting population / ignition / smoke intelligence blocks...")
    ok = True

    pop = result.get("population") or {}
    if pop.get("status") == "ok":
        note = pop.get("estimate_note") or ""
        print(f"  Population: ~{pop.get('estimated_population')} "
              f"({pop.get('mean_density_per_km2')}/km²), ref {pop.get('reference_year')}")
        if "Estimated" not in note or "reference year" not in note:
            print("✗ Population wording must keep the estimate + reference-year framing")
            ok = False
        if pop.get("human_exposure_priority") not in ("high", "moderate", "watch", "routine"):
            print("✗ Unknown human_exposure_priority"); ok = False
    else:
        print(f"  Population: UNAVAILABLE ({pop.get('reason')}) — valid honest outcome")

    ign = result.get("ignition") or {}
    if ign.get("status") == "ok":
        print(f"  Ignition:   {ign.get('indicator')}/100 ({ign.get('class')}) — "
              f"{ign.get('name')}")
        vs = ign.get("validation_status") or {}
        if vs.get("validated") is not False or "NOT VALIDATED" not in (vs.get("status") or ""):
            print("✗ Ignition indicator must carry the NOT VALIDATED status"); ok = False
        if "not_a_probability" not in ign:
            print("✗ Ignition block must carry the not-a-probability note"); ok = False
    else:
        print(f"  Ignition:   UNAVAILABLE ({ign.get('reason')}) — valid honest outcome")

    smoke_s = result.get("smoke_scenario") or {}
    if smoke_s.get("status") == "ok":
        tr = smoke_s.get("transport") or {}
        print(f"  Smoke:      corridor {tr.get('dominant_transport_direction')} "
              f"@ {tr.get('mean_transport_speed_kmh')} km/h "
              f"(confidence {tr.get('confidence')})")
        if smoke_s.get("mode") != "scenario" or "SCENARIO" not in (smoke_s.get("mode_label") or ""):
            print("✗ Smoke block must be labelled SCENARIO / MODELLED"); ok = False
        if tr.get("confidence") not in ("low", "moderate"):
            print("✗ Smoke confidence must be low/moderate (never high)"); ok = False
    else:
        print(f"  Smoke:      UNAVAILABLE ({smoke_s.get('error')}) — valid honest outcome")

    prov = result.get("provenance") or {}
    for key in ("population", "ignition", "smoke_scenario"):
        if key not in prov:
            print(f"✗ provenance['{key}'] missing"); ok = False
    print(f"  Provenance: {len(prov)} components documented")
    print("✓ Intelligence blocks consistent" if ok else "✗ Intelligence block problems")
    return ok


def main() -> int:
    print("=" * 60)
    print("HydraShield real-data integration test")
    print("=" * 60)
    s2_ok = test_copernicus_integration()
    analysis_result = test_full_analysis_integration()
    results = [s2_ok, analysis_result is not None]
    if analysis_result is not None:
        results.append(test_intelligence_blocks(analysis_result))
    print("=" * 60)
    print(f"Passed {sum(results)}/{len(results)}")
    print("✓ The platform is using real data." if all(results) else "✗ Failures — see above.")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""
Warm the public risk-snapshot cache.

Builds (or refreshes) the cached /api/risk-snapshot aggregate from real
analyses of the configured monitored areas. Intended to run periodically
inside the stack (see the watch_checker service in docker-compose.yml) so
homepage requests are always served from cache.

    python scripts/build_risk_snapshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dashboard import snapshot as snapshot_module  # noqa: E402
from src.dashboard.cache import default_cache  # noqa: E402


def main() -> int:
    # Memory guard: a runaway allocation inside one analysis (a multi-GB
    # satellite/raster read) must NOT let the kernel OOM-kill the whole
    # builder on the 4 GB host — RLIMIT_AS turns it into a catchable
    # MemoryError, the offending area is skipped honestly (compute_snapshot
    # already swallows per-area exceptions) and the build still completes.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    except (ImportError, ValueError, OSError):
        pass  # non-Linux or restricted environment — no guard

    # Drop the current entry so this run always rebuilds from fresh analyses.
    # This script is the ONLY builder (watch_checker loop): the request path
    # never builds inline (production OOM lesson — see snapshot.py).
    default_cache().delete(snapshot_module._CACHE_KEY)
    snap = snapshot_module.get_snapshot(build=True)
    status = snap.get("status")
    n = len(snap.get("entries") or [])
    print(f"Risk snapshot: {status} ({n} entries, scope: {snap.get('scope', 'n/a')})")
    for e in snap.get("entries") or []:
        print(f"  {e['rank']}. {e['name']}: {e['risk']} ({e['risk_class']}), FWI {e['fwi']}")
    if status != "ok":
        print(f"  note: {snap.get('message')}")

    # Multi-hazard board (every other registered hazard at the same areas).
    # Built here, in the periodic worker — never on the request path (the
    # cold 80-analysis build OOM-killed a gunicorn worker; see the module).
    from src.dashboard import hazard_snapshot as hazard_snapshot_module

    default_cache().delete(hazard_snapshot_module._CACHE_KEY)
    multi = hazard_snapshot_module.get_hazard_snapshot(build=True)
    mstatus = multi.get("status")
    boards = sum(1 for h in multi.get("hazards") or [] if h.get("entries"))
    print(f"Multi-hazard snapshot: {mstatus} ({boards} hazard boards)")
    for h in multi.get("hazards") or []:
        for e in h.get("entries") or []:
            score = e.get("level_score")
            print(f"  {h['hazard']}: {e['name']} — {e.get('level_label')}"
                  + (f" ({score}/{e.get('level_score_max')})" if score is not None else ""))
    if mstatus != "ok":
        print(f"  note: {multi.get('message')}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

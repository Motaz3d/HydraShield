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
    # Drop the current entry so this run always rebuilds from fresh analyses.
    default_cache().delete(snapshot_module._CACHE_KEY)
    snap = snapshot_module.get_snapshot()
    status = snap.get("status")
    n = len(snap.get("entries") or [])
    print(f"Risk snapshot: {status} ({n} entries, scope: {snap.get('scope', 'n/a')})")
    for e in snap.get("entries") or []:
        print(f"  {e['rank']}. {e['name']}: {e['risk']} ({e['risk_class']}), FWI {e['fwi']}")
    if status != "ok":
        print(f"  note: {snap.get('message')}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

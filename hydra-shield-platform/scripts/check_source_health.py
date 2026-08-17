#!/usr/bin/env python
"""
Periodic source-health checker (Source Intelligence layer).

Probes every ``integrated`` dataset in config/data_registry.json (HTTP GET
of its API/download URL or catalogue URL root, 10 s timeout, platform UA)
and records status / latency / ok / status_change into the shared platform
DB (``source_health`` table). This is the ONLY place health records are
created — the API never fabricates health data, it only reads what this
checker wrote.

Intended to run on the same cycle as the watch checker (docker-compose
``watch_checker`` service, every 30 minutes) or by cron:

    */30 * * * * cd /code && python scripts/check_source_health.py >> /var/log/source_health.log 2>&1

Exit code is 0 even when individual sources are down — a down source is a
health RECORD, not a checker failure. Exit code 1 only when the sweep
itself could not run (e.g. the data registry is unreadable).
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.climate.source_health import check_integrated_sources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("check_source_health")


def main() -> int:
    try:
        summary = check_integrated_sources()
    except Exception as exc:
        log.error("Source-health sweep could not run: %s", exc)
        return 1

    log.info("Checked %d integrated source(s): %d ok, %d down",
             summary["checked"], summary["ok"], summary["down"])
    for t in summary["transitions"]:
        log.info("TRANSITION %s: %s (http_status=%s note=%s)",
                 t["dataset_id"], t["status_change"], t["http_status"], t["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

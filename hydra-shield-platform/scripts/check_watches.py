#!/usr/bin/env python
"""
Periodic watch checker (Phase 5).

Re-analyses every registered watch, compares the current composite risk
against the watch threshold, and fires an alert on upward crossings. Alerts
are emailed when SMTP_* env vars are configured, otherwise recorded in the
database and logged. Intended to be run by cron, e.g. inside the api
container:

    */30 * * * * cd /code && python scripts/check_watches.py >> /var/log/watches.log 2>&1

Exit code is 0 even when individual watches fail; failures are logged.
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dashboard.monitoring import WatchStore, send_email_alert  # noqa: E402
from src.dashboard.real_analysis import HydraShieldRealAnalyser  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("check_watches")


def main() -> int:
    store = WatchStore()
    watches = store.list_watches()
    if not watches:
        log.info("No watches registered.")
        return 0

    analyser = HydraShieldRealAnalyser()
    log.info("Checking %d watch(es)...", len(watches))

    for watch in watches:
        wid = watch["id"]
        try:
            result = analyser.analyse_point(watch["lat"], watch["lon"], name=watch["location"])
            if "error" in result:
                log.warning("Watch %s: analysis error: %s", wid[:8], result["error"])
                continue

            risk = result["analysis"]["risk"]["baseline"]
            risk_class = result["analysis"]["risk"]["class"]
            store.update_check(wid, risk)

            crossed = (
                risk is not None
                and risk >= watch["threshold_risk"]
                and (watch.get("last_risk") is None or watch["last_risk"] < watch["threshold_risk"])
            )
            if not crossed:
                log.info("Watch %s (%s): risk %.1f below threshold %.1f",
                         wid[:8], watch["location"], risk or -1, watch["threshold_risk"])
                continue

            subject = f"HydraShield alert: {risk_class} wildfire risk at {watch['location']}"
            body = (
                f"HydraShield watch alert\n\n"
                f"Location:  {watch['location']}\n"
                f"Risk:      {risk}/100 ({risk_class})\n"
                f"Threshold: {watch['threshold_risk']}/100\n"
                f"FWI:       {result.get('fire_danger', {}).get('fwi')} "
                f"({result.get('fire_danger', {}).get('class')})\n"
                f"Checked:   {result.get('generated_at')}\n\n"
                f"Details: https://hydrashield.earth/dashboard.html?location="
                f"{watch['lat']},{watch['lon']}\n"
            )
            sent = False
            try:
                sent = send_email_alert(watch["email"], subject, body)
            except Exception as exc:
                log.error("Watch %s: email send failed: %s", wid[:8], exc)

            store.record_alert(
                wid, risk, risk_class or "unknown",
                channel="email" if sent else "db_only",
                payload={"subject": subject, "body": body},
            )
            log.info("Watch %s: ALERT fired (risk %.1f, channel=%s)",
                     wid[:8], risk, "email" if sent else "db_only")
        except Exception as exc:
            log.error("Watch %s: check failed: %s", wid[:8], exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())

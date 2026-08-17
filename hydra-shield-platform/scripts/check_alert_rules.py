#!/usr/bin/env python
"""
Periodic alert-rule checker (Stage 7 SMS/email alerting).

Evaluates every active alert rule against a fresh REAL analysis and fires
notifications (SMS + email + webhooks, per user preferences) on meaningful
severity transitions — upward threshold crossings and downward recoveries —
plus the additional significant-change trigger (declared 24 h / 7 d delta
on the real daily FWI-anchored risk-score series, NOT a validated anomaly
model) when the analysis carries a usable daily series; when it does not,
significant-change is skipped honestly. Intended
to be run on the same cycle as the watch checker (docker-compose
``watch_checker`` service, every 30 minutes) or by cron:

    */30 * * * * cd /code && python scripts/check_alert_rules.py >> /var/log/alerts.log 2>&1

Wildfire rules use the full ``HydraShieldRealAnalyser`` pipeline. Other
registered hazards use their registry module's ``analyze`` and classify
severity from ``level.score``; a hazard that yields no score is skipped
honestly ("no computable severity") — nothing is ever invented.

Exit code is 0 even when individual rules fail; failures are logged.
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dashboard import mailer, sms  # noqa: E402
from src.dashboard.accounts import UserStore  # noqa: E402
from src.dashboard.alert_engine import (  # noqa: E402
    daily_risk_scores_from_analysis,
    process_rule,
)
from src.dashboard.notify_store import NotifyStore  # noqa: E402
from src.dashboard.real_analysis import HydraShieldRealAnalyser  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("check_alert_rules")


def _analyse_rule(rule, analyser):
    """Run the real analysis for a rule; returns a dict suitable for
    ``process_rule`` or None when nothing computable is available."""
    hazard = rule["hazard"]
    if hazard == "wildfire":
        result = analyser.analyse_point(rule["lat"], rule["lon"], name=rule.get("name"))
        if "error" in result:
            log.warning("Rule %s: analysis error: %s", rule["id"], result["error"])
            return None
        return result
    from src.climate import registry

    module = registry.get(hazard)
    if module is None:
        log.warning("Rule %s: hazard %r not registered — skipped", rule["id"], hazard)
        return None
    analysis = module.analyze(rule["lat"], rule["lon"], name=rule.get("name"))
    return analysis.to_dict(include_raw=False)


def main() -> int:
    store = NotifyStore()
    rules = store.list_active_rules()
    if not rules:
        log.info("No active alert rules.")
        return 0

    analyser = HydraShieldRealAnalyser()
    user_store = UserStore(store.db_path)
    log.info("Checking %d alert rule(s)...", len(rules))

    for rule in rules:
        try:
            analysis = _analyse_rule(rule, analyser)
            if analysis is None:
                continue
            user = user_store.get_user(rule["user_id"])
            # Real daily FWI-anchored risk-score series for the
            # significant-change trigger; None → significant-change is
            # skipped honestly (threshold transitions still apply).
            daily_scores = daily_risk_scores_from_analysis(analysis)
            outcome = process_rule(
                store, rule, analysis, mailer=mailer, sms=sms, user=user,
                daily_scores=daily_scores)
            status = outcome.get("status")
            if status == "no_computable_severity":
                log.info("Rule %s (%s): no computable severity — skipped honestly",
                         rule["id"], rule["hazard"])
            elif outcome.get("trigger"):
                log.info("Rule %s (%s): ALERT %s → %s (dispatch=%s)",
                         rule["id"], rule["hazard"], outcome.get("trigger"),
                         outcome.get("severity"), outcome.get("dispatch"))
            else:
                log.info("Rule %s (%s): severity %s, no transition",
                         rule["id"], rule["hazard"], outcome.get("severity"))
        except Exception as exc:
            log.error("Rule %s: check failed: %s", rule["id"], exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())

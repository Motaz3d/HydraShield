"""
Talaix unified alert engine.

Turns REAL analysis results into high-value intelligence notifications
(SMS + email + webhooks) for alert rules. Core semantics:

- Severity is classified from the real composite risk score onto
  ``SEVERITY_ORDER`` using the same thresholds as
  ``TalaixRealAnalyser.RISK_CLASSES`` (Low < 25, Moderate < 45,
  High < 65, Extreme >= 65 → NORMAL | MODERATE | HIGH | EXTREME).
- Notifications fire only on MEANINGFUL transitions
  (:func:`evaluate_transition`): an upward crossing of the rule's
  threshold, and a downward recovery back below it. Same-severity
  re-checks stay silent.
- An ADDITIONAL independent notify path is the significant-change trigger
  (:func:`evaluate_significant_change`): a declared 24 h / 7 d delta
  heuristic on the real daily FWI-anchored risk-score series — NOT a
  validated anomaly model. It fires through the same dispatch and the
  same dedupe/anti-flood machinery with trigger ``"significant_change"``.
- Message content is always generated from the real analysis (FWI class /
  fire danger, real recommendations) — values are never invented.
- Delivery respects user preferences: channel routing (SMS needs a
  verified phone), quiet hours (SMS held, email still sent), a per-user
  daily cap across channels, and a 6 h dedupe cooldown for identical
  rule+hazard+severity+trigger alerts.
- After email/SMS, active webhook subscriptions of the user are notified
  (``webhooks.dispatch_webhooks``, channel ``"webhook"``); webhook
  failures never break the other channels.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("hydrashield.alert_engine")

SEVERITY_ORDER = ["NORMAL", "MODERATE", "HIGH", "EXTREME"]

DEDUPE_COOLDOWN_SECONDS = 6 * 3600.0

SITE_URL = "talaix.com"


def classify_severity(risk: Optional[float]) -> Optional[str]:
    """
    Map a composite risk score (0-100, real analysis baseline) onto the
    severity ladder, using the same thresholds as
    ``TalaixRealAnalyser.RISK_CLASSES``: Low < 25 → NORMAL,
    Moderate < 45 → MODERATE, High < 65 → HIGH, Extreme >= 65 → EXTREME.
    ``None`` (no computable score) maps to None — never invented.
    """
    if risk is None:
        return None
    try:
        value = float(risk)
    except (TypeError, ValueError):
        return None
    if value < 25.0:
        return "NORMAL"
    if value < 45.0:
        return "MODERATE"
    if value < 65.0:
        return "HIGH"
    return "EXTREME"


def evaluate_transition(
    old: Optional[str],
    new: Optional[str],
    threshold: str,
) -> Tuple[bool, Optional[str]]:
    """
    Decide whether a severity change warrants a notification.

    Notifies only on meaningful transitions relative to the rule
    threshold:

    - upward crossing: severity moves from below the threshold to at or
      above it (e.g. below → HIGH when threshold=HIGH; HIGH → EXTREME
      when threshold=EXTREME) — trigger ``"threshold_crossing"``;
    - downward recovery: severity falls from at/above the threshold back
      below it — trigger ``"recovery"``.

    Same-severity (or same-side) re-checks do not notify. A missing new
    severity (no computable score) never notifies.
    """
    if new not in SEVERITY_ORDER:
        return False, None
    threshold_rank = SEVERITY_ORDER.index(threshold) if threshold in SEVERITY_ORDER else 2
    new_rank = SEVERITY_ORDER.index(new)
    old_rank = SEVERITY_ORDER.index(old) if old in SEVERITY_ORDER else -1
    if new_rank >= threshold_rank and old_rank < threshold_rank:
        return True, "threshold_crossing"
    if new_rank < threshold_rank and old_rank >= threshold_rank:
        return True, "recovery"
    return False, None


def evaluate_significant_change(
    series,
    *,
    window: int = 1,
    threshold: float = 20.0,
) -> Tuple[bool, Dict]:
    """
    Significant-change trigger — DECLARED HEURISTIC, not a validated
    anomaly model.

    Declared method: on the real daily risk-score series (0-100 scale,
    FWI-anchored — see :func:`daily_risk_scores_from_analysis`), fire when

        |latest − value ``window`` days earlier| >= ``threshold``

    points. ``window`` is 1 (24 h delta) or 7 (7 d delta). Returns
    ``(fired, detail)`` where detail carries the exact inputs used so the
    notification path stays auditable. A series shorter than
    ``window + 1`` days never fires (insufficient real data — nothing is
    interpolated or invented).
    """
    if window not in (1, 7):
        raise ValueError("window must be 1 (24 h) or 7 (7 d)")
    values: List[float] = []
    for value in series or []:
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    detail: Dict = {"window_days": window, "threshold": float(threshold),
                    "series_days": len(values)}
    if len(values) < window + 1:
        detail["reason"] = "insufficient_series"
        return False, detail
    latest = values[-1]
    previous = values[-1 - window]
    delta = latest - previous
    detail.update({
        "latest": round(latest, 2), "previous": round(previous, 2),
        "delta": round(delta, 2),
        "direction": "rise" if delta > 0 else ("fall" if delta < 0 else "flat"),
    })
    return abs(delta) >= float(threshold), detail


def daily_risk_scores_from_analysis(analysis: Dict) -> Optional[list]:
    """
    Derive the daily risk-score series (0-100) from the REAL daily FWI
    series of a wildfire analysis (``fire_danger.series``), using the same
    FWI anchor as the composite risk score: ``100 * FWI / (FWI + 25)``.

    DECLARED simplification: the daily composite would also need per-day
    slope/fuel/wind terms, which are not recomputed per day; the FWI anchor
    alone is the declared risk-scale projection used by the
    significant-change trigger. Returns None when the analysis carries no
    usable daily series (significant-change is then skipped honestly).
    """
    fire_danger = analysis.get("fire_danger") if isinstance(analysis, dict) else None
    if not isinstance(fire_danger, dict):
        blocks = analysis.get("blocks") if isinstance(analysis, dict) else None
        fire_danger = (blocks or {}).get("fire_danger") if isinstance(blocks, dict) else None
    series = (fire_danger or {}).get("series") or []
    scores: List[float] = []
    for day in series:
        fwi = day.get("fwi") if isinstance(day, dict) else None
        if fwi is None:
            continue
        try:
            fwi = float(fwi)
        except (TypeError, ValueError):
            continue
        if fwi < 0:
            continue
        scores.append(round(100.0 * fwi / (fwi + 25.0), 2))
    return scores or None


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_sms_message(
    hazard: str,
    location: str,
    severity: str,
    driver: str,
    action: str,
    time_utc: str,
) -> str:
    """
    Compact alert SMS (kept ≤ ~320 chars). ``driver``/``action`` come from
    the real analysis (e.g. FWI class / fire danger / real recommendations)
    — never invented.
    """
    message = (
        "HYDRASHIELD ALERT\n"
        f"{_clip(hazard, 24).capitalize()}: {severity}\n"
        f"{_clip(location, 80)}\n"
        f"Main driver: {_clip(driver, 90)}\n"
        f"Action: {_clip(action, 110)}\n"
        f"{_clip(time_utc, 30)} UTC\n"
        f"{SITE_URL}"
    )
    return message[:320]


# ---------------------------------------------------------------------------
# Content extraction from real analysis results
# ---------------------------------------------------------------------------

def analysis_severity(analysis: Dict) -> Optional[str]:
    """
    Classify severity from a real analysis result. Supports the native
    wildfire analyser payload (``analysis.risk.baseline``) and the
    multi-hazard contract (``level.score``); returns None when no
    computable score exists.
    """
    risk = None
    inner = analysis.get("analysis") if isinstance(analysis, dict) else None
    if isinstance(inner, dict):
        risk = (inner.get("risk") or {}).get("baseline")
    if risk is None:
        level = analysis.get("level") if isinstance(analysis, dict) else None
        if isinstance(level, dict):
            risk = level.get("score")
    return classify_severity(risk)


def analysis_driver_action(analysis: Dict, severity: str) -> Tuple[str, str]:
    """
    Extract the main driver and a recommended action from the real
    analysis (FWI / fire danger class / top real recommendation). When
    the analysis carries no actionable content the action points at the
    full analysis on the site — nothing is invented.
    """
    driver = ""
    fire_danger = analysis.get("fire_danger") or {}
    if not isinstance(fire_danger, dict):
        fire_danger = {}
    blocks = analysis.get("blocks") or {}
    if not fire_danger and isinstance(blocks, dict):
        fire_danger = blocks.get("fire_danger") or {}
    fwi = fire_danger.get("fwi") if isinstance(fire_danger, dict) else None
    fwi_class = fire_danger.get("class") if isinstance(fire_danger, dict) else None
    if fwi is not None:
        driver = f"FWI {fwi} ({fwi_class})" if fwi_class else f"FWI {fwi}"
    elif fwi_class:
        driver = f"Fire danger {fwi_class}"
    if not driver:
        level = analysis.get("level")
        if isinstance(level, dict) and level.get("label"):
            driver = f"{analysis.get('hazard', 'hazard')} level {level['label']}"
    if not driver:
        risk_class = ((analysis.get("analysis") or {}).get("risk") or {}).get("class") \
            if isinstance(analysis.get("analysis"), dict) else None
        driver = f"Risk class {risk_class}" if risk_class else f"{severity} severity"

    action = ""
    recommendations = analysis.get("recommendations") or []
    if recommendations and isinstance(recommendations[0], dict):
        action = recommendations[0].get("what") or ""
    if not action and isinstance(analysis.get("summary"), str):
        action = analysis["summary"]
    if not action:
        action = f"See full real-data analysis at {SITE_URL}"
    return driver, action


# ---------------------------------------------------------------------------
# Quiet hours (UTC, HH:MM)
# ---------------------------------------------------------------------------

def in_quiet_hours(prefs: Dict, now_utc: Optional[datetime] = None) -> bool:
    quiet = prefs.get("quiet_hours")
    if not quiet:
        return False
    start, end = quiet.get("start"), quiet.get("end")
    if not start or not end:
        return False
    now = (now_utc or datetime.utcnow()).strftime("%H:%M")
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # overnight window, e.g. 22:00-07:00


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_alert(
    store,
    user: Dict,
    rule: Dict,
    analysis: Dict,
    *,
    mailer,
    sms,
    severity: Optional[str] = None,
    trigger: Optional[str] = None,
) -> Dict:
    """
    Record and deliver one fired alert for ``rule``/``user``.

    - Dedupe: the same rule+hazard+severity+trigger inside the 6 h
      cooldown is recorded as ``suppressed_duplicate`` and not sent.
    - Daily cap: ``max_per_day`` deliveries per user across channels;
      beyond the cap the alert is recorded suppressed and not sent.
    - Quiet hours: SMS is recorded ``held_quiet_hours`` (not sent);
      email is still sent.
    - Channel routing: SMS only when sms_enabled AND a verified phone
      exists; email when email_enabled AND the user has an address;
      webhooks for every active subscription listing the event.

    Returns a result dict describing what happened (never any secrets).
    """
    severity = severity or analysis_severity(analysis)
    trigger = trigger or "threshold_crossing"
    prefs = store.get_prefs(user["id"])
    location = rule.get("name") or f"{rule['lat']}, {rule['lon']}"
    analysis_id = str(
        analysis.get("generated_at")
        or (analysis.get("location") or {}).get("name")
        or "")
    risk_class = None
    if isinstance(analysis.get("analysis"), dict):
        risk_class = ((analysis["analysis"].get("risk") or {}).get("class"))
    elif isinstance(analysis.get("level"), dict):
        risk_class = analysis["level"].get("label")
    data_version = f"real-analysis:{risk_class or 'unknown'}"
    result: Dict = {
        "rule_id": rule["id"], "user_id": user["id"], "severity": severity,
        "trigger": trigger, "deliveries": [], "sent": False,
    }

    recent = store.find_recent_alert(
        rule["id"], rule["hazard"], severity, trigger, DEDUPE_COOLDOWN_SECONDS)
    if recent is not None:
        alert_id = store.record_alert(
            user["id"], rule["id"], rule["hazard"], rule["lat"], rule["lon"],
            severity, trigger, analysis_id, data_version, suppressed=True)
        store.record_delivery(alert_id, "sms", None, "suppressed_duplicate")
        result.update({"status": "suppressed_duplicate", "alert_id": alert_id,
                       "duplicate_of": recent["id"]})
        return result

    if store.count_deliveries_today(user["id"]) >= prefs["max_per_day"]:
        alert_id = store.record_alert(
            user["id"], rule["id"], rule["hazard"], rule["lat"], rule["lon"],
            severity, trigger, analysis_id, data_version, suppressed=True)
        result.update({"status": "max_per_day_reached", "alert_id": alert_id,
                       "max_per_day": prefs["max_per_day"]})
        return result

    alert_id = store.record_alert(
        user["id"], rule["id"], rule["hazard"], rule["lat"], rule["lon"],
        severity, trigger, analysis_id, data_version, suppressed=False)

    driver, action = analysis_driver_action(analysis, severity)
    time_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    message = build_sms_message(
        rule["hazard"], location, severity, driver, action, time_utc)

    # -- SMS channel -----------------------------------------------------
    phone = store.get_verified_phone(user["id"])
    if prefs["sms_enabled"]:
        if phone is None:
            store.record_delivery(alert_id, "sms", None, "disabled")
            result["deliveries"].append({"channel": "sms", "status": "disabled"})
        elif in_quiet_hours(prefs):
            store.record_delivery(alert_id, "sms", phone["e164"], "held_quiet_hours")
            result["deliveries"].append(
                {"channel": "sms", "status": "held_quiet_hours"})
        else:
            try:
                outcome = sms.send_sms(phone["e164"], message)
            except Exception as exc:  # delivery failures recorded honestly
                outcome = {"backend": "error", "error": str(exc)}
            backend = outcome.get("backend")
            if backend == "http":
                status = "sent"
            elif backend == "outbox":
                status = "outbox"
            else:
                status = "failed"
            store.record_delivery(alert_id, "sms", phone["e164"], status,
                                  provider_message_id=outcome.get("provider_message_id"))
            result["deliveries"].append({"channel": "sms", "status": status})
            result["sent"] = result["sent"] or status in ("sent", "outbox")

    # -- Email channel ---------------------------------------------------
    if prefs["email_enabled"] and user.get("email"):
        subject = f"Talaix alert: {severity} {rule['hazard']} at {location}"
        try:
            outcome = mailer.send_mail(
                user["email"], "alert",
                {"subject": subject, "message": message},
                subject_override=subject,
            )
            status = "sent" if outcome.get("backend") == "smtp" else "outbox"
        except Exception as exc:
            log.warning("Alert email to user %s failed: %s", user["id"], exc)
            status = "failed"
        store.record_delivery(alert_id, "email", user["email"], status)
        result["deliveries"].append({"channel": "email", "status": status})
        result["sent"] = result["sent"] or status in ("sent", "outbox")

    # -- Webhook channel --------------------------------------------------
    # Active subscriptions of the user that list this event. The event name
    # follows the trigger: significant-change alerts fire the
    # "significant_change" event, everything else "alert_fired". Failures
    # are recorded (channel "webhook") but never break email/SMS.
    event_type = "significant_change" if trigger == "significant_change" else "alert_fired"
    webhook_payload = {
        "alert_id": alert_id,
        "hazard": rule["hazard"],
        "location": {"name": rule.get("name"), "lat": rule["lat"], "lon": rule["lon"]},
        "severity": severity,
        "trigger": trigger,
        "analysis_id": analysis_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    try:
        from .webhooks import dispatch_webhooks

        webhook_results = dispatch_webhooks(
            store, user["id"], event_type, webhook_payload, alert_id=alert_id)
    except Exception as exc:  # defensive: dispatch_webhooks never raises
        log.warning("Webhook dispatch failed for user %s: %s", user["id"], exc)
        webhook_results = []
    for delivery in webhook_results:
        result["deliveries"].append({
            "channel": "webhook", "status": delivery["status"],
            "webhook_id": delivery["webhook_id"],
        })
        result["sent"] = result["sent"] or delivery["status"] == "sent"

    # Audit: operational facts only — never codes, credentials or targets.
    store.audit(user["id"], "alert_fired", target=location,
                meta={"rule_id": rule["id"], "hazard": rule["hazard"],
                      "severity": severity, "trigger": trigger,
                      "channels": [d["channel"] for d in result["deliveries"]]})
    result.update({"status": "dispatched", "alert_id": alert_id})
    return result


# ---------------------------------------------------------------------------
# Rule processing (periodic checker)
# ---------------------------------------------------------------------------

def process_rule(
    store,
    rule: Dict,
    analysis: Dict,
    *,
    mailer,
    sms,
    user: Optional[Dict] = None,
    daily_scores: Optional[List[float]] = None,
) -> Dict:
    """
    Evaluate one rule against a fresh real analysis: classify severity,
    compare with the rule's last severity via :func:`evaluate_transition`,
    dispatch on meaningful transitions, and always update the rule's
    last-severity / last-checked state. Returns a descriptor dict.

    ``daily_scores`` is the optional real daily FWI-anchored risk-score
    series (see :func:`daily_risk_scores_from_analysis`). When given, the
    significant-change heuristic (:func:`evaluate_significant_change`,
    declared 24 h / 7 d delta — NOT a validated anomaly model) is
    evaluated as an ADDITIONAL notify path with trigger
    ``"significant_change"``: it fires independently of the threshold
    transition but through the same dispatch and the same
    dedupe/anti-flood machinery. When ``daily_scores`` is absent,
    significant-change is skipped honestly. The rule's
    ``severity_threshold`` still applies to threshold triggers only.
    """
    severity = analysis_severity(analysis)
    if severity is None:
        store.update_rule_state(rule["id"], rule.get("last_severity"))
        return {"rule_id": rule["id"], "status": "no_computable_severity",
                "notified": False}

    notify, trigger = evaluate_transition(
        rule.get("last_severity"), severity, rule["severity_threshold"])

    # Additional independent notify path: significant change on the real
    # daily risk-score series (24 h delta first, then 7 d). At most one
    # significant-change dispatch per run.
    significant: Optional[Dict] = None
    notify_sc = False
    if daily_scores:
        for window in (1, 7):
            notify_sc, detail = evaluate_significant_change(daily_scores, window=window)
            if notify_sc:
                break
        significant = detail
        significant["fired"] = notify_sc

    outcome: Dict = {"rule_id": rule["id"], "severity": severity,
                     "previous": rule.get("last_severity"),
                     "notified": False, "trigger": None}
    if significant is not None:
        outcome["significant_change"] = significant

    if notify or notify_sc:
        if user is None:
            from .accounts import UserStore

            user = UserStore(store.db_path).get_user(rule["user_id"])
        if user is None:
            store.update_rule_state(rule["id"], severity)
            outcome["status"] = "user_missing"
            return outcome
        if notify:
            dispatch = dispatch_alert(
                store, user, rule, analysis,
                mailer=mailer, sms=sms, severity=severity, trigger=trigger)
            outcome.update({"notified": dispatch.get("sent", False),
                            "trigger": trigger,
                            "dispatch": dispatch.get("status"),
                            "alert_id": dispatch.get("alert_id")})
        if notify_sc:
            dispatch_sc = dispatch_alert(
                store, user, rule, analysis,
                mailer=mailer, sms=sms, severity=severity,
                trigger="significant_change")
            outcome["notified"] = outcome["notified"] or dispatch_sc.get("sent", False)
            outcome["significant_change"].update({
                "dispatch": dispatch_sc.get("status"),
                "alert_id": dispatch_sc.get("alert_id"),
            })
            if not notify:
                outcome["trigger"] = "significant_change"
                outcome["alert_id"] = dispatch_sc.get("alert_id")

    store.update_rule_state(rule["id"], severity)
    outcome.setdefault("status", "ok")
    return outcome

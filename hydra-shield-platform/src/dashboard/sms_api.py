"""
Talaix alerting API (Stage 7) — Flask blueprint ``sms_bp``.

Mounted at ``/api/v2`` (registered in ``src/dashboard/api.py::create_app()``
right after ``auth_bp``). Implements the SMS/alerting endpoints:

    POST   /api/v2/alerts/phone            register phone → verification code via SMS
    POST   /api/v2/alerts/phone/verify     verify the 6-digit code
    DELETE /api/v2/alerts/phone            remove own phone
    GET    /api/v2/alerts/preferences      own notification preferences
    PATCH  /api/v2/alerts/preferences      update preferences
    GET    /api/v2/alerts/rules            own alert rules
    POST   /api/v2/alerts/rules            create rule (tier-capped)
    DELETE /api/v2/alerts/rules/<id>       delete own rule
    GET    /api/v2/alerts/history          own alert records + deliveries
    POST   /api/v2/alerts/unsubscribe      explicit SMS opt-out

Progressive access: every endpoint requires at least the ``registered``
tier; rule counts are tier-capped (registered ≤ 2, subscriber/professional
≤ 25, business/municipality/government ≤ 100) with a 403 ``upgrade``
descriptor at the cap. Organisation seats and programmatic API access for
business/government tiers are roadmap items, not exposed here. Per-user
isolation is enforced in every query (IDOR-safe); verification codes are
delivered only via SMS and never appear in responses.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from . import sms as sms_module
from .auth_api import _err, _rate, _tier_rate, require_role
from .notify_store import NotifyStore

sms_bp = Blueprint("sms_alerts", __name__, url_prefix="/api/v2")

# Tier caps for alert rules (progressive access; no pricing here).
RULE_CAPS = {
    "registered": 2,
    "subscriber": 25,
    "professional": 25,
    "business": 100,
    "municipality": 100,
    "government": 100,
    "admin": 100,
}

_NEXT_TIER = {
    "registered": "subscriber",
    "subscriber": "business",
    "professional": "business",
    "business": "government",
    "municipality": "government",
}


def _registered_hazards():
    from ..climate import registry

    return registry.ids()


# ---------------------------------------------------------------------------
# Phone number + verification
# ---------------------------------------------------------------------------

@sms_bp.post("/alerts/phone")
@require_role("registered")
def add_phone():
    user = g.current_user
    if not _rate("v2sms_phone", 10, 3600.0):
        return _err("Rate limit exceeded (10 requests/hour)", 429)
    data = request.get_json(silent=True) or {}
    phone = sms_module.normalize_e164(data.get("phone") or "")
    if not sms_module.valid_e164(phone):
        return _err("A valid E.164 phone number is required (e.g. +306912345678)", 400)
    store = NotifyStore()
    result = store.upsert_phone(user["id"], phone)
    if "error" in result:
        return _err(result["error"], 409)
    # The code is delivered via SMS only (dev: outbox file) — never in the
    # API response.
    delivery = sms_module.send_sms(
        phone,
        f"Talaix verification code: {result['code']}\n"
        "It expires in 10 minutes.\ntalaix.com",
    )
    return jsonify({
        "status": "verification_sent",
        "phone": result["phone"],
        "delivery_backend": delivery.get("backend"),
    }), 201


@sms_bp.post("/alerts/phone/verify")
@require_role("registered")
def verify_phone():
    user = g.current_user
    if not _rate("v2sms_verify", 10, 3600.0):
        return _err("Rate limit exceeded (10 requests/hour)", 429)
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "").strip()
    store = NotifyStore()
    result = store.verify_phone(user["id"], code)
    if "error" in result:
        return _err(result["error"], 400)
    # Default after verification: SMS on (prefs may be changed afterwards).
    store.update_prefs(user["id"], sms_enabled=True)
    return jsonify({"status": "verified", "phone": result["phone"],
                    "prefs": store.get_prefs(user["id"])})


@sms_bp.delete("/alerts/phone")
@require_role("registered")
def delete_phone():
    user = g.current_user
    store = NotifyStore()
    if store.delete_phone(user["id"]):
        store.update_prefs(user["id"], sms_enabled=False)
        return jsonify({"deleted": True})
    return _err("Phone number not found", 404)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@sms_bp.get("/alerts/preferences")
@require_role("registered")
def get_preferences():
    store = NotifyStore()
    prefs = store.get_prefs(g.current_user["id"])
    phone = store.get_phone(g.current_user["id"])
    # Honest delivery state: the UI shows whether a real SMS provider is
    # configured (True) or messages go to the safe dev outbox (False).
    return jsonify({
        "prefs": prefs,
        "phone": phone,
        "sms_delivery": {
            "provider_configured": sms_module.sms_configured(),
            "note": (
                "Real SMS delivery is active."
                if sms_module.sms_configured()
                else "No SMS provider is configured — messages are written to "
                     "the operator outbox, not delivered."
            ),
        },
    })


@sms_bp.patch("/alerts/preferences")
@require_role("registered")
def update_preferences():
    user = g.current_user
    if not _tier_rate(user, "v2sms_prefs"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    if not data:
        return _err("Nothing to update", 400)
    unknown = set(data) - {"sms_enabled", "email_enabled", "quiet_hours",
                           "language", "max_per_day"}
    if unknown:
        return _err(f"Unknown preference field(s): {', '.join(sorted(unknown))}", 400)
    kwargs = {}
    if "sms_enabled" in data:
        kwargs["sms_enabled"] = bool(data["sms_enabled"])
    if "email_enabled" in data:
        kwargs["email_enabled"] = bool(data["email_enabled"])
    if "quiet_hours" in data:
        quiet = data["quiet_hours"]
        if quiet is not None and not isinstance(quiet, dict):
            return _err("quiet_hours must be {'start','end'} (HH:MM UTC) or null", 400)
        kwargs["quiet_hours"] = quiet
    if "language" in data:
        kwargs["language"] = data["language"]
    if "max_per_day" in data:
        kwargs["max_per_day"] = data["max_per_day"]
    result = NotifyStore().update_prefs(user["id"], **kwargs)
    if "error" in result:
        return _err(result["error"], 400)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Alert rules (tier-capped)
# ---------------------------------------------------------------------------

@sms_bp.get("/alerts/rules")
@require_role("registered")
def list_rules():
    return jsonify({"rules": NotifyStore().list_rules(g.current_user["id"])})


@sms_bp.post("/alerts/rules")
@require_role("registered")
def add_rule():
    user = g.current_user
    if not _tier_rate(user, "v2sms_rules"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    hazard = (data.get("hazard") or "").strip().lower()
    if hazard not in _registered_hazards():
        return _err(
            f"Unknown hazard (registered: {', '.join(_registered_hazards())})", 400)
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return _err("lat and lon must be numbers", 400)
    threshold = (data.get("severity_threshold") or "HIGH").strip().upper()

    store = NotifyStore()
    cap = RULE_CAPS.get(user["role"], RULE_CAPS["registered"])
    if len(store.list_rules(user["id"])) >= cap:
        nxt = _NEXT_TIER.get(user["role"], "business")
        return _err(
            f"Alert-rule limit reached for your tier ({cap})",
            403,
            upgrade={
                "required_role": nxt,
                "your_role": user["role"],
                "unlocks": f"Upgrading to '{nxt}' raises the alert-rule limit.",
            },
        )
    result = store.add_rule(
        user["id"], hazard, lat, lon,
        name=data.get("name"), severity_threshold=threshold)
    if "error" in result:
        return _err(result["error"], 400)
    return jsonify(result), 201


@sms_bp.delete("/alerts/rules/<int:rule_id>")
@require_role("registered")
def delete_rule(rule_id: int):
    if NotifyStore().delete_rule(g.current_user["id"], rule_id):
        return jsonify({"deleted": True})
    return _err("Alert rule not found", 404)


# ---------------------------------------------------------------------------
# History + unsubscribe
# ---------------------------------------------------------------------------

@sms_bp.get("/alerts/history")
@require_role("registered")
def alert_history():
    store = NotifyStore()
    return jsonify({"alerts": store.list_history(g.current_user["id"], limit=50)})


@sms_bp.post("/alerts/unsubscribe")
@require_role("registered")
def unsubscribe():
    """Explicit SMS opt-out: disables sms_enabled; ?rules=1 also deletes
    the user's alert rules. Authenticated, audited."""
    user = g.current_user
    store = NotifyStore()
    store.update_prefs(user["id"], sms_enabled=False)
    deleted = 0
    if request.args.get("rules") == "1":
        deleted = store.delete_rules_for_user(user["id"])
    store.audit(user["id"], "alert_unsubscribe", target="self",
                meta={"rules_deleted": deleted})
    return jsonify({"status": "unsubscribed", "sms_enabled": False,
                    "rules_deleted": deleted})

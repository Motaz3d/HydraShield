"""
Hunter.io email-discovery integration.

Lightweight stdlib-only wrapper around the Hunter.io domain-search API.
The API key is read from the environment only; it is never logged or
embedded in error messages.

On HTTP 429 (free-plan quota exhausted) the operator is emailed once per
quota episode (send_plan §7.2); the alert re-arms when calls succeed
again and never breaks the lookup path.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse


class HunterError(Exception):
    """User-safe error from the Hunter.io integration."""


def configured() -> bool:
    """True when a Hunter.io API key is present in the environment."""
    return bool(os.environ.get("HUNTER_API_KEY"))


# ---------------------------------------------------------------------------
# Quota guard — operator alert on free-plan exhaustion (send_plan §7.2)
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _guard_path() -> str:
    return os.environ.get(
        "HUNTER_QUOTA_GUARD_FILE",
        os.path.join(_ROOT, "data", "hunter_quota_guard.json"),
    )


def _load_guard() -> Dict:
    try:
        with open(_guard_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"notified": False}


def _save_guard(state: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(_guard_path()), exist_ok=True)
        with open(_guard_path(), "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    except OSError:
        pass


def _note_quota_success() -> None:
    """Re-arm the quota alert after a successful call (monthly reset or
    plan upgrade)."""
    state = _load_guard()
    if state.get("notified"):
        state["notified"] = False
        _save_guard(state)


def _maybe_alert_quota() -> None:
    """Email the operator once per quota episode. Alerting must never
    break the Hunter call path."""
    state = _load_guard()
    if state.get("notified"):
        return
    try:
        from . import mailer
        mailer.operator_notify(
            "Hunter.io quota exhausted — paid-plan decision needed",
            "The Hunter.io verification layer hit the free-plan quota "
            "(API returned 429, quota exhausted).\n\n"
            "Impact: address verification is unavailable until the monthly "
            "quota resets (start of next month) or a paid plan is adopted. "
            "Sending continues; bounced addresses are still marked invalid "
            "automatically and skipped by wave selection.\n\n"
            "Agreed action (marketing/strategy/send_plan_2026-09.md §7.2): "
            "the operator decides on any paid subscription — nothing is "
            "purchased automatically. If sends can wait for the monthly "
            "reset, no action is needed.\n\n"
            "This alert fires once per quota episode and re-arms when "
            "calls succeed again.",
            kind="hunter_quota",
        )
    except Exception:
        return
    state["notified"] = True
    _save_guard(state)


def domain_from_url(url: str) -> Optional[str]:
    """Extract a bare, lower-case domain from a URL (or plain domain).

    Strips the scheme, ``www.`` prefix, path, query and port. Returns
    ``None`` when no usable domain can be extracted.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None

    parsed = urlparse(url)
    netloc = parsed.netloc
    if not netloc:
        # The caller may have passed a bare domain; retry with a scheme.
        parsed = urlparse("https://" + url)
        netloc = parsed.netloc
    if not netloc:
        return None

    # Drop port.
    netloc = netloc.split(":", 1)[0]
    # Drop www. prefix.
    if netloc.lower().startswith("www."):
        netloc = netloc[4:]
    if not netloc or "." not in netloc:
        return None
    return netloc.lower()


def domain_search(domain: str, limit: int = 10) -> List[Dict]:
    """Search Hunter.io for emails on ``domain``.

    Returns a list of normalized contact dicts::

        [{"email", "name", "position", "department", "confidence"}]

    Raises :class:`HunterError` with an honest, key-free message on failure.
    """
    api_key = os.environ.get("HUNTER_API_KEY")
    if not api_key:
        raise HunterError("Hunter.io is not configured")

    url = (
        "https://api.hunter.io/v2/domain-search"
        f"?domain={quote(domain, safe='')}&limit={int(limit)}&api_key={api_key}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        _note_quota_success()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HunterError("invalid API key")
        if exc.code == 429:
            _maybe_alert_quota()
            raise HunterError("Hunter.io quota exhausted")
        raise HunterError(f"Hunter.io lookup failed: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc.reason}")
    except Exception as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc}")

    emails = (payload.get("data") or {}).get("emails") or []
    out: List[Dict] = []
    for entry in emails:
        first = str(entry.get("first_name") or "").strip()
        last = str(entry.get("last_name") or "").strip()
        name = f"{first} {last}".strip()
        confidence = entry.get("confidence")
        if confidence is not None:
            try:
                confidence = int(confidence)
            except (TypeError, ValueError):
                confidence = None
        out.append({
            "email": entry.get("value"),
            "name": name,
            "position": entry.get("position"),
            "department": entry.get("department"),
            "confidence": confidence,
        })
    return out


def email_finder(domain: str, first_name: str, last_name: str) -> Optional[Dict]:
    """Find a single email address on ``domain`` given a name.

    Returns a contact dict::

        {"email", "score", "sources", "verification"}

    Returns ``None`` when Hunter has no result for the name/domain.
    Raises :class:`HunterError` on API failure.
    """
    api_key = os.environ.get("HUNTER_API_KEY")
    if not api_key:
        raise HunterError("Hunter.io is not configured")

    first = str(first_name or "").strip()
    last = str(last_name or "").strip()
    if not first or not last:
        raise HunterError("first_name and last_name are required")

    url = (
        "https://api.hunter.io/v2/email-finder"
        f"?domain={quote(domain, safe='')}"
        f"&first_name={quote(first)}"
        f"&last_name={quote(last)}"
        f"&api_key={api_key}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        _note_quota_success()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (401, 403):
            raise HunterError("invalid API key")
        if exc.code == 429:
            _maybe_alert_quota()
            raise HunterError("Hunter.io quota exhausted")
        raise HunterError(f"Hunter.io lookup failed: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc.reason}")
    except Exception as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc}")

    data = payload.get("data") or {}
    email = data.get("email")
    if not email:
        return None

    verification = data.get("verification") or {}
    return {
        "email": email,
        "score": data.get("score"),
        "sources": data.get("sources") or [],
        "verification": verification.get("status") or verification.get("result"),
    }


def verify_email(email: str) -> Dict:
    """Verify an email address with Hunter.io.

    Returns a dict::

        {"email", "score", "status", "result"}

    Raises :class:`HunterError` on API failure.
    """
    api_key = os.environ.get("HUNTER_API_KEY")
    if not api_key:
        raise HunterError("Hunter.io is not configured")

    if not email or "@" not in email:
        raise HunterError("valid email is required")

    url = (
        "https://api.hunter.io/v2/email-verifier"
        f"?email={quote(email, safe='')}&api_key={api_key}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        _note_quota_success()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HunterError("invalid API key")
        if exc.code == 429:
            _maybe_alert_quota()
            raise HunterError("Hunter.io quota exhausted")
        raise HunterError(f"Hunter.io lookup failed: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc.reason}")
    except Exception as exc:
        raise HunterError(f"Hunter.io lookup failed: {exc}")

    data = payload.get("data") or {}
    return {
        "email": data.get("email") or email,
        "score": data.get("score"),
        "status": data.get("status"),
        "result": data.get("result"),
    }

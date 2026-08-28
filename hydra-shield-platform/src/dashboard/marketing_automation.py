"""
Talaix marketing automation — automatic follow-up flows on top of the CRM.

Two flows, built on the existing machinery (never a parallel send path):

1. **New-contact follow-up** (opt-in via ``AUTO_OUTREACH_ON_CONTACT=1``):
   when contacts are imported or discovered for a lead, one *scheduled*
   outreach email is queued per new contact. Sending stays with the cron
   processor (``scripts/process_scheduled_outreach.py``), so the daily cap,
   the unsubscribe list and duplicate protection are all enforced at send
   time exactly as for operator-queued mail.

2. **Registration match** (always on): when a newly verified account's
   email domain matches a lead's website domain, the signal is recorded on
   the lead, pending scheduled outreach for that lead is auto-cancelled
   (someone from the organisation is already inside), and the operator is
   notified.

Honesty rules are inherited unchanged: no email is ever sent to an
unsubscribed or excluded lead, and every automated action leaves an
interaction record saying what happened and why.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import mailer
from .marketing_store import MarketingStore

# Domains that can never identify an organisation (same rule the email
# discovery engine applies).
FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
    "live.com", "msn.com", "yandex.com", "zoho.com",
})

_HOST_RE = re.compile(r"^https?://", re.I)


def auto_outreach_enabled() -> bool:
    """New-contact auto follow-up is on only when explicitly enabled."""
    return os.environ.get("AUTO_OUTREACH_ON_CONTACT", "").strip().lower() in ("1", "true", "yes")


def queue_outreach_for_new_contacts(
    store: MarketingStore,
    lead_slug: str,
    contacts: List[Dict],
    delay_minutes: int = 0,
) -> int:
    """Queue one scheduled outreach email per new contact for ``lead_slug``.

    Respects the enabled flag, exclusions and the unsubscribe list, and
    skips addresses that already have a pending scheduled row. Returns the
    number of rows queued.
    """
    if not auto_outreach_enabled() or not contacts:
        return 0
    from .marketing_crm import _leads_by_slug, _outreach_template_and_context

    lead = _leads_by_slug().get(lead_slug)
    if lead is None or lead.get("excluded") or store.is_unsubscribed(lead_slug):
        return 0

    pending = {
        r["to_email"]
        for r in store.list_scheduled(lead_slug=lead_slug, status="scheduled")
    }
    send_at = (datetime.utcnow() + timedelta(minutes=delay_minutes)).isoformat()[:19]
    queued = 0
    for contact in contacts:
        email = (contact.get("email") or "").strip().lower()
        if not email or email in pending:
            continue
        template, context = _outreach_template_and_context(
            lead, {"contact_name": contact.get("name") or ""})
        row = store.schedule_send(
            lead_slug=lead_slug,
            to_email=email,
            contact_name=context.get("contact_name") or None,
            template=template,
            context=context,
            send_at=send_at,
        )
        if row:
            pending.add(email)
            queued += 1
    if queued:
        store.add_interaction(
            lead_slug,
            summary=f"Auto-queued outreach to {queued} new contact(s) "
                    f"(AUTO_OUTREACH_ON_CONTACT).",
            type="note",
        )
    return queued


def _site_host(website: str) -> str:
    host = _HOST_RE.sub("", (website or "").strip().lower())
    host = host.split("/")[0].strip()
    return host[4:] if host.startswith("www.") else host


def match_registration_to_leads(email: str) -> List[Dict]:
    """Leads whose website domain matches the registrant's email domain.

    Free-mail addresses never match — they identify no organisation.
    """
    domain = (email or "").rsplit("@", 1)[-1].strip().lower()
    if not domain or domain in FREE_MAIL_DOMAINS:
        return []
    from .marketing_crm import _all_leads

    matches = []
    for lead in _all_leads():
        host = _site_host(lead.get("website") or "")
        if host and (domain == host or domain.endswith("." + host)
                     or host.endswith("." + domain)):
            matches.append(lead)
    return matches


def handle_registration(user_email: str) -> List[str]:
    """Record a platform registration against matching leads.

    For every matched lead: log a ``registered`` interaction, auto-cancel
    pending scheduled outreach, and notify the operator. Returns the slugs
    of matched leads (empty when there is no match). Raises nothing on
    unknown leads; caller wraps for absolute safety.
    """
    store = MarketingStore()
    matched_slugs: List[str] = []
    for lead in match_registration_to_leads(user_email):
        slug = lead.get("_slug")
        if not slug:
            continue
        matched_slugs.append(slug)
        cancelled = store.cancel_scheduled_for_lead(slug)
        waves = store.cancel_waves_for_lead(slug)
        store.add_interaction(
            slug,
            summary=(
                f"Someone from this organisation registered on the platform "
                f"({user_email}). Auto-cancelled {cancelled} scheduled outreach "
                f"row(s) and {waves} campaign wave(s)."
            ),
            type="registered",
        )
        mailer.operator_notify(
            "Lead registered on the platform",
            f"Organisation: {lead.get('organization') or slug}\n"
            f"Lead: {slug}\n"
            f"Registered email: {user_email}\n"
            f"Segment: {lead.get('segment') or 'unknown'} · Country: {lead.get('country') or '—'}\n"
            f"Scheduled outreach auto-cancelled: {cancelled}\n"
            f"Campaign waves auto-cancelled: {waves}",
            kind="lead_registered",
        )
    return matched_slugs

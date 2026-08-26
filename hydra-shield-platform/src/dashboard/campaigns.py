"""Shared campaign-wave selection and enqueue logic.

Used by scripts/run_campaign.py and the /api/v2/admin/marketing/campaigns/start
endpoint. The helper is intentionally free of Flask request state so it can run
from cron scripts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .admin_intel import _WORKSPACE, _records_ws
from .marketing_store import MarketingStore
from .marketing_crm import _lead_category, _outreach_template_and_context


ALLOWED_TEMPLATES = {"followup_1", "followup_2"}


def _load_leads() -> List[Dict]:
    return _records_ws("leads")


def _leads_by_slug(leads: List[Dict]) -> Dict[str, Dict]:
    return {l.get("_slug"): l for l in leads if l.get("_slug")}


def _matches_filters(lead: Dict, filters: Dict[str, str]) -> bool:
    segment = filters.get("segment")
    country = filters.get("country")
    if segment and _lead_category(lead) != segment:
        return False
    if country and (lead.get("country") or "") != country:
        return False
    return True


def _has_pending_or_sent_wave(store: MarketingStore, campaign: str, lead_slug: str, wave: int) -> bool:
    existing = store.pending_waves(campaign=campaign)
    for row in existing:
        if row["lead_slug"] == lead_slug and row["wave"] == wave and row["status"] in ("pending", "sent"):
            return True
    return False


def select_campaign_leads(
    leads: List[Dict],
    store: MarketingStore,
    campaign: str,
    wave: int,
    filters: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Return leads eligible for a campaign wave.

    Eligibility:
      - not excluded
      - has at least one stored contact
      - not unsubscribed
      - outreach_status in (researched, qualified, contacted)
      - matches optional segment/country filters
      - no pending or sent wave of the same number for this campaign
    """
    filters = filters or {}
    eligible_statuses = {"researched", "qualified", "contacted"}
    selected: List[Dict] = []

    for lead in leads:
        if lead.get("excluded"):
            continue
        slug = lead.get("_slug")
        if not slug:
            continue
        if not _matches_filters(lead, filters):
            continue
        if not store.list_contacts(slug):
            continue
        if store.is_unsubscribed(slug):
            continue
        status = lead.get("outreach_status", "researched")
        if status not in eligible_statuses:
            continue
        if _has_pending_or_sent_wave(store, campaign, slug, wave):
            continue
        selected.append(lead)

    return selected


def build_wave_context(lead: Dict, contact: Dict) -> Dict:
    """Build a render context for a follow-up template."""
    template, context = _outreach_template_and_context(lead, {
        "contact_name": contact.get("name") or "there",
        "custom_message": "",
    })
    return context


def enqueue_campaign_wave(
    campaign: str,
    wave: int,
    template: str,
    leads: List[Dict],
    store: Optional[MarketingStore] = None,
    delay_days: float = 0.0,
) -> Dict:
    """Enqueue a campaign wave for the selected leads.

    send_at is staggered in small increments so the daily cap drains them
    naturally over time. Returns summary counts and the list of enqueued slugs.
    """
    if template not in ALLOWED_TEMPLATES:
        raise ValueError(f"Template must be one of {ALLOWED_TEMPLATES}")

    store = store or MarketingStore()
    now = datetime.utcnow()
    base_send_at = now + timedelta(days=delay_days)
    stagger_minutes = 5.0

    enqueued: List[str] = []
    skipped = 0

    for idx, lead in enumerate(leads):
        slug = lead.get("_slug")
        if not slug:
            skipped += 1
            continue
        contacts = store.list_contacts(slug)
        if not contacts:
            skipped += 1
            continue
        contact = contacts[0]
        context = build_wave_context(lead, contact)
        send_at = (base_send_at + timedelta(minutes=idx * stagger_minutes)).isoformat()[:19]
        row = store.enqueue_wave(
            campaign=campaign,
            lead_slug=slug,
            wave=wave,
            template=template,
            context=context,
            send_at=send_at,
        )
        if row:
            enqueued.append(slug)
        else:
            skipped += 1

    return {
        "campaign": campaign,
        "wave": wave,
        "template": template,
        "enqueued": len(enqueued),
        "skipped": skipped,
        "leads": enqueued,
    }


def start_campaign(
    campaign: str,
    wave: int,
    template: str,
    filters: Optional[Dict[str, str]] = None,
    delay_days: float = 0.0,
    store: Optional[MarketingStore] = None,
) -> Dict:
    """Select leads and enqueue a campaign wave."""
    store = store or MarketingStore()
    leads = _load_leads()
    selected = select_campaign_leads(leads, store, campaign, wave, filters)
    return enqueue_campaign_wave(
        campaign=campaign,
        wave=wave,
        template=template,
        leads=selected,
        store=store,
        delay_days=delay_days,
    )

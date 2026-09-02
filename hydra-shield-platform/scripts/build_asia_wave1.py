#!/usr/bin/env python3
"""Build the Asia+Brazil investment/consulting outreach wave (wave 1).

Reads marketing leads in the target geographies (SG, HK, JP, KR, CN, TW,
IN, BR) and target segments (investment first, then consultants /
environmental_consulting, then banking and insurance), picks the best
stored contact per lead and renders the sector outreach template into a
reviewable wave:

    marketing/outreach/asia_investment_wave1.json  — machine-readable wave
    marketing/outreach/asia_investment_wave1.md    — human review document

HARD RULES (aligned with scripts/outreach_composer.py):

- This script never sends anything and touches no network. Sending is a
  separate, explicit, human-approved step (scripts/send_asia_wave1.py).
- Only OBSERVED contacts enter the sendable wave. INFERRED contacts are
  listed in the review document under "needs human verification" and are
  never written to the JSON wave.
- Leads without any stored contact are listed as "contact gap" so the
  operator sees the remaining manual-search workload (Brazil especially).
- No invented personalisation: the rendered context uses only the lead's
  recorded fields (organization, identified_problem,
  relevant_capability), exactly as the CRM does.

Usage (from the platform directory):

    .venv/bin/python scripts/build_asia_wave1.py [--limit N]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard import mailer  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

LEADS_DIR = os.path.join(ROOT, "marketing", "leads")
OUT_JSON = os.path.join(ROOT, "marketing", "outreach", "asia_investment_wave1.json")
OUT_MD = os.path.join(ROOT, "marketing", "outreach", "asia_investment_wave1.md")

COUNTRY_RANK = ["SG", "HK", "JP", "KR", "CN", "TW", "IN", "BR"]
SEGMENT_TIERS = [
    ("investment", "outreach_investment"),
    ("environmental_consulting", "outreach_environmental_consulting"),
    ("consultants", "outreach_environmental_consulting"),
    ("banking", "outreach_banking"),
    ("insurance", "outreach_insurance"),
]
TIER_OF = {seg: i for i, (seg, _tmpl) in enumerate(SEGMENT_TIERS)}
TEMPLATE_OF = dict(SEGMENT_TIERS)

COUNTRY_NAMES = {
    "SG": "Singapore", "HK": "Hong Kong", "JP": "Japan", "KR": "South Korea",
    "CN": "China", "TW": "Taiwan", "IN": "India", "BR": "Brazil",
}

# Recruitment inboxes are never a commercial outreach target — a sales
# message to hr@/jobs@ is spam to the wrong department. Same for
# security/abuse desks (phishing@, fraud@, ...). Leads whose only
# address is one of these fall through to the contact-gap list.
RECRUITMENT_LOCALPARTS = {
    "hr", "jobs", "job", "careers", "career", "recruitment", "recruit",
    "askhr", "talent", "hiring",
    "phishing", "abuse", "fraud", "security", "infosec", "soc", "cert",
    "incident", "spam",
}

# Leads excluded from the wave with a documented reason (reviewed
# 2026-09-02). The stored contact stays in the CRM as an honest record;
# it is simply not a valid outreach target.
EXCLUDED_SLUGS = {
    # info@fsk.or.jp belongs to the umbrella domain hosting the firm's
    # profile page, not to the firm itself.
    "you-architect": "published address belongs to host umbrella domain fsk.or.jp, not the firm",
}


def _is_recruitment(address: str) -> bool:
    local = (address or "").split("@", 1)[0].lower()
    local = re.split(r"[._+\-]", local)[0] if local else ""
    return local in RECRUITMENT_LOCALPARTS


def _iter_target_leads() -> List[Dict]:
    leads = []
    for path in sorted(glob.glob(os.path.join(LEADS_DIR, "*.json"))):
        if path.endswith("schema.json"):
            continue
        try:
            lead = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (lead.get("country") or "") not in COUNTRY_RANK:
            continue
        if (lead.get("segment") or "") not in TIER_OF:
            continue
        lead["_slug"] = Path(path).stem
        leads.append(lead)
    leads.sort(key=lambda l: (
        TIER_OF[l["segment"]],
        COUNTRY_RANK.index(l["country"]),
        (l.get("organization") or "").lower(),
    ))
    return leads


def _best_contact(contacts: List[Dict], observed_only: bool = True) -> Optional[Dict]:
    pool = [
        c for c in contacts
        if c.get("email")
        and not _is_recruitment(c["email"])
        and (
            not observed_only
            or (c.get("verification") or "").upper() == "OBSERVED"
        )
    ]
    if not pool:
        return None
    pool.sort(key=lambda c: -(c.get("confidence") or 0))
    return pool[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="cap the number of sendable entries (default: no cap)")
    args = parser.parse_args()

    mailer.load_dotenv(os.path.join(ROOT, ".env"))
    mailer.load_dotenv(os.path.join(os.path.dirname(ROOT), ".env"))

    store = MarketingStore()
    followup = (date.today() + timedelta(days=7)).isoformat()

    entries: List[Dict] = []
    inferred_only: List[Dict] = []
    contact_gap: List[Dict] = []

    for lead in _iter_target_leads():
        slug = lead["_slug"]
        if slug in EXCLUDED_SLUGS:
            continue
        if store.is_unsubscribed(slug):
            continue
        state = store.get_state(slug) or {}
        if state.get("outreach_status") in ("replied", "contacted"):
            continue
        contacts = store.list_contacts(slug)
        observed = _best_contact(contacts, observed_only=True)
        template = TEMPLATE_OF[lead["segment"]]
        if observed:
            context = {
                "contact_name": "there",
                "organization": lead.get("organization") or "",
                "country": lead.get("country") or "",
                "identified_problem": lead.get("identified_problem") or "",
                "relevant_capability": lead.get("relevant_capability") or "",
                "recommended_product": lead.get("recommended_product") or "",
                "custom_message": "",
                "unsubscribe_url": mailer.unsubscribe_mailto(),
            }
            rendered = mailer.render_template(template, context)
            entries.append({
                "slug": slug,
                "org": lead.get("organization") or "",
                "email": observed["email"],
                "template": template,
                "segment": lead.get("segment") or "",
                "country": lead.get("country") or "",
                "contact_confidence": observed.get("confidence"),
                "contact_source": observed.get("source"),
                "followup_date": followup,
                "subject": rendered["subject"],
                "body": rendered["text"],
            })
            continue
        any_contact = _best_contact(contacts, observed_only=False)
        row = {
            "slug": slug,
            "org": lead.get("organization") or "",
            "segment": lead.get("segment") or "",
            "country": lead.get("country") or "",
            "website": lead.get("website") or "",
        }
        if any_contact:
            row["inferred_email"] = any_contact["email"]
            inferred_only.append(row)
        else:
            contact_gap.append(row)

    if args.limit and len(entries) > args.limit:
        entries = entries[: args.limit]

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    lines: List[str] = []
    lines.append("# Talaix — Asia + Brazil Investment/Consulting Outreach Wave 1")
    lines.append("")
    lines.append("> حالة الموجة: مسودات جاهزة للمراجعة البشرية. لا شيء أُرسل بعد.")
    lines.append("> Human gate: كل رسالة تُراجع وتُرسل يدوياً من Vultr عبر")
    lines.append("> `scripts/send_asia_wave1.py` (وضع الجفاف افتراضياً؛ `--send` للإرسال).")
    lines.append("")
    lines.append("## قاعدة التصفية (binding)")
    lines.append("")
    lines.append("- التوزيع: 100% من هذه الموجة لآسيا والبرازيل — تنفيذاً لخطة")
    lines.append("  الإرسال 2026-09 (نصف الرسائل على الأقل لهذه المناطق).")
    lines.append("- القطاعات بالترتيب: investment ثم consultants ثم banking/insurance.")
    lines.append("- المراكز المالية بالترتيب: سنغافورة، هونغ كونغ، طوكيو، سول،")
    lines.append("  الصين، تايبيه، مومباي/الهند، ساو باولو/البرازيل.")
    lines.append("- جهات الاتصال OBSERVED فقط تدخل الموجة؛ العناوين INFERRED")
    lines.append("  مدرجة للتحقق البشري ولا تُرسل قبل التحقق.")
    lines.append("- اللغة الإنجليزية؛ قوالب القطاع من")
    lines.append("  `src/dashboard/email_templates/outreach_*.txt`.")
    lines.append(f"- تاريخ المتابعة المقترح لكل رسالة: {followup}.")
    lines.append("")
    lines.append(f"## ملخص: {len(entries)} رسالة قابلة للإرسال | "
                 f"{len(inferred_only)} عنوان INFERRED للتحقق | "
                 f"{len(contact_gap)} عميل بلا جهة اتصال (فجوة بحث يدوي)")
    lines.append("")
    for i, e in enumerate(entries, 1):
        lines.append(f"## {i}. {e['org']} — {COUNTRY_NAMES.get(e['country'], e['country'])}"
                     f" ({e['segment']})")
        lines.append("")
        lines.append(f"- slug: `{e['slug']}`")
        lines.append(f"- البريد: {e['email']} (OBSERVED، ثقة {e.get('contact_confidence') or '—'}،"
                     f" المصدر: {e.get('contact_source') or '—'})")
        lines.append(f"- القالب: `{e['template']}`")
        lines.append("")
        lines.append(f"**Subject:** {e['subject']}")
        lines.append("")
        lines.append("```")
        lines.append(e["body"].rstrip())
        lines.append("```")
        lines.append("")
    if inferred_only:
        lines.append("## عناوين INFERRED — تحقق بشري مطلوب قبل أي إرسال")
        lines.append("")
        for r in inferred_only:
            lines.append(f"- {r['org']} ({r['country']}, {r['segment']}): "
                         f"{r['inferred_email']} — {r['website']}")
        lines.append("")
    if contact_gap:
        lines.append("## فجوة جهات الاتصال — بحث يدوي (البرازيل أولوية)")
        lines.append("")
        for r in contact_gap:
            lines.append(f"- {r['org']} ({r['country']}, {r['segment']}) — {r['website']}")
        lines.append("")
    lines.append("---")
    lines.append(f"آخر تحديث: {date.today().isoformat()}. الحالة: draft للمراجعة —"
                 " لم تُرسل أي رسالة.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Wave written: {OUT_JSON} ({len(entries)} entries)")
    print(f"Review doc:   {OUT_MD}")
    print(f"Inferred-only (verify before send): {len(inferred_only)}")
    print(f"Contact gap (manual search): {len(contact_gap)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

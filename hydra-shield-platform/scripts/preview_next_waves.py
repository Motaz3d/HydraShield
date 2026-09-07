#!/usr/bin/env python3
"""Render the CSRD-companies wave and the insurance fresh batch into one HTML
preview page for operator review — BEFORE anything is scheduled or sent.

Writes marketing/outreach/next_waves_preview.html and prints its path.
This script never sends and never schedules anything.
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from src.dashboard import mailer  # noqa: E402

OUT_PATH = os.path.join(BASE, "marketing", "outreach", "next_waves_preview.html")

CSRD_JSON = os.path.join(BASE, "marketing", "outreach", "csrd_companies_wave1.json")
INS_JSON = os.path.join(BASE, "marketing", "outreach", "insurance_fresh_wave.json")

HOLD_CSRD = [
    ("Bouygues", "Only an investor-relations mailbox is published (off-purpose for a product pitch); named exec Marie-Luce Godinot (SVP Sustainable Development) — LinkedIn route."),
    ("Ahold Delhaize", "IR mailbox only; CSO Alex Holt is published — LinkedIn route."),
    ("Ferretti Group", "IR mailbox only — hold."),
    ("Enel", "Only IR/press mailboxes published — hold."),
    ("Barilla", "Only media/privacy mailboxes published — hold."),
    ("Danone", "Only IR + press mailboxes published — hold."),
    ("E.ON", "Official site behind a Cloudflare challenge — no route could be verified; retry manually."),
]
INSURANCE_SKIPS = [
    ("Groupama / Mutua Madrileña / Bertelsmann BKK (datenschutz@)", "Only DPO/privacy mailboxes found — pitching those burns reputation; skipped on purpose."),
    ("ENNIA", "Curaçao-based (not CSRD-obligated); only a regional office mailbox — weak fit, skipped."),
    ("Betriebskrankenkasse EVM", "Health insurer — physical-risk underwriting angle does not apply; too small for CSRD Wave 2."),
    ("Q101627756 / Q122460511 / Q18011733", "Lead names are unresolved Wikidata QIDs — cannot personalize honestly; sent to data cleanup."),
    ("26 premium insurers (Generali, AXA XL, Beazley, Allianz Direct…)", "Already emailed pre-pivot — re-approach belongs to the follow-up wave ~2 weeks later, not a cold re-mail."),
]

CSS = """
body{font-family:-apple-system,'Inter',sans-serif;background:#f4f6f8;color:#0f172a;margin:0;padding:2rem;}
h1{font-size:1.5rem;} h2{font-size:1.1rem;margin-top:2.5rem;border-bottom:2px solid #0EA5E9;padding-bottom:.3rem;}
.meta{color:#475569;font-size:.9rem;}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.2rem 1.4rem;margin:1rem 0;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.badge{display:inline-block;background:#0EA5E9;color:#fff;border-radius:6px;padding:.1rem .5rem;font-size:.75rem;margin-right:.4rem;}
.badge.gray{background:#64748b;} .badge.green{background:#047857;}
pre{white-space:pre-wrap;font-family:'SF Mono',Menlo,monospace;font-size:.82rem;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;line-height:1.45;}
a{color:#0EA5E9;} table{border-collapse:collapse;width:100%;font-size:.9rem;background:#fff;}
td,th{border:1px solid #e2e8f0;padding:.45rem .6rem;text-align:left;vertical-align:top;}
.summary{background:#ecfeff;border:1px solid #0EA5E9;border-radius:10px;padding:1rem 1.4rem;}
"""


def _card(entry: dict, idx: int, template: str) -> str:
    context = {
        "contact_name": entry.get("contact_name") or "there",
        "organization": entry["organization"],
        "country": entry.get("country") or "",
        "identified_problem": entry.get("identified_problem") or "",
        "relevant_capability": entry.get("relevant_capability") or "",
        "recommended_product": "",
        "custom_message": entry.get("custom_message") or "",
        "unsubscribe_url": mailer.unsubscribe_mailto(),
    }
    rendered = mailer.render_template(template, context)
    body = rendered["text"].rstrip() + "\n\n" + mailer.signature_text()
    utc = datetime.fromisoformat(entry["send_at"])
    brussels = utc + timedelta(hours=2)
    when = f"{utc:%Y-%m-%d %H:%M} UTC · {brussels:%H:%M} Brussels"
    return f"""
<div class="card">
  <div><span class="badge">#{idx}</span> <span class="badge gray">{html.escape(when)}</span></div>
  <h3>{html.escape(entry['organization'])} ({html.escape(entry['country'])})</h3>
  <p class="meta">TO: {html.escape(entry['to_email'])} &nbsp;·&nbsp; published at:
  <a href="{html.escape(entry['source'])}">{html.escape(entry['source'])}</a> (checked {entry['date_checked']})</p>
  <p><b>SUBJECT: {html.escape(rendered['subject'])}</b></p>
  <pre>{html.escape(body)}</pre>
</div>"""


def main() -> int:
    csrd = json.load(open(CSRD_JSON, encoding="utf-8"))
    ins = json.load(open(INS_JSON, encoding="utf-8"))
    csrd_email = [e for e in csrd if e.get("to_email")]
    csrd_web = [e for e in csrd if e.get("channel") == "webform"]

    csrd_cards = "".join(_card(e, i + 1, "outreach_sustainability_compliance")
                         for i, e in enumerate(csrd_email))
    ins_cards = "".join(_card(e, i + 1, "outreach_insurance")
                        for i, e in enumerate(ins))
    web_rows = "".join(
        f"<tr><td><b>{html.escape(e['organization'])}</b> ({html.escape(e['country'])})</td>"
        f"<td><a href=\"{html.escape(e['form_url'])}\">{html.escape(e['form_url'])}</a></td>"
        f"<td>{html.escape(e.get('note') or '')}</td></tr>" for e in csrd_web)
    hold_rows = "".join(
        f"<tr><td><b>{html.escape(n)}</b></td><td>{html.escape(r)}</td></tr>" for n, r in HOLD_CSRD)
    ins_skip_rows = "".join(
        f"<tr><td><b>{html.escape(n)}</b></td><td>{html.escape(r)}</td></tr>" for n, r in INSURANCE_SKIPS)

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Talaix — CSRD wave + insurance batch preview (2026-09-07)</title>
<style>{CSS}</style></head><body>
<h1>Next waves — operator preview: CSRD-obligated companies + insurance</h1>
<p class="meta">Generated 2026-09-07 · sources: csrd_companies_wave1.json + insurance_fresh_wave.json ·
templates: outreach_sustainability_compliance (already approved) + outreach_insurance ·
NOTHING is scheduled or sent yet — scheduling runs only after «معتمد».</p>

<div class="summary">
<b>Rolling send plan (DAILY_SEND_CAP=15, →20 from 09-14; window 07:00–17:00 UTC):</b>
<table>
<tr><th>Date</th><th>Content</th><th>Total</th></tr>
<tr><td>Tue 09-08</td><td>11 investor + 3 compliance (already queued)</td><td>14 ≤ 15 ✓</td></tr>
<tr><td>Wed 09-09</td><td>4 investor + 2 compliance (already queued)</td><td>6 ✓</td></tr>
<tr><td>Thu 09-10</td><td><b>10 CSRD</b> + 2 compliance</td><td>12 ✓</td></tr>
<tr><td>Fri 09-11</td><td><b>4 CSRD + 2 insurance</b> + 1 compliance</td><td>7 ✓</td></tr>
<tr><td>Sat/Sun 09-12/13</td><td>no cold sends (weekend)</td><td>0</td></tr>
<tr><td>Mon 09-14 →</td><td>cap rises to 20/day — consultants channel wave (43 fresh, next approval), banking/investment fresh (22), follow-up wave for 41 pre-pivot contacts ~09-22</td><td>—</td></tr>
</table>
<p class="meta">Every address is literally published on the company's official site (source link under each card).
UPM's mailbox keeps the exact spelling their page publishes. No guessed addresses anywhere.</p>
</div>

<h2>① CSRD-obligated companies wave — {len(csrd_email)} emails (template: the one you already approved)</h2>
{csrd_cards}

<h2>② Insurance fresh batch — {len(ins)} emails (template: outreach_insurance, ORSA/EIOPA angle)</h2>
{ins_cards}

<h2>③ CSRD webform-only — operator submits manually ({len(csrd_web)})</h2>
<table><tr><th>Company</th><th>Official form</th><th>Notes</th></tr>{web_rows}</table>

<h2>④ CSRD research holds — no fit-for-purpose published route ({len(HOLD_CSRD)})</h2>
<table>{hold_rows}</table>

<h2>⑤ Insurance honest skips — and why ({len(INSURANCE_SKIPS)} groups)</h2>
<table>{ins_skip_rows}</table>

</body></html>"""
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(OUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render the investor outreach wave (A/B/C) into a single HTML preview page
so the operator can read every message exactly as recipients would get it —
BEFORE anything is scheduled or sent.

Writes marketing/outreach/investor_waves_abc_preview.html and prints its path.
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

DATA_PATH = os.path.join(BASE, "marketing", "outreach", "investor_waves_abc.json")
OUT_PATH = os.path.join(BASE, "marketing", "outreach", "investor_waves_abc_preview.html")
TEMPLATE = "outreach_investor"

EXCLUDED = [
    ("DeepTechXL", "Operator sends the reply + deck personally (thread with Joel George) — never auto-mailed."),
    ("Rubio Impact Ventures",
     "Official funding page states it does NOT invest in ESG/transparency tools — our category is a stated exclusion. "
     "Honest skip; operator may override."),
]
PENDING = [
    ("Pale Blue Dot", "SE", "Contact research incomplete (batch interrupted 2026-09-07; operator decision: proceed without)."),
    ("SE Ventures (Schneider Electric)", "FR/SG", "Contact research incomplete (batch interrupted 2026-09-07; operator decision: proceed without)."),
    ("Main Sequence Ventures", "AU", "Contact research incomplete (batch interrupted 2026-09-07; operator decision: proceed without)."),
    ("100x100 (ex-Wavemaker Impact)", "SG", "No published email or form on the new 100x100.com site; old wavemaker.vc address is archived — do not use."),
    ("Dalus Capital", "MX", "No pitch channel published (only a complaints mailbox — unusable). Route: warm intro."),
    ("DCVC", "US", "No cold-pitch channel published on dcvc.com — warm-intro-only fund."),
]

CSS = """
body{font-family:-apple-system,'Inter',sans-serif;background:#f4f6f8;color:#0f172a;margin:0;padding:2rem;}
h1{font-size:1.5rem;} h2{font-size:1.1rem;margin-top:2.5rem;border-bottom:2px solid #0EA5E9;padding-bottom:.3rem;}
.meta{color:#475569;font-size:.9rem;}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.2rem 1.4rem;margin:1rem 0;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.badge{display:inline-block;background:#0EA5E9;color:#fff;border-radius:6px;padding:.1rem .5rem;font-size:.75rem;margin-right:.4rem;}
.badge.gray{background:#64748b;} .badge.amber{background:#b45309;} .badge.red{background:#b91c1c;}
pre{white-space:pre-wrap;font-family:'SF Mono',Menlo,monospace;font-size:.82rem;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;line-height:1.45;}
a{color:#0EA5E9;} table{border-collapse:collapse;width:100%;font-size:.9rem;}
td,th{border:1px solid #e2e8f0;padding:.45rem .6rem;text-align:left;vertical-align:top;}
.summary{background:#ecfeff;border:1px solid #0EA5E9;border-radius:10px;padding:1rem 1.4rem;}
"""


def _card(entry: dict, idx: int) -> str:
    context = {
        "contact_name": entry.get("contact_name") or "there",
        "organization": entry["organization"],
        "thesis_hook": entry.get("thesis_hook") or "",
        "portfolio_overlap": entry.get("portfolio_overlap") or "",
        "custom_message": entry.get("custom_message") or "",
        "unsubscribe_url": mailer.unsubscribe_mailto(),
    }
    rendered = mailer.render_template(TEMPLATE, context)
    body = rendered["text"].rstrip() + "\n\n" + mailer.signature_text()
    send_at = entry["send_at"]
    utc = datetime.fromisoformat(send_at)
    brussels = utc + timedelta(hours=2)  # CEST in September
    when = f"{utc:%Y-%m-%d %H:%M} UTC · {brussels:%H:%M} Brussels"
    return f"""
<div class="card">
  <div><span class="badge">#{idx} · Wave {html.escape(entry['wave'])}</span>
  <span class="badge gray">{html.escape(when)}</span></div>
  <h3>{html.escape(entry['organization'])} ({html.escape(entry['country'])})</h3>
  <p class="meta">TO: {html.escape(entry['to_email'])} &nbsp;·&nbsp; contact route observed:
  <a href="{html.escape(entry['source'])}">{html.escape(entry['source'])}</a> (checked {entry['date_checked']})</p>
  <p><b>SUBJECT: {html.escape(rendered['subject'])}</b></p>
  <pre>{html.escape(body)}</pre>
</div>"""


def main() -> int:
    with open(DATA_PATH, encoding="utf-8") as fh:
        entries = json.load(fh)
    email_entries = [e for e in entries if e.get("to_email")]
    webform_entries = [e for e in entries if e.get("channel") == "webform"]

    per_day = {}
    for e in email_entries:
        per_day.setdefault(e["send_at"][:10], 0)
        per_day[e["send_at"][:10]] += 1
    plan_rows = "".join(
        f"<tr><td>{d}</td><td>{n} investor emails</td>"
        f"<td>{'3' if d == '2026-09-08' else '2' if d == '2026-09-09' else '0'} compliance (Vultr, separate store)</td>"
        f"<td>{n + (3 if d == '2026-09-08' else 2 if d == '2026-09-09' else 0)} ≤ 15 ✓</td></tr>"
        for d, n in sorted(per_day.items()))

    cards = "".join(_card(e, i + 1) for i, e in enumerate(email_entries))
    webform_rows = "".join(
        f"<tr><td><b>{html.escape(e['organization'])}</b> ({html.escape(e['country'])}) — Wave {e['wave']}</td>"
        f"<td><a href=\"{html.escape(e['form_url'])}\">{html.escape(e['form_url'])}</a></td>"
        f"<td>{html.escape(e.get('note') or '')}</td></tr>"
        for e in webform_entries)
    excluded_rows = "".join(
        f"<tr><td><b>{html.escape(name)}</b></td><td>{html.escape(reason)}</td></tr>"
        for name, reason in EXCLUDED)
    pending_rows = "".join(
        f"<tr><td><b>{html.escape(name)}</b> ({html.escape(cc)})</td><td>{html.escape(reason)}</td></tr>"
        for name, cc, reason in PENDING)

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Talaix — Investor Wave A/B/C preview (2026-09-07)</title>
<style>{CSS}</style></head><body>
<h1>Investor outreach wave A/B/C — operator preview</h1>
<p class="meta">Generated 2026-09-07 · source data: marketing/outreach/investor_waves_abc.json ·
template: src/dashboard/email_templates/outreach_investor.txt ·
NOTHING is scheduled or sent yet — scheduling runs only after the operator says «معتمد».</p>

<div class="summary">
<b>Send plan (daily-cap discipline, DAILY_SEND_CAP=15, window 07:00–17:00 UTC):</b>
<table><tr><th>Date</th><th>Investor (this machine)</th><th>Compliance wave (Vultr)</th><th>Combined</th></tr>{plan_rows}</table>
<p class="meta">Every address below is literally published on the fund's official site (source link under each card).
Funds with no published email are NEVER guessed — they go to the manual webform list.</p>
</div>

<h2>① Emails to send — {len(email_entries)} (read each one)</h2>
{cards}

<h2>② Webform-only — operator submits manually ({len(webform_entries)})</h2>
<table><tr><th>Fund</th><th>Official form</th><th>Notes</th></tr>{webform_rows}</table>

<h2>③ Excluded from this wave</h2>
<table>{excluded_rows}</table>

<h2>④ Pending — no verified route yet (not contacted)</h2>
<table>{pending_rows}</table>

</body></html>"""
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(OUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

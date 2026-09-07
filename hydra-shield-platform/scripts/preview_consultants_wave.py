#!/usr/bin/env python3
"""Render the consultants channel wave into an HTML preview page for
operator review — BEFORE anything is scheduled or sent.

Writes marketing/outreach/consultants_wave1_preview.html and prints its path.
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

DATA_PATH = os.path.join(BASE, "marketing", "outreach", "consultants_wave1.json")
OUT_PATH = os.path.join(BASE, "marketing", "outreach",
                        "consultants_wave1_preview.html")
TEMPLATE = "outreach_environmental_consulting"

NOTES = [
    ("Composition flag", "Harvest is architecture/engineering-firm heavy (plus ESG consultancies): JP 13, ES 7, NL 5, GB 5, IT 3, IN 2, DE 2, BR 2, FR 1, SG 1 — every mailbox is OBSERVED-verified, but the segment leans built-environment."),
    ("Uniform problem line", "All leads carry the same harvested problem statement (\"client engagements need defensible, source-cited climate evidence\") — true for the channel, but per-recipient depth is thin beyond org/country/practice."),
    ("Dropped on purpose", "deloitte-tohmatsu (Big-4 — channel, not a cold target) and q140677831 (unresolved QID name) were removed by the builder."),
    ("Sequencing (operator decision 2026-09-07)", "Consultants go AFTER the investor (09-08/09) and CSRD/insurance (09-10/11) waves: sends start Mon 2026-09-14, 15/day over 3 days (cap rises to 20 the same day)."),
]

CSS = """
body{font-family:-apple-system,'Inter',sans-serif;background:#f4f6f8;color:#0f172a;margin:0;padding:2rem;}
h1{font-size:1.5rem;} h2{font-size:1.1rem;margin-top:2.5rem;border-bottom:2px solid #0EA5E9;padding-bottom:.3rem;}
.meta{color:#475569;font-size:.9rem;}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.2rem 1.4rem;margin:1rem 0;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.badge{display:inline-block;background:#0EA5E9;color:#fff;border-radius:6px;padding:.1rem .5rem;font-size:.75rem;margin-right:.4rem;}
.badge.gray{background:#64748b;}
pre{white-space:pre-wrap;font-family:'SF Mono',Menlo,monospace;font-size:.82rem;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;line-height:1.45;}
a{color:#0EA5E9;} table{border-collapse:collapse;width:100%;font-size:.9rem;background:#fff;}
td,th{border:1px solid #e2e8f0;padding:.45rem .6rem;text-align:left;vertical-align:top;}
.summary{background:#ecfeff;border:1px solid #0EA5E9;border-radius:10px;padding:1rem 1.4rem;}
.warn{background:#fff7ed;border:1px solid #b45309;border-radius:10px;padding:1rem 1.4rem;}
"""


def _card(entry: dict, idx: int) -> str:
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
    rendered = mailer.render_template(TEMPLATE, context)
    body = rendered["text"].rstrip() + "\n\n" + mailer.signature_text()
    utc = datetime.fromisoformat(entry["send_at"])
    brussels = utc + timedelta(hours=2)
    when = f"{utc:%Y-%m-%d %H:%M} UTC · {brussels:%H:%M} Brussels"
    return f"""
<div class="card">
  <div><span class="badge">#{idx}</span> <span class="badge gray">{html.escape(when)}</span></div>
  <h3>{html.escape(entry['organization'])} ({html.escape(entry['country'])})</h3>
  <p class="meta">TO: {html.escape(entry['to_email'])} &nbsp;·&nbsp; source:
  <a href="{html.escape(entry['source'])}">{html.escape(entry['source'])}</a>
  (observed {entry['date_checked']})</p>
  <p><b>SUBJECT: {html.escape(rendered['subject'])}</b></p>
  <pre>{html.escape(body)}</pre>
</div>"""


def main() -> int:
    with open(DATA_PATH, encoding="utf-8") as fh:
        entries = json.load(fh)
    cards = "".join(_card(e, i + 1) for i, e in enumerate(entries))
    note_rows = "".join(
        f"<tr><td><b>{html.escape(t)}</b></td><td>{html.escape(x)}</td></tr>"
        for t, x in NOTES)
    per_day = {}
    for e in entries:
        per_day[e["send_at"][:10]] = per_day.get(e["send_at"][:10], 0) + 1
    plan = " · ".join(f"{d}: {n}" for d, n in sorted(per_day.items()))

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Talaix — Consultants channel wave preview (2026-09-07)</title>
<style>{CSS}</style></head><body>
<h1>Consultants channel wave — operator preview</h1>
<p class="meta">Generated 2026-09-07 · source: marketing/outreach/consultants_wave1.json
(built by scripts/build_consultants_wave1.py from verified store contacts) ·
template: outreach_environmental_consulting ·
NOTHING is scheduled or sent yet — scheduling runs only after «معتمد».</p>

<div class="summary"><b>Send plan:</b> {plan} — 15/day moderate, 15-min stagger from 07:05 UTC,
inside the 07:00–17:00 UTC window; starts AFTER the investor and CSRD/insurance waves (operator decision).</div>

<div class="warn"><b>Read me before approving — honest quality notes:</b>
<table>{note_rows}</table></div>

<h2>Emails to send — {len(entries)}</h2>
{cards}

</body></html>"""
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(OUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

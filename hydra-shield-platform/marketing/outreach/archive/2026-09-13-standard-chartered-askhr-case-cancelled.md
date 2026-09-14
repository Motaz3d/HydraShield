# Archived inbound — Standard Chartered AskHR case HRC6274378 (cancelled)

Archived: 2026-09-14 · Archived by: copilot, on operator instruction ("حلل هذه الرسالة واحفظها في الارشيف")
Source of record: operator Gmail inbox, message received 2026-09-13 12:20 local (≈10:20 UTC), from `AskHR <scbnow01@service-now.com>`
Classification: **machine notification, not a reply** — no human at the target read the outreach.

## Verbatim message

```
HR Case HRC6274378 has been cancelled
External
Inbox

AskHR <scbnow01@service-now.com>
Sun, Sep 13, 12:20 PM
to me

HRC6274378
Opened by: info
State: Cancelled

Short Description: [Newly Registered Domain] [External] Physical-risk evidence for the loan book — Standard Chartered Taiwan
Description:

Hi Chief Risk Officer,

EBA Pillar 3 ESG disclosures and EU Taxonomy alignment checks now require banks to show the physical
climate exposure behind their loans — not a score, but evidence tied to collateral locations.

Talaix supplies that evidence layer: ten hazards screened per financed asset, from Earth observation and
official open data, every value with its source, date and evidence status. We do not produce capital
requirements or accreditation; we give credit files and disclosure workflows documented, defensible inputs.

loan-book and collateral locations need documented climate exposure evidence

For Standard Chartered Taiwan: ten-hazard screening of collateral and loan-book locations from Earth
observation and official open data — every value with source, date and evidence status, ready for
physical-risk credit files and disclosure workflows; EU collateral also receives CSRD/EU Taxonomy context

Send three collateral coordinates and we will return a free sample verification report — no procurement step needed.

Worth a 20-minute call this week?

---

Not relevant? One click and we will not write again: mailto:info@talaix.com?subject=unsubscribe

--

Talaix
Climate-Risk Compliance Evidence for EU Disclosure
Earth Observation & Physical-Risk Intelligence
Luxembourg-based technology team
info@talaix.com | talaix.com

----------------------------------------------------------------------
This email and any attachments are confidential and may also be privileged. If you are not the intended
recipient, please delete all copies and notify the sender immediately. You may wish to refer to the
incorporation details of Standard Chartered PLC, Standard Chartered Bank and their subsidiaries together
with Standard Chartered Bank's Privacy Policy via our public website.
----------------------------------------------------------------------

Comments:

Open case

Ref:MSG363395953_uEadJbnd9WtqDGJSJ0
```

## What actually happened (reconstructed from the store)

| Step | Evidence |
|---|---|
| 2026-09-12 10:40:19Z — banking outreach sent to `askhr@sc.com` (contact labelled "Chief Risk Officer"), template `outreach_banking`, subject "Physical-risk evidence for the loan book — Standard Chartered Taiwan", campaign `auto-backfill-2026-09-12` | `scheduled_outreach` id 138, status `sent`; `lead_interactions` id 115; lead `standard-chartered-taiwan` → `outreach_status: contacted` |
| Standard Chartered's gateway tagged the message `[Newly Registered Domain]` + `[External]` and routed it to the AskHR intake queue | case short description verbatim above |
| Their ServiceNow auto-opened HR case **HRC6274378** from the inbound mail and **cancelled** it (unactionable external item; no HR action) | notification body, `Opened by: info`, `State: Cancelled` |
| Notification returned to the sender (`info@talaix.com`) — that is the message archived here | sender `scbnow01@service-now.com`, `Ref:MSG363395953_uEadJbnd9WtqDGJSJ0` |

## What this is NOT

- **Not a human reply and not a commercial signal.** The case was machine-opened from our own mail; nobody in a risk function saw it. Campaign reply metrics stay honest by excluding it.
- **Not a hard bounce.** The message was delivered and parsed, so the address is live: `data/bounce_guard.json` correctly has no 2026-09-13 entry and the 7-day rate stayed at 0/15 (09-12), far below the 5% alert threshold.
- **Not detected by `check_replies.py`.** The sender (`service-now.com`) matches no stored contact, so the scan left the message untouched/unseen and unlogged — the record exists only because the operator pasted it. That is expected behaviour, but it means blocked-in-transit mail is invisible to the pipeline unless archived by hand (this file).

## Findings

1. **Wrong-role contact (root cause).** `askhr@sc.com` is an HR service-desk intake, not a risk function. The lead's only stored contacts are the three addresses found by `talaix-discovery` on 2026-09-02 (confidence 90, verification OBSERVED): `askhr@sc.com`, `phishing@sc.com`, `security@sc.com`. Discovery scraped sc.com's security/HR pages; none of the three is a CRO route. The pitch was routed to an HR case queue and closed automatically.
2. **Two of the three stored addresses are abuse/incident desks** (`phishing@`, `security@`). Sending sales mail to those is a reputation risk (abuse reports / blocklisting). They are legacy rows predating the junk filter — commit `3fe6722` added `phishing`/`security`/`abuse`-class localparts to `JUNK_LOCALPARTS` (`src/dashboard/email_discovery.py`), but `askhr` is not covered, and these three rows survive in the store. Store-wide they are the *only* such rows.
3. **`[Newly Registered Domain]` is a structural headwind.** A tier-1 bank gateway flagged `talaix.com` on domain age, independent of content. Levers: sending history over time, keeping per-domain volume low (20/day cap already), no attachments on first contact (already true), and a DMARC decision — `_dmarc` is `p=none` (monitoring) per `docs/EMAIL_ARCHITECTURE.md`; tightening to `p=quarantine` after a clean monitoring window helps receivers trust the domain.
4. **No measurable harm.** One recipient, no unsubscribe request, no abuse report, bounce guard untouched; the message did not reach the decision layer either way.
5. **Lead quality.** `standard-chartered-taiwan` came from Wikidata (Q62267023) with the CRO role as a plausible-but-unverified target; no named risk contact exists in the store. The organisation is still a legitimate target — the *route* was wrong, not the segment.

## Actions

- **A1 (operator):** do not re-send to `askhr@sc.com`; treat that address as dead for sales.
- **A2 (copilot, on approval):** purge the three stale `standard-chartered-taiwan` contacts from the store (prod DB on `mtz` + the local mirror), log a `note` interaction, and extend `JUNK_LOCALPARTS` in `src/dashboard/email_discovery.py` with the `askhr`-class intake localparts (plus a regression test) so this cannot recur at other banks.
- **A3 (operator):** re-route the lead through a genuine risk / sustainability / IR contact published on sc.com or LinkedIn before any further send; otherwise park it (no follow-up wave).
- **A4 (strategic, no code):** for bank and insurer targets, only published role-appropriate mailboxes; keep the domain warm-up discipline (low volume, high relevance) and revisit DMARC once the monitoring window is clean.

## Related

- Lead ledger: `marketing/leads/standard-chartered-taiwan.json` (interaction appended 2026-09-13)
- Deliverability / DNS: `docs/EMAIL_ARCHITECTURE.md` · Bounce guard: `scripts/check_replies.py`, `data/bounce_guard.json`
- Contact discovery filters: `src/dashboard/email_discovery.py` (`JUNK_LOCALPARTS`, `_ROLE_LOCALPARTS`)

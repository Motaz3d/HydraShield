# Daily operator workflow

The copilot (`scripts/marketing_status.py`) drives the day. Outreach is
operator-initiated by default, with optional per-lead auto-send for
scheduled/bulk flows. Unsubscribes and the daily send cap are always honored.

## Morning

```
python scripts/marketing_status.py morning
```

1. **New commercial signals** — who showed climate-relevant activity
2. **Events to monitor** — ranked by relevance and date
3. **High-priority prospects** — who to contact today, why, with which
   Talaix service and which evidence
4. **Follow-ups due** — leads past their `next_followup` date
5. **Product demand signals** — what users actually analyzed/viewed
   (aggregate counts only)
6. **Content this week** — drafts awaiting human review
7. **Recommended outreach** — pick from the above; draft per the segment's
   style; queue in `marketing/outreach/queue.json`

## Evening

```
python scripts/marketing_status.py evening
```

1. **Record interactions** — append to each lead's `interactions[]`
   (date, type, summary, source, next_action)
2. **Update lead status** — `outreach_status`, `status`, `last_contact`,
   `next_followup`
3. **Record responses** — what was actually said/decided
4. **Capture lessons** — persuasive evidence, dead ends →
   `marketing/analytics/` notes
5. **Generate next actions** — tomorrow's priorities emerge from the
   records, not from memory

## Rules

- A record without `source` + `date_checked` does not exist.
- Unknown stays "unknown" — never pad a lead.
- The integrity check runs inside every copilot call; fix problems before
  acting on the data.

## Marketing CRM tabs

The Marketing CRM lives in `/admin.html` as two tabs — **Targets** and
**Site statistics** — next to the Commercial Center tab. `/marketing.html`
is a legacy alias: operator-gated like `/admin.html`, it redirects to
`/admin.html#targets`.

**Targets** is a lazy drill-down: **sector → country → all targets in the
intersection**. `GET /api/v2/admin/marketing/tree` returns every segment
present in the lead base (we target all sectors) with counts; adding
`?segment=` returns countries; `?segment=&country=` returns the status
counts plus the full lead list (each lead carries its `outreach_status`);
adding `&status=` filters that list. The intersection opens as a modal
listing every targeted organisation with Auto-send / Follow-up buttons.
Lead detail (`/api/v2/admin/marketing/lead/<slug>`) shows the merged
record, score, interaction log, follow-up file and scheduled outreach.

**Site statistics** (`/api/v2/admin/marketing/stats`) shows visitor cards
(today / 7d / 30d unique sessions, page views), subscribers and accounts,
then collapsible detail sections: most visited pages, daily visitors,
traffic sources, devices & languages and risk interests. Aggregate counts
only — analytics sessions are pseudonymous hashes.

**Auto-send.** The operator clicks send; individual sends are always
operator-initiated. Each lead can be opted into auto-send for scheduled/bulk
flows (`POST /lead/<slug>/auto-send`). The message is rendered from the sector
templates in `src/dashboard/email_templates/outreach_*.txt` (falling back to
`outreach_generic.txt`), merged with the lead's country, identified problem,
capability, custom note and an unsubscribe footer. Without `SMTP_HOST`
configured, email goes to the dev outbox (`HYDRASHIELD_OUTBOX_DIR`) and the UI
says so; with SMTP env set, delivery uses STARTTLS.

**Daily send cap.** A hard cap (default 20, override with `DAILY_SEND_CAP`)
counts immediate sends and scheduled sends per calendar day. When the cap is
reached, the API returns 429 for new sends and the cron processor leaves
remaining scheduled rows pending for the next day.

**Unsubscribe.** A lead can be marked unsubscribed from the CRM. Unsubscribed
leads block all immediate and scheduled sends; scheduled rows for unsubscribed
leads are marked `skipped_unsubscribed` rather than sent or failed. Every
outreach template includes an unsubscribe footer.

**Scheduled sending.** Queue future emails with `send_at` (ISO, must be
future). A cron job sends due rows, skips unsubscribed leads, enforces the
daily cap, logs an `email` interaction, and advances `outreach_status` to
`contacted` when it was `researched`, `qualified` or `draft_prepared`:

```
*/5 * * * * cd <repo>/hydra-shield-platform && .venv/bin/python scripts/process_scheduled_outreach.py
```

## Campaigns & replies (Phase 18)

**Campaign waves.** A campaign is a named sequence of follow-up emails sent to
matching leads. Use the CLI or the Targets tab in `/admin.html` to enqueue a
wave:

```
python scripts/run_campaign.py --campaign q4-2026 --wave 2 --template followup_1 \
    --filter segment=banking --filter country=US --delay-days 1
```

Allowed templates are `followup_1` (wave-2 nudge) and `followup_2`
(wave-3 value-add + breakup). Eligible leads must have at least one stored
contact, not be excluded or unsubscribed, and have an early outreach status
(`researched`, `qualified` or `contacted`). The processor sends due waves in
order, enforces the daily cap, and cancels any pending wave for a lead that
has replied or unsubscribed.

The same endpoints power the UI:
- `GET /api/v2/admin/marketing/campaigns` — per-campaign stats and wave breakdowns
- `GET /api/v2/admin/marketing/campaigns/<name>` — detail for one campaign
- `POST /api/v2/admin/marketing/campaigns/start` — enqueue a wave

**Reply detection.** When `IMAP_*` is configured, `scripts/check_replies.py`
scans the inbox for unseen messages, matches the sender to stored contacts,
logs a `reply` interaction, sets `outreach_status` to `replied`, and
auto-cancels scheduled outreach plus campaign waves. If the subject or plain-text
body contains "unsubscribe" or "إلغاء الاشتراك", it also marks the lead
unsubscribed and logs an `unsubscribe` interaction. Matched messages are marked
Seen; unmatched messages are left untouched.

Cron (e.g. every 15 minutes):
```
*/15 * * * * cd /path/to/hydra-shield-platform && .venv/bin/python scripts/check_replies.py
```

**Contact imports.** Research contacts live in `marketing/imports/*.json` and are
idempotently imported into the CRM with:
```
python scripts/import_contacts.py
```
Missing lead files are created automatically; contacts are deduplicated by
`(lead_slug, email)`.

## Signatory lists (Layer 1)

Official climate-finance signatory lists are a permanent, low-noise lead source.
The model is: fetch the official page → parse the published table → resolve an
honest website per row → match by normalised organisation name → merge into an
existing lead or create a new one. Re-running is idempotent.

**Source registry** (`src/dashboard/signatories.py`):

| id | name | state | reason |
|---|---|---|---|
| `pcaf` | Partnership for Carbon Accounting Financials | **live** | public server-rendered table with disclosure status and per-organisation disclosure PDFs |
| `unepfi` | UNEP FI Membership | pending | AJAX-rendered list; no confirmed public endpoint |
| `icma` | International Capital Market Association | pending | JS-rendered |
| `gfanz` | Glasgow Financial Alliance for Net Zero | pending | no public member list published |

Pending sources are recorded with their exact reason. They are **not scraped** in
this phase.

**Website resolution (two-stage, honesty HARD):**

1. **Self-hosted disclosure PDF.** If the published disclosure URL is hosted on
the organisation's own domain, that domain becomes the lead website
(`website_source: self-disclosure`).
2. **Wikidata official website (P856).** If the disclosure PDF is hosted on the
PCAF site itself (which is the norm — PCAF publishes no organisation websites),
the importer queries Wikidata's public API for the entity's `P856` official
website claim (`website_source: wikidata`).
3. **Pending.** If neither source yields a verifiable website, the row is written
to `marketing/imports/signatory_pending.json` with `pending_reason` and is **not**
turned into a lead. This file is overwritten wholesale on each run; it is a
staging snapshot, not a cumulative backlog.

**Run the import (PCAF live now):**

```
python scripts/import_signatories.py
python scripts/import_signatories.py --source pcaf
python scripts/import_signatories.py --dry-run
python scripts/import_signatories.py --dir /path/to/marketing/leads
```

One-off cleanup of the buggy PCAF-domain leads (Phase 20 bug):

```
python scripts/import_signatories.py --purge-bad
```

The script:

- Fetches only live sources.
- Refuses to import a truncated PCAF table (`< 200` rows) and aborts that source
  with exit code `2`.
- Resolves websites in two stages; unresolved rows go to the pending snapshot.
- Builds leads only from resolved rows; each lead carries `website_source` and
  `wikidata_id` when applicable. The original disclosure URL remains in
  `signatory_meta` as provenance.
- Merges by normalised organisation name, appending the source to `signatory_of`
  and storing per-source metadata under `signatory_meta`.
- Sets `priority` to `high` when a signatory has status **Disclosed** or appears
  on two or more lists.

**Weekly cron:**

```
0 9 * * 1 cd /path/to/hydra-shield-platform && .venv/bin/python scripts/import_signatories.py
```

**From signatory import to contact:**

1. Import produces/updates a lead in `marketing/leads/` (or stages it in
   `marketing/imports/signatory_pending.json`).
2. Use the CRM **Contacts** flow (`/admin.html` Targets tab or
   `scripts/import_contacts.py`) to discover a public contact at the organisation.
3. Review the lead, then **Preview** and **Send** — individual sends remain
   operator-initiated.

**Honesty note:** this importer copies only what the official lists and
Wikidata publish. Disclosure URLs are captured verbatim. PCAF's own domain is
**never** used as an organisation's website. No organisation is invented, no
domain is guessed, no contact is inferred, and no financial figure is padded.
Unresolved rows stay in the pending snapshot rather than being assigned a fake
website.

## Organization inventory (deep scan)

The Wikidata-based inventory is a second permanent lead source. It scans
companies, institutions and government bodies across sectors and countries
using the public Wikidata SPARQL endpoint, then feeds the marketing workspace.

**Target matrix** (`src/dashboard/org_inventory.py`):

| Segment | Concepts scanned |
|---|---|
| Banking | bank, central bank |
| Insurance | insurance company |
| Investment | investment company, asset management company, pension fund, sovereign wealth fund |
| Real estate | real estate company, real estate investment trust |
| Governments | ministry of the environment, government agency, meteorological service, disaster management agency |
| Research centers | university, research institute |

**Countries** (ISO-3166-1 alpha-2 codes):

- East Asia: CN, JP, KR, TW, HK, MN
- Southeast Asia: SG, ID, MY, TH, VN, PH, MM, KH, LA, BN, TL
- Europe focus: LU, BE, NL, DE, FR, CH, AT, DK, FI, SE, NO, PL, CZ, HR, RO, PT, ES, IT, GR, GB

**Website rule (honesty HARD):**

1. Wikidata SPARQL returns the entity's official website (`P856`) when it exists.
2. Rows **without** a P856 website are **never** turned into leads. They are
   written to `marketing/imports/inventory_pending.json` with reason
   `no official website found (Wikidata P856 missing)`.
3. No domain is guessed, no search engine is scraped, and no inferred URL is
   used.

**Run the inventory:**

```
python scripts/run_org_inventory.py
python scripts/run_org_inventory.py --countries JP,KR,SG --concepts bank,insurance company
python scripts/run_org_inventory.py --limit 200 --sleep 1.0
python scripts/run_org_inventory.py --dry-run
python scripts/run_org_inventory.py --dir /path/to/marketing/leads
```

The script:

- Resolves each concept and country to a Wikidata Q-id once per run.
- Records unresolvable concepts/countries in `skipped` and continues the sweep.
- Runs one SPARQL query per concept × country, sleeping `sleep` seconds between
  calls to stay polite to the Wikidata query service.
- Deduplicates within the sweep by normalised organisation name + country code.
- Merges matches against existing leads by normalised organisation name,
  appending source URLs to `inventory_of` (like `signatory_of`), adding
  `wikidata_id` and `concepts`, and logging a discovery interaction.
- Creates new lead files for organisations with a P856 website.
- Writes the staging pending snapshot to `marketing/imports/inventory_pending.json`
  (overwritten each run) and the operator summary to
  `marketing/reports/inventory_latest.json`.

**Monthly cron:**

```
0 6 1 * * cd /path/to/hydra-shield-platform && .venv/bin/python scripts/run_org_inventory.py
```

**From inventory to contact:**

1. Inventory produces/updates a lead in `marketing/leads/` (or stages it in
   `marketing/imports/inventory_pending.json`).
2. Use the CRM **Contacts** flow (`/admin.html` Targets tab or
   `scripts/import_contacts.py`) to discover a public contact. Government-body
   websites are often the richest public role-email sources because they are
   mandated to publish contacts.
3. Review the lead, then **Preview** and **Send** — individual sends remain
   operator-initiated.

**Honesty note:** this inventory copies only what Wikidata publishes. Official
websites come from Wikidata P856 only. No organisation is invented, no domain
is guessed, no contact is inferred, and no financial figure is padded.
Unresolvable concepts and countries are recorded, not fabricated.

## Email discovery (Talaix engine)

The CRM uses a layered discovery model: the Talaix engine runs first because
it is free and records provenance for every contact; Hunter.io remains
available as a quota-limited fallback.

The engine crawls a polite, fixed list of public pages on the target domain
(`/`, `/contact`, `/about`, `/team`, `/sustainability`, `/press`, etc. — up to
12 pages per request). It extracts emails from `mailto:` links and visible
text, including common "name [at] domain [dot] tld" obfuscation, then filters
junk localparts (`noreply`, `postmaster`, etc.), image-file artifacts,
off-domain addresses and free-mail hosts (`gmail.com`, `yahoo.com`, etc.).

Every returned contact carries:

- `email` — lower-cased, deduplicated
- `type` — `role` (`info@`, `press@`, etc.), `personal` (`first.last@`,
  `f.last@`, etc.) or `unknown`
- `source_url` — the exact public page where the address was observed
- `found_on` — the page path within the domain
- `claim_status` — `OBSERVED` for extracted addresses, `INFERRED` for
  pattern-generated addresses, `UNKNOWN` when no pattern is available
- `confidence` — page-weight score (0.50–0.99), never treated as verification

`robots.txt` is fetched and honored when possible; if it cannot be fetched or
parsed the engine proceeds politely and notes that in the result.

**Pattern inference.** When at least two personal emails at the same domain
share a consistent pattern (`first.last`, `f.last` or `first.l`), the engine
can infer a candidate for a named person. Inferred emails are always labelled
`INFERRED` and carry a "verify before sending" warning in the UI. They are
never displayed as observed or verified.

**Declared limits.** This phase does not perform SMTP probing (reputation
risk), does not validate via MX lookup (`dnspython` is not a dependency yet),
and does not use a global pre-built index like Hunter.io. It only reads pages
on the supplied domain, so deep pages or sites that block bots will yield
fewer contacts.

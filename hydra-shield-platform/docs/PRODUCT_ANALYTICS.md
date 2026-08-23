# Talaix — Product Analytics

**Status:** implemented (Phase B). First-party, privacy-conscious product
analytics. Normative reference for what is collected, why, and the controls.

## 1. Technology decision

A **lightweight first-party event system** — no third-party analytics
dependency (no Matomo/Plausible/GA), no tag manager, no external processor.
Rationale: the questions we need to answer are product questions (which
pages, hazards, solutions, reports, and funnel steps are used); a 250-line
beacon + one SQLite table + one ingest endpoint answers them without
sending user data to anyone else. If volume or analysis needs outgrow
this, a self-hosted privacy-respecting tool can be evaluated later — the
event schema below is the stable contract either way.

## 2. What is collected (whitelist)

`POST /api/v2/analytics/event` accepts only these event names
(`src/dashboard/analytics.py::ALLOWED_EVENTS`):

`page_view` · `hazard_selected` · `location_analyzed` · `map_opened` ·
`map_layer_enabled` · `historical_year_selected` · `event_opened` ·
`solution_viewed` · `solution_saved` · `report_previewed` ·
`report_generated` · `account_started` · `account_created` ·
`subscription_started` · `sms_enabled` · `alert_created` · `qgis_interest`
· `contact_started`

Per event, only these fields are accepted (anything else is dropped):

| Field | Content | Privacy treatment |
|---|---|---|
| `ts` | server timestamp (UTC) | — |
| `event` | one of the whitelist | — |
| `session_id` | random id generated in the browser (localStorage, **no cookie**) | stored only as **HMAC-SHA256 hash** |
| `page` | site path (e.g. `map.html`) | pattern-validated |
| `hazard` | hazard id | enum-bounded by the registry |
| `lat`/`lon` | analysis coordinates | **rounded to 1 decimal (~11 km)** |
| `feature` | e.g. layer id, report type | length-capped |
| `referrer` | origin + path only | query strings stripped |
| `device` | desktop / mobile / tablet | coarse enum |
| `language` | browser language tag | length-capped |
| `user_id` | account id | **only on explicit account events, recorded server-side** |

## 3. What is never collected

- IP addresses (rate limiting is in-memory only, nothing persisted)
- precise locations (analytics coordinates are rounded by construction)
- names, emails, phone numbers, free text, message contents
- passwords or any credentials; payment data; device fingerprints
- cross-site behaviour; advertising profiles; sensitive characteristics

The whitelist is enforced server-side: unknown event names are rejected
and unknown fields are dropped, so the store cannot silently grow new
collection. `account_created` and other account events are recorded
**server-side** at the moment they happen (`auth_api.verify`) — the public
ingest endpoint never accepts identity.

## 4. Consent, DNT, disclosure

- **Do Not Track**: the beacon sends nothing when DNT is enabled.
- **Disclosure**: `privacy.html` (linked in every footer) describes the
  collection in plain language.
- **Accounts**: registration carries an explicit consent checkbox
  (existing behaviour, unchanged). Browsing analytics relies on legitimate
  interest for a pseudonymised, minimised, first-party measurement; DNT +
  the deletion capability below are the opt-out.

## 5. Retention & deletion

- Retention: **12 months rolling** (`AnalyticsStore.purge_older_than`,
  default `RETENTION_DAYS = 365`); the retention sweep runs from the
  periodic checker.
- Erasure: `AnalyticsStore.delete_session(session_id)` deletes all events
  of a pseudonymous session; account deletion removes user-linked account
  events.
- Access: aggregation endpoints are **admin-only** (see §6); nothing from
  this store is exposed publicly.

## 6. Reading the data (admin)

Admin-only aggregate endpoints (`require_role("admin")`, in
`src/dashboard/analytics.py`): `GET /api/v2/admin/analytics/summary`
(totals, by-event counts, funnel), `GET /api/v2/admin/analytics/top?
dimension=page|hazard|referrer|feature`, `GET /api/v2/admin/analytics/
daily?days=N`. No row-level browsing export exists; the funnel is counts,
not people.

## 7. Funnel questions this answers

Which pages/hazards/locations attract use → which surfaces convert to
accounts (`account_created`) → monitoring (`alert_created`) → SMS
(`sms_enabled`) → reports (`report_generated`) → contact
(`contact_started`). Campaign attribution uses `referrer` (origin-level)
and, later, declared `utm` tags on links we publish ourselves.

## 8. Non-goals

No A/B identity experiments, no behavioural advertising, no sale or
sharing of analytics data, no public exposure of internal metrics, no
tracking of identified individuals' browsing.

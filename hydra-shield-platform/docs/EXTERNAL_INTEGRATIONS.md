# Talaix — External Integrations & Activation Readiness

**Status:** architecture (Phase H). What each external channel needs to
move from prepared/draft to live — and the audit trail each requires.
Nothing in this document authorizes sending; activation is an explicit
operator decision per channel.

## Channel readiness matrix

| Channel | State today | Activation requires | Audit trail |
|---|---|---|---|
| **Transactional email** (registration, contact, alerts) | LIVE — verified Google Workspace (`info@talaix.com`, SPF/DKIM/DMARC pass) via `SMTP_*` env | already active in production | per-message outbox/SMTP logs; alert deliveries recorded per channel |
| **SMS alerts** | ARCHITECTURE live; delivery pending provider credentials | `SMS_PROVIDER=http`, `SMS_HTTP_URL`, `SMS_API_KEY`/`SMS_API_SECRET`, `SMS_FROM` in the server env (chmod 600, untracked) | alert_deliveries rows with provider message id |
| **LinkedIn organic** | drafts + calendar + campaign queues ready | human publishing from reviewed drafts; OR official LinkedIn API with OAuth + documented permissions (docs/LINKEDIN_STRATEGY.md §7) | per-post status transitions in `marketing/content/drafts/` |
| **LinkedIn API integration** | not integrated | official API access, OAuth app review, scope grant; per-action logging | new integration doc + delivery log before first use |
| **Webhooks (outbound)** | LIVE — subscriber-configured, HMAC-signed, SSRF-guarded | active (subscriber feature) | webhook delivery rows |
| **QGIS plugin distribution** | architecture documented (docs/QGIS_INTEGRATION_ARCHITECTURE.md) | Phase 0 spike + repo submission (human) | plugin repo review history |
| **Gmail mailbox reading** | not implemented | Gmail API/OAuth architecture with explicit scopes and operator authorization | access log; no browser automation, ever |
| **Payment provider** | not integrated | provider evaluation + integration | transaction records |

## Future commercial-intelligence integrations (classified)

| Integration | Classification | Notes |
|---|---|---|
| Public procurement portals (TED, national) | RESEARCH REQUIRED | Public APIs exist; per-portal terms and rate limits to be verified before use |
| Company registries (national/EU open data) | RESEARCH REQUIRED | Official sources only; coverage varies by country |
| Official company publications (reports on company sites) | AVAILABLE | Manual research + URL live-check; no automation needed |
| Official event pages | AVAILABLE | Manual; recorded as EventSignals |
| Careers pages (public job postings) | AVAILABLE (manual) | Aggregator APIs: LEGAL/TERMS REVIEW REQUIRED |
| Platform ad-transparency libraries | LEGAL/TERMS REVIEW REQUIRED | Access rules and API availability differ per platform; qualitative `activity_level` only unless an authoritative spend figure is published |
| LinkedIn official APIs | CREDENTIAL REQUIRED + LEGAL/TERMS REVIEW | OAuth app, granted permissions, per-action audit; no scraping |
| CRM (e.g. self-hosted or SaaS) | DEFERRED | The `marketing/` workspace is the CRM until volume justifies one |
| Event APIs | DEFERRED | Manual official-page research suffices at current volume |
| Email sending (transactional) | AVAILABLE — live | Verified Workspace; operational notifications only |
| Newsletter/bulk email | DEFERRED + LEGAL/TERMS REVIEW | Requires consent management design first |
| Calendar | DEFERRED | — |
| Financial/market datasets | RESEARCH REQUIRED | Official/institutional sources only |

## Rules for every activation

1. Credentials live only in server-side environment/secret storage —
   never in Git, images, frontend, tests, docs or logs.
2. Bulk/unsolicited sending is never enabled by any activation.
3. Every outbound action class has a reviewable record before it scales.
4. A channel can be deactivated by removing its credentials — the system
   degrades honestly (outbox/disabled states), never crashes.

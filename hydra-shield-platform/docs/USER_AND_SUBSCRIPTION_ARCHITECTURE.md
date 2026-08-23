# Talaix — User & Subscription Architecture

**Status:** account system design + progressive gating model + email system.
Norms: least-privilege defaults; conversion through value, not obstruction;
no credentials in Git.

---

## 1. Roles

| Role | Description |
|---|---|
| `anonymous` | no account; public snapshot + limited analysis |
| `visitor` | email provided (verified) — unlocks extended analysis + saved location + updates |
| `registered` | full account — historical analysis, full reports, saved locations, alerts |
| `subscriber` | paid tier — complete reports, advanced maps, historical datasets, economic/financial intelligence, API access where appropriate |
| `professional` | subscriber variant for practitioners (researchers, consultants) |
| `business` / `municipality` / `government` | organization seats — multiple locations, monitoring, dashboards, custom reports, team access |
| `admin` | platform administration |

Roles map to permission sets; nothing sensitive is granted by default.
Organization roles are seated under an `organization` with a seat count.

## 2. Progressive gating (conversion through value)

| Tier | Gets |
|---|---|
| Anonymous | current snapshot, basic map, limited analysis (rate-limited per IP) |
| Email verified (visitor) | extended analysis, save 1 location, receive updates |
| Registered | historical analysis, all 3 report types, multiple saved locations, alerts |
| Subscriber | complete reports, advanced map layers, full historical datasets, economic/financial intelligence, API key |
| Enterprise/Government | organization accounts, multi-location monitoring, dashboards, custom reports, team seats, API |

Design rules: the public site stays genuinely useful; gating appears at
the moment of added value ("save this location", "see the 2022 event
layer", "download the full report"); every gated response explains what
unlocks it (HTTP 402/403 with a JSON `upgrade` descriptor).

## 3. Data model (SQLite, additive migrations)

```sql
users(id, email UNIQUE, password_hash, display_name, role, status,
      email_verified_at, created_at, last_login_at)
email_tokens(id, user_id, token_hash, purpose, expires_at, used_at)
sessions(id, user_id, token_hash, created_at, expires_at, ip, user_agent)
organizations(id, name, kind, seats, created_at)
organization_members(org_id, user_id, role)
subscriptions(id, owner_user_id NULL, owner_org_id NULL, tier, status,
      started_at, ends_at, external_ref NULL)
api_keys(id, user_id, key_hash, label, created_at, revoked_at)
saved_locations(id, user_id, name, lat, lon, created_at)
analysis_history(id, user_id NULL, anon_id NULL, hazard, lat, lon,
      params_json, summary_json, created_at)
report_history(id, user_id, report_type, hazard, lat, lon, params_json,
      report_meta_json, created_at)
alert_subscriptions(id, user_id, hazard, lat, lon, threshold_json,
      channel, created_at, active)   -- supersedes anonymous watches over time
usage_log(id, user_id NULL, endpoint, created_at, meta_json)
audit_log(id, actor_user_id, action, target, meta_json, created_at)
```

- Passwords: salted hash (PBKDF2-HMAC-SHA256 via stdlib `hashlib`, no new
  dependency). Tokens: random 256-bit, stored **hashed** (HMAC-SHA256),
  TTL'd. Reuses `src/security/api_security.py` primitives.
- The existing anonymous `watches` table keeps working; account alerts are
  the new path. Migration of a watch into an account is a user action.
- Audit log records security-relevant actions (login, verify, subscribe,
  key create/revoke, role change) — never passwords/tokens.

## 4. AuthN/Z mechanics (Flask)

- `POST /api/v2/auth/register` → create unverified user, send
  verification email (token link).
- `GET  /api/v2/auth/verify?token=` → verify, create session.
- `POST /api/v2/auth/login` / `POST /api/v2/auth/logout`.
- Bearer session token (`Authorization: Bearer …`) or HttpOnly cookie
  (website). Constant-time compares (existing security module).
- `require_role("subscriber")` decorator for gated endpoints; per-tier
  rate limits on top of the existing per-IP limiter.
- CSRF: token-cookie double-submit for browser POSTs; API clients use
  Bearer only (no cookie) — documented.
- GDPR: consent recorded at register; data-subject export/delete via
  `src/security/gdpr.py` helpers (wired in this stage); minimal data
  collection; watch emails deletable (existing behaviour preserved).

## 5. Email system

Address in service: **info@talaix.com**.

Environment variables (never committed; `.env.example` documents names
only):

```
SMTP_HOST · SMTP_PORT · SMTP_USER · SMTP_PASSWORD · SMTP_FROM=info@talaix.com
```

(The existing code reads `SMTP_PASS`; the new mailer accepts both
`SMTP_PASSWORD` and legacy `SMTP_PASS`.)

Implementation: `src/dashboard/mailer.py`

- One `send_mail(to, template, context)` entry point; templates rendered
  from `src/dashboard/email_templates/` (plain-text + minimal HTML pair).
- **Dev backend:** when SMTP vars are absent, emails are written to
  `data/outbox/` as `.eml` files (and logged) — never sent. Tests use the
  dev backend. Production uses STARTTLS SMTP.
- Templates: `welcome`, `email_verification`, `report_ready`,
  `report_delivery`, `alert`, `contact_acknowledgement`,
  `subscription_confirmation`.
- The existing watch-alert mail path (`monitoring.py`) migrates to the
  mailer, keeping behaviour identical when SMTP is configured.

## 6. API surface (v2)

```
POST /api/v2/auth/register · POST /api/v2/auth/login · POST /api/v2/auth/logout
GET  /api/v2/auth/verify · POST /api/v2/auth/resend-verification
POST /api/v2/auth/forgot-password · POST /api/v2/auth/reset-password
GET  /api/v2/account · PATCH /api/v2/account
GET/POST /api/v2/account/locations · DELETE /api/v2/account/locations/<id>
GET  /api/v2/account/history (analyses + reports)
GET/POST /api/v2/account/alerts · DELETE /api/v2/account/alerts/<id>
GET  /api/v2/account/subscription · POST /api/v2/account/subscribe
POST /api/v2/account/unsubscribe
GET  /api/v2/account/usage
POST /api/v2/contact  (public; sends acknowledgement via mailer)
```

Self-service subscription: `POST /account/subscribe` records an active
`subscriptions` row (never charged — §7) and promotes the account to
`subscriber`, unlocking API-key creation and the higher per-tier rate
limits; a `subscription_confirmation` email is sent on activation. Both
endpoints are idempotent; `POST /account/unsubscribe` returns the tier to
`registered` and never demotes operator-assigned roles. Role promotion
happens only through this recorded flow or the server-side operator list —
there is still no endpoint that accepts a role from the client.

Gated existing endpoints keep anonymous access with reduced depth; the
`upgrade` descriptor in responses tells the UI what a tier unlocks.

## 7. Non-goals (this stage)

- Payments/billing integration (subscriptions are recorded, not charged;
  `external_ref` awaits a provider). Card data never touches Talaix.
- SSO/OAuth, SAML. Multi-region data residency.
- Admin UI beyond minimal admin API calls.

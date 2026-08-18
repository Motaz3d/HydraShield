# HydraShield — Conversion Strategy

**Status:** implemented (Phase F). How free value becomes accounts,
monitoring and subscriptions — without dark patterns.

## 1. Principle

Conversion through value: the free tier is genuinely useful forever; the
prompt to register appears **only after a real result exists** and offers
the natural next step for that exact surface. One quiet strip per surface,
dismissible ("Not now" persists per surface via localStorage), never a
modal, never a wall.

## 2. Contextual CTAs (live)

| Surface | Moment | CTA |
|---|---|---|
| Intelligence (`intelligence.html`) | after a real analysis renders | "Save this analysis" → account |
| Events (`events.html`) | after historical events render | "Monitor this area" → account#sms |
| Map (`map.html`) | on map open | "Create a monitoring alert" → account#sms |
| Solutions (`solutions.html`) | after matched solutions render | "Save this solution set" → account |
| Reports (`reports.html`) | after report links render | "Keep my reports" → account |
| Homepage | always-on section | "Set up SMS alerts" → account#sms |

Implementation: `website/js/convert.js` (`HSConvert.show`), one include
per page, one call per success path.

## 3. The ladder

```
FREE VALUE → ACCOUNT → MONITORING → ALERTS → SMS → PROFESSIONAL → BUSINESS/GOVERNMENT
```

- Free: six-hazard analysis, maps, events, economy, solutions, PDF reports.
- Registered (free): save locations, history, 2 alert rules, email/SMS
  after phone verification.
- Subscriber/professional: 25 rules, SMS+email, alert history, API key.
- Business/government: 100 rules, organizations, webhooks, API.

Tier enforcement lives server-side (caps + 403 upgrade descriptors); the
site never invents entitlement claims — upgrade prompts render the
server's descriptor.

## 4. Measurement

Conversion is read from the first-party analytics funnel
(docs/PRODUCT_ANALYTICS.md): `page_view → location_analyzed /
solution_viewed / report_generated → account_created → alert_created →
sms_enabled`. Campaign-tagged landings add referrer attribution. No
per-person tracking: the funnel is counts, not individuals.

## 5. What we never do

No countdown timers, no fake scarcity, no "unlock to see your result"
walls on free features, no repeated prompts after dismissal, no
pre-checked consent, no silent SMS subscription (phone verification is
explicit).

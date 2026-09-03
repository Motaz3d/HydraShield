# Talaix — Email Architecture

**Status:** verified production architecture (2026-08-17). Describes the
real, confirmed configuration. **No credentials live in Git.**
Normative rule: DNS, Google Workspace, MX, SPF, DKIM and DMARC are
operator-managed and are **never modified by the platform or its
automation**.

---

## 1. Verified foundation (operator-confirmed)

| Component | State |
|---|---|
| Domain | `talaix.com` |
| Mail provider | **Google Workspace — Business Starter** |
| Primary mailbox | `info@talaix.com` — **fully operational** |
| Domain ownership | PASS |
| Gmail | READY |
| Sending | PASS · Receiving | PASS |
| SPF | PASS · DKIM | PASS (google._domainkey) · DMARC | PASS · TLS | PASS |

**DNS architecture (as deployed — do not change automatically):**

```
A      @    → 45.77.54.166
A      app  → 45.77.54.166
CNAME  www  → talaix.com
MX     @    → smtp.google.com (priority 1)
TXT    @    → v=spf1 include:_spf.google.com ~all
DKIM   google._domainkey → Google Workspace key (configured, verified)
DMARC  _dmarc → v=DMARC1; p=none   (intentionally monitoring mode —
                                    do NOT move to quarantine/reject
                                    automatically)
```

## 2. Address & identity model

| Address | Role | Rules |
|---|---|---|
| `info@talaix.com` | **Official Talaix organizational address** — all public/platform communication, transactional email, operator notifications | preferred public address |
| `motazomarien@gmail.com` | Founder / professional personal contact (long-term identity) | never modified by the platform |
| `motaz3d@gmail.com` | Existing personal account — recovery / historical identity | **must remain active; never deleted, replaced, migrated or modified** |

## 3. Alias plan (Google Workspace side — operator action, not automated)

Aliases attached to the existing `info@` user (no additional paid seats):

```
contact@ · hello@ · support@ · sales@ · partners@ · reports@ · alerts@
        @talaix.com  →  all route to info@talaix.com
```

- Aliases are created in the Google Workspace admin console by the
  operator. The platform does not and cannot create them.
- **Sending from an alias**: once the alias exists and is enabled under
  Gmail → Settings → "Send mail as", the platform can send with that
  alias in the `From` header through the same `info@` SMTP credentials.
  Per-template alias overrides are supported via env vars
  (`SMTP_FROM_<TEMPLATE>`, e.g. `SMTP_FROM_ALERT=alerts@talaix.com`,
  `SMTP_FROM_REPORT_DELIVERY=reports@talaix.com`) — see
  `.env.example`. The platform **never invents sender identities**: an
  alias is used only when explicitly set via env.

## 4. Capability matrix

| # | Capability | Status |
|---|---|---|
| A | Google Workspace mailbox **receiving** at info@ | **operational** (operator-verified) — handled entirely by Google Workspace, not by the application |
| B | Application **transactional sending** | implemented; activates when `SMTP_HOST/…` env secrets are set (Google Workspace SMTP: `smtp.gmail.com:587`, the info@ account + an app password — created operator-side, stored only in the server `.env`) |
| C | Contact form → platform inbox | implemented (`contact_message` → `CONTACT_INBOX`) |
| D | Registration notification (user) | implemented (`welcome`, `email_verification`) |
| E | Report delivery / report-ready | templates implemented (`report_delivery`, `report_ready`); account wiring is a later stage |
| F | Alerts (watch subscribers) | implemented (`alert`) |
| G | Account verification | implemented (24 h single-use token) |
| H | Password reset | implemented (single-use token, sessions invalidated) |
| I | **Operator notifications** to info@ | implemented (see §5) |
| J | Application reading/searching the Gmail mailbox | **not built — separate future design** (§7): SMTP credentials do NOT provide mailbox access |
| K | Marketing campaigns / newsletters | deliberately not built (§8) |

**Sending ≠ receiving.** The application never reads the mailbox. The
mailbox receiving capability lives in Google Workspace (operator reads it
in Gmail); the application only *sends* transactional email and *delivers
messages to* the platform inbox via its send path.

## 5. Operator notification matrix (info@talaix.com)

| Event | Mechanism | Content |
|---|---|---|
| New user registers | `admin_notification` | email, name, timestamp — never password/token |
| New contact message | `contact_message` | name, email, message text |
| Report generated | `operator_notification` (kind `report_generated`) | report type, location, report ID, history flag |
| Alert condition at a monitored location | `operator_notification` (kind `alert_fired`) | location, risk, threshold, delivery channel — subscriber address deliberately excluded |
| Subscription created | **pending** — subscriptions are recorded, not charged; no public creation endpoint exists yet. Notification hook point: `UserStore` subscription creation when that path ships |
| Material change at a monitored location | covered by the watch-alert path (threshold crossing = material change; account alerts checker is a later stage) |

All operator notifications go through `mailer.operator_notify()`:
anti-flood bucket (≤20/kind/hour), operational facts only, and the same
backend selection as everything else (safe outbox until SMTP env is set).

## 6. Local development & tests

- No credentials → the **safe outbox backend** writes `.eml` files to
  `data/outbox/` and never sends. All tests use it; **tests never contain
  real credentials and never send real email**.
- `HYDRASHIELD_OUTBOX_DIR` overrides the outbox location.

## 7. Future: application-level mailbox access (separate design)

If searching/reading the Gmail mailbox is ever required (support triage,
bounce handling), it must be a **separate, explicitly authorized**
architecture: Google Workspace Gmail API with OAuth 2.0 (domain-wide
delegation or per-user consent), least scopes (e.g. `gmail.readonly`),
credentials in server-side secret storage, audit logging, and a lawful
basis for any processing. Never: the Workspace password in the repo,
browser automation against Gmail, or mailbox credentials in frontend code.

## 8. Future: newsletter / campaign architecture

Not built. When authorized: double opt-in subscriber lists (the
`subscriptions`/consent records exist), unsubscribe links in every
message, provider-side sending (Google Workspace is not a bulk-mail
service — evaluate a proper ESP when the time comes), and **no use of
email data for marketing intelligence** without explicit configuration
and legal permission. The platform never sends marketing email
automatically.

## 9. Security policy (normative)

- Secrets come only from environment/secret storage.
- Logs never print SMTP passwords/tokens (the mailer logs template,
  recipient and outbox path only).
- `.env` files stay ignored (`.gitignore`); templates are versioned,
  credentials are not.
- Production secrets live only in the production server `.env`
  (`/opt/hydrashield/.env`, compose `env_file`).
- Audit events never contain email credentials.
- DMARC stays `p=none` (monitoring) until the operator decides otherwise.

## 10. Templates (versioned in Git)

`welcome` · `email_verification` · `password_reset` · `report_ready` ·
`report_delivery` · `alert` · `contact_acknowledgement` ·
`contact_message` · `admin_notification` · `operator_notification` ·
`subscription_confirmation`

Sender defaults to `SMTP_FROM` (info@talaix.com); per-template
alias overrides via `SMTP_FROM_<TEMPLATE>` env (§3).

## 11. Outreach auto-send pipeline (operator-gated)

Cold outreach (sales/funder/media) is **queued by humans or explicit
opt-in flags, sent only by the cron processor** — never by the web app:

- **Queue paths**: the CRM send/schedule endpoints
  (`/api/v2/admin/marketing/…`), campaign waves (`followup_1`/`followup_2`),
  `AUTO_OUTREACH_ON_CONTACT=1` (queue on newly discovered contacts), and
  the per-lead **Auto-send** toggle (same effect for one lead).
- **Sender**: `scripts/process_scheduled_outreach.py` via
  `scripts/email_cron.sh` (every 5 min, overlap-locked). Enforces, on
  every row: unsubscribe list, replied-lead auto-stop (rows are really
  cancelled, not re-polled), and the platform-wide daily cap
  (`DAILY_SEND_CAP`, default 20, counted across all send paths).
- **Reliability**: a transient SMTP failure reschedules the row
  (`OUTREACH_RETRY_MINUTES`, default 30) up to `OUTREACH_MAX_ATTEMPTS`
  (default 3) before it is marked failed. An optional UTC business-hours
  window (`OUTREACH_WINDOW_START`/`OUTREACH_WINDOW_END`) holds cold mail
  to professional sending times.
- **Standards**: every message carries explicit `Date` and `Message-ID`;
  `outreach_*`/`followup_*` templates also carry `List-Unsubscribe`
  (mailto to the platform inbox). `scripts/check_replies.py` classifies
  each matched reply before acting: machine acknowledgements (RFC 3834
  `Auto-Submitted`, autoresponder headers, stock phrases such as
  "system generated auto reply" / "out of office") are logged as notes
  only — they never stop outreach. Genuine human replies stop all pending
  sends and are forwarded to the operator inbox via
  `mailer.operator_notify` (sender, subject, fresh-text snippet). The
  unsubscribe heuristic judges only the freshly written reply text, never
  quoted history (our own footer contains the word "unsubscribe").
- **Bounce guard**: delivery-failure notices are matched to the failed
  recipient (body address, never the MTA sender), logged as `bounce`,
  the contact is marked `invalid` (wave selection skips it) and pending
  sends to that address are cancelled. A rolling 7-day bounce rate
  (`data/bounce_guard.json`) over 5% with ≥10 sends triggers a one-time
  operator email recommending Hunter.io verification — the agreed
  adoption trigger (`marketing/strategy/send_plan_2026-09.md` §7).
- **Wave scripts** (`send_funder_wave1/2.py`, `send_media_wave.py`) are
  DRY-RUN by default (`--send` to send), skip unsubscribed/replied leads,
  skip entries already logged as sent (re-run safe), and respect the same
  daily cap.

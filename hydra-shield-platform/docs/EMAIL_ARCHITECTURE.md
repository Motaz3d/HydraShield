# HydraShield — Email Architecture

**Status:** implemented capability description. Distinguishes precisely what
the platform CAN and CANNOT do today, and what must be configured outside
the repository. **No credentials live in Git.**

---

## 1. Capability matrix (honest)

| # | Capability | Status | Mechanism |
|---|---|---|---|
| A | **Send** transactional email | **implemented, inactive until SMTP env is set** | `mailer.py` STARTTLS SMTP via `SMTP_HOST/PORT/USER/PASSWORD/FROM` env secrets |
| B | **Receive** arbitrary external email at info@hydrashield.earth | **NOT a platform capability** — requires mailbox hosting + DNS/MX configuration outside this repository (§4). The platform never reads mailboxes |
| C | Contact form → platform inbox | **implemented** — submissions are delivered to `CONTACT_INBOX` (default info@hydrashield.earth) via the send path; in dev/unconfigured they land in the safe outbox (`data/outbox/`) |
| D | Registration notification (user) | implemented — `welcome` + `email_verification` |
| E | Report ready / delivery | templates implemented (`report_ready`, `report_delivery`) — wiring to account report generation is a later stage |
| F | Alerts | implemented — watch alerts via `alert` template (`scripts/check_watches.py`) |
| G | Account verification | implemented — `email_verification`, 24 h single-use token |
| H | Password reset | implemented — `password_reset`, single-use token, sessions invalidated |
| I | Admin notification on registration | implemented — `admin_notification` to the platform inbox (email + timestamp only, never secrets) |
| J | Marketing campaigns / newsletters | **deliberately not built** — infrastructure (mailer, templates, subscriber records) is ready for an authorized, legally-configured addition; the platform never sends marketing email automatically |

**Sending is not receiving.** An SMTP sender does not imply the platform
can receive arbitrary external email. Receiving requires mailbox hosting
and DNS/MX records (§4), which are outside the repository and are NOT
claimed to be configured.

## 2. Send path (implemented)

`src/dashboard/mailer.py` — one `send_mail(to, template, context)` entry:

- **SMTP backend** (production): active when `SMTP_HOST` is set.
  `SMTP_PORT` (default 587, STARTTLS), `SMTP_USER`,
  `SMTP_PASSWORD` (canonical; legacy `SMTP_PASS` honoured),
  `SMTP_FROM` (default `info@hydrashield.earth`).
- **Safe outbox backend** (dev / unconfigured): messages are written as
  `.eml` files to `data/outbox/` (override `HYDRASHIELD_OUTBOX_DIR`) and
  logged. **Never sent.** Tests assert on outbox files.
- Templates (`src/dashboard/email_templates/`): `welcome`,
  `email_verification`, `password_reset`, `report_ready`,
  `report_delivery`, `alert`, `contact_acknowledgement`,
  `contact_message`, `admin_notification`, `subscription_confirmation`.
- Contact flow: the visitor's message goes to `CONTACT_INBOX`
  (`contact_message`); the visitor receives a `contact_acknowledgement`
  that deliberately does NOT echo their message (anti-abuse).

## 3. Secrets policy (normative)

Mailbox/SMTP credentials are **runtime environment secrets only**. They
must never appear in: Git, source code, frontend, Dockerfile,
documentation, repository history, or public logs. The application reads
them exclusively from the environment. `.env.example` documents variable
names only. Production secrets are set server-side
(`/opt/hydrashield/.env` on Vultr, mounted into the api container via
docker-compose `env_file`).

## 4. Receiving email at info@hydrashield.earth (outside the repository)

For the address to receive external mail, the following must exist —
**none of which is configured by this repository**, and none of which is
claimed to exist until verified:

1. A mailbox or forward for `info@hydrashield.earth` at a mail provider
   (e.g. the domain registrar's mail hosting, or a dedicated provider).
2. DNS `MX` record(s) for `hydrashield.earth` pointing at that provider.
3. For the platform's *outbound* mail to be deliverable and not spam-flagged:
   `SPF` (TXT) authorising the sending host, `DKIM` signing (provider
   dependent), and optionally `DMARC` policy records.
4. Optional later stage: an authorized mailbox connection (IMAP/Graph/Gmail
   API) to ingest the platform inbox for support workflows — must be
   explicitly configured, scoped read-only, never used for marketing
   intelligence without a lawful basis, and never scraped.

Until items 1–2 are verified in DNS, statements about "receiving email at
info@hydrashield.earth" are limited to: the platform *delivers
contact-form submissions and notifications to that address via its send
path* — once SMTP credentials are configured.

## 5. What works today without any credentials

- Full registration → verification-email → verify → login → password-reset
  flow, with every email visible as an `.eml` in the safe outbox.
- Contact form → platform inbox (outbox) + acknowledgement (outbox).
- Admin registration notifications (outbox).
- Watch alert generation (recorded in DB; outbox email).

## 6. Adding the real mailbox later (secure procedure)

1. Provision the mailbox + MX/SPF/DKIM at the provider (outside repo).
2. Set `SMTP_HOST/PORT/USER/PASSWORD` + `SMTP_FROM=info@hydrashield.earth`
   in the server `.env` (never in Git).
3. `docker compose up -d api watch_checker` — the mailer switches from
   outbox to SMTP automatically (`smtp_configured()`).
4. Verify with a contact-form submission and a registration on production;
   confirm receipt at the mailbox and check spam scoring.

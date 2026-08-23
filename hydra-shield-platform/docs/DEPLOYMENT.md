# Talaix — Deployment Guide (Vultr + Docker)

This guide explains how to run the full Talaix product — static marketing
site, live Dash dashboard, and REST API — on a single Vultr server with
automatic deploys from your local machine.

## What gets deployed

| URL | Service | Tech | Internal port |
|-----|---------|------|---------------|
| `https://talaix.com/` | Marketing site + real-data public dashboard | Caddy file server | — |
| `https://talaix.com/api/*` | REST API (real data, cached) | Flask via **gunicorn** | 8051 |
| `https://app.talaix.com/` | Live dashboard | Dash via **gunicorn** | 8050 |
| (internal) | `watch_checker` | periodic alert evaluation every 30 min | — |

Caddy terminates HTTPS for both domains automatically via Let's Encrypt.
A named volume (`hydrashield_data`) persists the SQLite cache and the
watch/alert database across deploys.

## Environment configuration (optional)

Create `/opt/hydrashield/.env` (never commit it) to enable optional layers:

```bash
FIRMS_MAP_KEY=...        # free NASA FIRMS key -> real active-fire layer
SMTP_HOST=...            # alert email delivery for watches + verification emails
SMTP_PORT=587
SMTP_USER=...
SMTP_PASS=...
SMTP_FROM=...
HYDRASHIELD_SECRET_KEY=...   # `openssl rand -hex 32` — keeps session and
                             # email-verification tokens valid across deploys
```

Without these, everything still runs; the affected layers are reported as
unavailable in the analysis provenance instead of being simulated. Until
`SMTP_HOST` is set, transactional emails (verification, reset, alerts) are
NOT sent — they land as `.eml` files in `/data/outbox` on the
`hydrashield_data` volume (retrievable via
`docker exec hydrashield-api-1 ls /data/outbox`).

### Operator (Commercial Center) access

The Commercial Center (`/admin.html` + `/api/v2/admin/*`) is served only
after server-side authorization. To activate the operator account:

```bash
HYDRASHIELD_OPERATOR_EMAILS=info@talaix.com   # in /opt/hydrashield/.env
```

Then register `info@talaix.com` via the normal account flow
(verification email lands in the official mailbox) and sign in — the
account is promoted to the admin role at session resolution, audited as
`operator_promotion`. There is no endpoint or client path to set a role;
anonymous visitors get 401 and normal users 403 on every admin surface.

## Prerequisites

- A Vultr server running **Ubuntu 24.04 LTS** (1 vCPU / 4GB / 30GB is enough).
- Domain `talaix.com` managed at your DNS provider.
- Docker + Docker Compose installed on the server.

---

## Step 1 — Install Docker on the server

SSH into the server as root, then run:

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version
docker compose version
```

---

## Step 2 — Point DNS at the server

In your DNS provider, create these records pointing to the Vultr server IP
(`45.77.54.166`):

| Type | Name / Host | Value |
|------|-------------|-------|
| `A`  | `@` (apex)  | `45.77.54.166` |
| `A`  | `app`       | `45.77.54.166` |

> GitHub Pages hosting has been fully retired: Vultr is the only production
> deployment destination (the old `deploy-website.yml` Pages workflow and the
> `website/CNAME` file have been removed).

---

## Step 3 — Create the deploy directory

```bash
mkdir -p /opt/hydrashield
```

---

## Step 4 — Set up SSH key for GitHub Actions

1. On the server, generate a dedicated key (run as root):

   ```bash
   ssh-keygen -t ed25519 -C "github-actions-vultr" -f /root/.ssh/gh_actions -N ""
   cat /root/.ssh/gh_actions.pub >> /root/.ssh/authorized_keys
   ```

2. Print the **private** key and copy it:

   ```bash
   cat /root/.ssh/gh_actions
   ```

3. In GitHub repo → **Settings → Secrets and variables → Actions**, add three
   repository secrets:

   | Secret name | Value |
   |-------------|-------|
   | `VULTR_HOST` | `45.77.54.166` |
   | `VULTR_USER` | `root` |
   | `VULTR_SSH_KEY` | the **private** key contents (from step 2) |

---

## Step 5 — First deploy

Option A — push to GitHub and let Actions deploy (recommended):

```bash
git add .
git commit -m "Deploy Talaix to Vultr"
git push origin main
```

Option B — manual deploy directly on the server:

```bash
cd /opt/hydrashield
docker compose up -d --build
docker compose ps
```

The first build takes a few minutes (installing `geopandas`, `xgboost`, etc.).

---

## Step 6 — Verify

```bash
curl -I https://talaix.com
curl -I https://app.talaix.com
curl https://talaix.com/api/health
curl "https://talaix.com/api/analyze?location=Clervaux,%20Luxembourg"
```

Expected for the API: `{"status":"ok", ...}`; the analysis endpoint returns a
full real-data report with a provenance block.

---

## Everyday workflow (after setup)

Every time you change code on your machine:

```bash
git push origin main
```

GitHub Actions copies `hydra-shield-platform/` to `/opt/hydrashield` on the
server and runs `docker compose up -d --build`. The site updates automatically.

## Useful operational commands

```bash
cd /opt/hydrashield

# Watch logs
docker compose logs -f caddy
docker compose logs -f dash
docker compose logs -f api

# Rebuild a single service after code change
docker compose up -d --build dash

# Full restart
docker compose restart
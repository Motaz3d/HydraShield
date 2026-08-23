# Talaix — Development & Operations

This document describes how the Talaix project is developed, tested,
operated, and recovered. It contains **no secrets**. Credentials live only in
`~/.config/hydrashield/` on the operations machine (chmod 700/600), never in
this repository.

## Purpose

Talaix is an AI-driven Digital Twin for preemptive wildfire protection
via subsurface hydration barriers. It turns real Copernicus/EO data into
water-optimized protection blueprints. See `README.md` for the module map.

## Machine architecture

```
MacBook Pro  ──Tailscale SSH──▶  mtz (Linux Mint, home server)
                                      │  ~/projects/Talaix  (working clone)
                                      ▼
                              GitHub origin/main  (canonical source of truth)
                                      │  GitHub Actions (.github/workflows/deploy-vultr.yml)
                                      ▼
                              Vultr production  (talaix.com)
```

- **GitHub `origin/main`** is the canonical code history. Nothing exists only
  on a laptop.
- **mtz** is the permanent development/operations machine. It stays powered on
  and holds the complete working clone at `~/projects/Talaix`.
- **Mac** is a remote control/development interface (SSH or VS Code
  Remote-SSH to host `mtz`).
- **Vultr** is production. It is only touched by the GitHub Actions deploy
  workflow, and only when a real project change requires deployment.

## Local development (on mtz)

```bash
cd ~/projects/Talaix/hydra-shield-platform
source .venv/bin/activate

# Run the full test suite
python -m pytest tests/ -v

# Live real-data integration test (needs network)
python test_real_integration.py
```

Install deps (already done on mtz): `pip install -r requirements-dev.txt && pip install -e .`

## Git / synchronization policy

GitHub is the source of truth. mtz is the permanent working clone.

Normal workflow:

```bash
git status                 # ALWAYS inspect first
git pull --ff-only         # never merge commits, never force
# ... develop, run tests ...
git add -A && git commit -m "..."
git push origin main
```

Rules:
- **Never** `push --force`. **Never** `reset --hard` unless explicitly told.
- Before any pull: check `git status` for uncommitted work and
  `git log origin/main..HEAD` for unpushed commits. Preserve local work
  (commit or `git stash`) before syncing.
- If local and remote diverge, stop and reconcile deliberately — do not
  blindly overwrite either side.

## Docker / operations

```bash
cd ~/projects/Talaix/hydra-shield-platform
docker compose config          # validate
docker compose build           # build the platform image
docker compose up -d           # run: caddy(80/443) + dash(8050) + api(8051) + watch_checker
docker compose ps
docker compose logs -f --tail=50
```

Key local endpoints (API on 8051):

- `GET /api/health`
- `GET /api/analyze?lat=49.9&lon=6.03`
- `GET /api/risk-snapshot`
- `GET /api/risk-grid?south=49.9&west=5.9&north=50.1&east=6.1&n=5`
- `GET /api/history?lat=37.6&lon=-6.5&days=90`

Persistent data lives in the `hydrashield_data` named volume (`/data`,
SQLite cache/watch DB). Caddy's TLS state is in `caddy_data`/`caddy_config`.

**Local stack note:** on mtz the stack is for development/verification.
Production deployment goes through GitHub Actions only — do not redeploy
Vultr manually.

## Environment & secrets

- Template: `hydra-shield-platform/.env.example` (tracked, empty values).
- Real values: `~/.config/hydrashield/development.env` and `production.env`
  on mtz — outside the repo, `chmod 700` dir, `chmod 600` files.
- `.gitignore` already excludes `.env` / `.env.*` (except `.env.example`),
  `data/` runtime files, and `.venv/`. Keep it that way.
- Docker receives secrets only via compose `environment:` expansion from an
  untracked `.env` next to `docker-compose.yml` (or the environment).
- Optional vars (missing = layer reported UNAVAILABLE, never invented):
  `FIRMS_MAP_KEY` (free NASA FIRMS key), `SMTP_HOST/PORT/USER/PASS/FROM`
  (watch alert email), `HYDRASHIELD_CACHE_DB`.

## tmux persistent workspace (mtz)

```bash
hs-tmux        # attach to (or create) the 'hydrashield' session
```

Windows: `1 dev` (repo + venv) · `2 logs` (compose logs) · `3 git` · `4 docker`.
Detach with `Ctrl-b d`; the session survives SSH disconnects.

Helper commands on mtz (`~/.local/bin`):
- `hs-tmux` — persistent workspace
- `hs-backup` — backup non-Git runtime data (see below)

## Real-data policy (fundamental rule)

**REAL DATA ONLY.** Never introduce `Math.random()`/`np.random()`-fabricated
risk values, fake satellite observations, fake fire detections, fake
validation results, or invented confidence values. If a source is down, the
platform reports `UNAVAILABLE`. Every public value carries provenance
(observed / derived / modeled / forecast / unavailable).

## Backup & recovery

- **Code & history:** GitHub. Nothing code-related exists only on mtz.
- **Non-Git runtime data** (secrets in `~/.config/hydrashield/`, `data/`
  SQLite cache + trained models): `hs-backup` archives them to
  `~/backups/hydrashield/` (14 generations, chmod 600) and runs nightly via
  the user crontab. These archives contain secrets — they stay on mtz unless
  deliberately copied somewhere safe.
- **Regenerable, not backed up:** Docker images/volumes beyond `data/`,
  `.venv/`, pip/npm caches.

Recovery if mtz's disk fails:

1. New machine: install Docker (+Compose), Python 3.12 + venv, git, tmux,
   Tailscale; join the tailnet.
2. `git clone git@github.com:Motaz3d/HydraShield.git ~/projects/Talaix`
3. Restore the latest `hydrashield-backup-*.tar.gz` (secrets + `data/`).
4. `python3 -m venv .venv && pip install -r requirements-dev.txt && pip install -e .`
5. `pytest tests/ && python test_real_integration.py` to verify.
6. `docker compose up -d` if the local stack is wanted.

## Deployment

`.github/workflows/deploy-vultr.yml` deploys to Vultr over SSH using GitHub
secrets (`VULTR_HOST`, `VULTR_USER`, `VULTR_SSH_KEY`). Deploy only on real
changes to `main` that need to ship. Do not deploy merely because the dev
environment changed.

## Kimi on mtz

Kimi Code CLI is installed at `~/.kimi-code/bin/kimi` (on PATH via
`.bashrc`/`.profile`) and is authenticated. It can maintain, test, and
operate this repository autonomously when given instructions, under the
policies above (real data only, no force-push, no secrets in the repo).

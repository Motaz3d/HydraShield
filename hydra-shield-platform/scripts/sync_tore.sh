#!/usr/bin/env bash
# sync_tore.sh — mirror the Talaix analytical engine into the public tore repo.
#
# Binding rule (root AGENTS.md): every change to the analytical engine in
# this monorepo must be mirrored to the public open-source repository
# (github.com/Motaz3d/tore). This script does the copy; run it after any
# engine change, then commit + push in the tore checkout (or pass --push).
#
# Usage:
#   scripts/sync_tore.sh            # sync files, show tore git status
#   scripts/sync_tore.sh --push     # sync + commit + push (message required)
#   TORE_REPO=/path/to/tore scripts/sync_tore.sh
#
# The mirrored set is the analytical engine ONLY: tx_core, src.climate
# (minus the api_*.py web blueprints), src.prediction, src.gis_mapping, the
# analytical data-pipeline modules of src.dashboard, src.hydration_control,
# the knowledge registries they load, and the engine docs/tests. The web
# layer (Flask app, accounts, billing, marketing, api blueprints) never
# leaves this monorepo.
set -euo pipefail

MONOREPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TORE_REPO="${TORE_REPO:-$MONOREPO/../../tore}"
PUSH=0
MESSAGE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --push) PUSH=1 ;;
        -m|--message) shift; MESSAGE="${1:-}" ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ ! -d "$TORE_REPO/.git" ]; then
    echo "tore checkout not found at $TORE_REPO (set TORE_REPO)" >&2
    exit 1
fi

RSYNC=(rsync -a --delete --exclude=__pycache__ --exclude='*.pyc')

# Engine packages (full).
"${RSYNC[@]}" "$MONOREPO/tx_core" "$TORE_REPO/"
"${RSYNC[@]}" "$MONOREPO/src/prediction" "$MONOREPO/src/gis_mapping" "$TORE_REPO/src/"
"${RSYNC[@]}" "$MONOREPO/src/hydration_control" "$TORE_REPO/src/"
"${RSYNC[@]}" --exclude='api_*.py' "$MONOREPO/src/climate" "$TORE_REPO/src/"
"${RSYNC[@]}" "$MONOREPO/src/__init__.py" "$TORE_REPO/src/"

# Analytical data-pipeline modules of src.dashboard (the web app stays here).
DASH_MODULES=(cache change crime_stats ecology explain exposure fire_evidence
              grid history ignition micro population real_analysis real_data
              recommendations scenarios site_image smoke snapshot
              verification_store)
mkdir -p "$TORE_REPO/src/dashboard"
cp "$MONOREPO/src/dashboard/__init__.py" "$TORE_REPO/src/dashboard/"
for m in "${DASH_MODULES[@]}"; do
    cp "$MONOREPO/src/dashboard/$m.py" "$TORE_REPO/src/dashboard/"
done
# Drop any dashboard file that no longer exists upstream.
for f in "$TORE_REPO"/src/dashboard/*.py; do
    base="$(basename "$f" .py)"
    [ "$base" = "__init__" ] && continue
    keep=0
    for m in "${DASH_MODULES[@]}"; do [ "$m" = "$base" ] && keep=1; done
    [ "$keep" = 0 ] && rm -f "$f"
done

# Knowledge registries loaded by the engine + the engine contract doc.
CONFIGS=(loss_registry.json model_registry.json loss_estimate_benchmarks.json
         cascading_graph.json)
for c in "${CONFIGS[@]}"; do
    cp "$MONOREPO/config/$c" "$TORE_REPO/config/"
done
cp "$MONOREPO/docs/TX_ENGINE.md" "$TORE_REPO/docs/"

# Mirrored tests (network-free subset that passes against the engine alone).
cp "$MONOREPO/tests/test_climate_core.py" "$TORE_REPO/tests/"
cp "$MONOREPO/tests/test_tx_reproduce.py" "$TORE_REPO/tests/"
# The monorepo test imports its fakes from tests.test_tx_core (which needs
# the web app); the mirror carries an equivalent fakes module instead.
sed -i '' 's/from tests.test_tx_core import FakeHazardModule, make_engine/from fakes import FakeHazardModule, make_engine/' \
    "$TORE_REPO/tests/test_tx_reproduce.py"

echo "synced -> $TORE_REPO"
cd "$TORE_REPO"
if [ "$PUSH" = 1 ]; then
    [ -z "$MESSAGE" ] && { echo "--push needs -m <message>" >&2; exit 2; }
    git add -A
    git commit -m "$MESSAGE"
    git push
    echo "pushed to origin"
else
    git status --short
fi

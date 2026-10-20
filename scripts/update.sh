#!/usr/bin/env bash
# Pull latest from origin; if HEAD changed, reinstall deps and restart. Rolls back on failed health check.
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${PITV_BRANCH:-main}"
REMOTE_URL="${PITV_REMOTE_URL:-https://github.com/nizn1770/multimediaDisplay.git}"
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE_URL"
git fetch --quiet origin "$BRANCH"
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && { echo "up to date ($OLD)"; exit 0; }
echo "updating $OLD -> $NEW"
git reset --hard "$NEW"   # local edits on the Pi are overwritten; config.yaml/secrets/cache are gitignored
if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then .venv/bin/pip install -q -r requirements.txt; fi
sudo systemctl restart pitv.service
for _ in $(seq 1 20); do curl -fs http://127.0.0.1:8080/healthz >/dev/null && { echo ok; exit 0; }; sleep 1; done
echo "health check failed; rolling back to $OLD" >&2
git reset --hard "$OLD"; sudo systemctl restart pitv.service; exit 1

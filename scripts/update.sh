#!/usr/bin/env bash
# Auto-update: fetch origin; if it moved, reset to it, reinstall deps if needed, restart, health-check.
# Any failure after the reset rolls back to the previous commit (trap) and records the bad SHA in
# .pitv-bad-commit so it is not redeployed every run; it is retried only once origin moves past it.
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${PITV_BRANCH:-main}"
REMOTE_URL="${PITV_REMOTE_URL:-https://github.com/nizn1770/multimediaDisplay.git}"
BAD_FILE=.pitv-bad-commit
RESTART="${PITV_RESTART_CMD:-sudo systemctl restart pitv.service}"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
if [ -n "${PITV_PORT:-}" ]; then PORT=$PITV_PORT
elif ! PORT=$(./pitv get server.port 2>/dev/null) || [ -z "$PORT" ]; then
  echo "WARNING: could not read server.port from config (./pitv get failed); assuming 8080" >&2; PORT=8080
fi
HEALTH_TRIES="${PITV_HEALTH_TRIES:-30}"
healthy() {
  for _ in $(seq 1 "$HEALTH_TRIES"); do
    curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null && return 0
    sleep 1
  done
  return 1
}

git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE_URL"
git fetch --quiet origin "$BRANCH"
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && { echo "up to date ($OLD)"; exit 0; }
if [ -f "$BAD_FILE" ] && [ "$(cat "$BAD_FILE")" = "$NEW" ]; then
  echo "skipping $NEW: failed to deploy earlier (delete $BAD_FILE to retry)"; exit 0
fi

echo "updating $OLD -> $NEW"
rollback() {
  local rc=$?
  trap - ERR EXIT
  [ "$rc" -eq 0 ] && return 0
  echo "deploy of $NEW failed (rc=$rc); rolling back to $OLD" >&2
  echo "$NEW" > "$BAD_FILE"
  git reset --hard --quiet "$OLD"
  .venv/bin/pip install -q -r requirements.txt >/dev/null 2>&1 || true
  $RESTART || echo "rollback: restart command failed" >&2
  if healthy; then echo "rollback: $OLD is healthy on port $PORT" >&2
  else echo "rollback: WARNING $OLD is NOT healthy on port $PORT after rollback; check journalctl -u pitv" >&2; fi
  exit "$rc"
}
trap rollback EXIT
git reset --hard --quiet "$NEW"   # tracked files only; config.local.yaml/secrets/cache are gitignored
if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then .venv/bin/pip install -q -r requirements.txt; fi
$RESTART
healthy || { echo "health check failed on port $PORT" >&2; exit 1; }
rm -f "$BAD_FILE"
trap - EXIT
echo "deployed $NEW"

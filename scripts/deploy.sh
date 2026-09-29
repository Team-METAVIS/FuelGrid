#!/usr/bin/env bash
# Health-gated deploy with automatic rollback.
#
#   bash scripts/deploy.sh            # deploy the current commit
#   bash scripts/deploy.sh <tag>      # deploy (or roll back to) a specific image tag
#
# Every build is tagged fuelgrid:<git sha>, so each deployment is versioned and any earlier one can be restored.
# The new version must report itself healthy (right build, data source healthy) within HEALTH_TIMEOUT seconds;
# otherwise the previous version is started again and the script exits non-zero.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:-$(git rev-parse --short HEAD)}"
HOST="${FUELGRID_URL:-http://127.0.0.1:8080}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"

current_tag() {  # tag of the running fuelgrid container, empty if none
  local id
  id="$(docker compose ps -q fuelgrid 2>/dev/null || true)"
  [ -n "$id" ] && docker inspect --format '{{.Config.Image}}' "$id" 2>/dev/null | sed 's/^fuelgrid://' || true
}

healthy() {  # $1 = expected build tag
  local body
  body="$(curl -sf -m 3 "$HOST/api/health" || true)"
  [ -n "$body" ] || return 1
  echo "$body" | grep -q "\"build\":\"$1\"" || return 1
  echo "$body" | grep -q '"data_source":{"status":"healthy"'
}

wait_healthy() {  # $1 = expected build tag
  local i
  for i in $(seq 1 "$HEALTH_TIMEOUT"); do
    if healthy "$1"; then return 0; fi
    sleep 1
  done
  return 1
}

PREV="$(current_tag)"
echo "deploy: current=${PREV:-none} target=$TAG"

if ! docker image inspect "fuelgrid:$TAG" >/dev/null 2>&1; then
  GIT_SHA="$TAG" docker compose build fuelgrid
fi
GIT_SHA="$TAG" docker compose up -d --no-build simulator fuelgrid

if wait_healthy "$TAG"; then
  echo "deploy: fuelgrid:$TAG is healthy"
  exit 0
fi

echo "deploy: fuelgrid:$TAG did not become healthy within ${HEALTH_TIMEOUT}s" >&2
docker compose logs --tail 40 fuelgrid >&2 || true
if [ -n "$PREV" ] && [ "$PREV" != "$TAG" ]; then
  echo "deploy: rolling back to fuelgrid:$PREV" >&2
  GIT_SHA="$PREV" docker compose up -d --no-build fuelgrid
  if wait_healthy "$PREV"; then
    echo "deploy: rollback to fuelgrid:$PREV succeeded" >&2
  else
    echo "deploy: rollback to fuelgrid:$PREV is not healthy either" >&2
  fi
fi
exit 1

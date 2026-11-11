#!/usr/bin/env bash
# =============================================================================
# Remote deployment for prompt-folio. Runs on the production host, called by CI
# (.github/workflows/ci.yml) over SSH after docker-compose.yml was synced.
#
# Environment:
#   IMAGE_TAG - image tag to roll out (CI passes the commit SHA; default 'latest')
#
# The host must already be logged in to the registry (docker login) and hold the
# .env file next to docker-compose.yml. If the new container does not become
# healthy, the previously deployed tag is started again and the script fails.
# =============================================================================

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEPLOY_DIR"

CONTAINER="prompt-folio-web"
NEW_TAG="${IMAGE_TAG:-latest}"
PREVIOUS_TAG="$(cat .deployed_image_tag 2>/dev/null || true)"

if [ ! -f .env ]; then
    echo "ERROR: $DEPLOY_DIR/.env is missing; create it from .env.example first."
    exit 1
fi

# Uploaded documents and the SQLite database; the container runs as uid 999
mkdir -p ./private
chown -R 999:999 ./private 2>/dev/null || echo "WARNING: could not chown ./private to 999:999"

start_tag() {
    echo "Pulling and starting image tag $1..."
    IMAGE_TAG="$1" docker compose pull -q
    IMAGE_TAG="$1" docker compose up -d --remove-orphans
}

# Waits for the container's HEALTHCHECK (GET /health) to report healthy.
wait_healthy() {
    local status=""
    for _ in $(seq 1 30); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || echo missing)"
        case "$status" in
            healthy) echo "Container $CONTAINER is healthy."; return 0 ;;
            unhealthy|exited|dead|missing) break ;;
        esac
        sleep 2
    done
    echo "ERROR: $CONTAINER is '$status' (expected 'healthy')."
    docker logs "$CONTAINER" --tail 50 || true
    return 1
}

start_tag "$NEW_TAG"

if wait_healthy; then
    echo "$NEW_TAG" > .deployed_image_tag
    docker image prune -f
    echo "Deployed $NEW_TAG."
    exit 0
fi

if [ -n "$PREVIOUS_TAG" ] && [ "$PREVIOUS_TAG" != "$NEW_TAG" ]; then
    echo "Rolling back to $PREVIOUS_TAG..."
    start_tag "$PREVIOUS_TAG"
    if wait_healthy; then
        echo "Rolled back to $PREVIOUS_TAG; $NEW_TAG was NOT deployed."
    else
        echo "ERROR: rollback to $PREVIOUS_TAG is unhealthy as well."
    fi
fi
exit 1

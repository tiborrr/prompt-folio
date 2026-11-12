#!/usr/bin/env bash
# =============================================================================
# Remote deployment for prompt-folio. Runs on the production host as the SSH
# forced command of the CI deploy key (see README, "Server setup"), so that key
# can do nothing but roll out an image:
#
#   command="/home/deploy/deployments/prompt-folio/scripts/deploy_remote.sh",restrict ssh-ed25519 ...
#
# CI connects with the commit SHA as the only "command"; sshd passes it in
# SSH_ORIGINAL_COMMAND. Run by hand, pass the tag as the first argument.
# Only a full 40-character commit SHA is accepted.
#
# The host must already be logged in to the registry (docker login) and hold
# docker-compose.yml and .env in this directory. If the new container does not
# become healthy, the previously deployed tag is started again and the script fails.
# =============================================================================

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEPLOY_DIR"

CONTAINER="prompt-folio-web"
NEW_TAG="${SSH_ORIGINAL_COMMAND:-${1:-}}"
if [[ ! "$NEW_TAG" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: expected a 40-character commit SHA as image tag."
    exit 2
fi
PREVIOUS_TAG="$(cat .deployed_image_tag 2>/dev/null || true)"

for required in .env docker-compose.yml; do
    if [ ! -f "$required" ]; then
        echo "ERROR: $DEPLOY_DIR/$required is missing (see README, \"Server setup\")."
        exit 1
    fi
done

# Uploaded documents and the SQLite database; the container runs as uid 999.
# Created once during server setup (needs root for the chown).
if [ ! -d ./private ]; then
    echo "ERROR: $DEPLOY_DIR/private is missing (see README, \"Server setup\")."
    exit 1
fi

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

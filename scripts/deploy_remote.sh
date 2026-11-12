#!/usr/bin/env bash
# =============================================================================
# Generic remote deployment for docker compose apps. Installed once on the
# server as /usr/local/bin/deploy-app (owned by root) and used by every app.
#
# Each app's CI deploy key is pinned to this script with the app name fixed in
# authorized_keys (SSH forced command), so a key can only roll out its own app:
#
#   command="/usr/local/bin/deploy-app prompt-folio",restrict ssh-ed25519 AAAA... deploy@prompt-folio
#
# CI connects with the commit SHA as the only "command"; sshd passes it in
# SSH_ORIGINAL_COMMAND. By hand: deploy-app <app> <commit-sha>
#
# The app lives in $DEPLOY_ROOT/<app> (default ~/deployments/<app>) with a
# docker-compose.yml whose image tag is ${IMAGE_TAG} and a .env file. The user
# running this must be logged in to the registry (docker login). If the new
# containers do not become healthy, the previously deployed tag is started
# again and the script fails.
# =============================================================================

set -euo pipefail

APP="${1:-}"
NEW_TAG="${SSH_ORIGINAL_COMMAND:-${2:-}}"

if [[ ! "$APP" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "ERROR: invalid app name '$APP'."
    exit 2
fi
if [[ ! "$NEW_TAG" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: expected a 40-character commit SHA as image tag."
    exit 2
fi

DEPLOY_DIR="${DEPLOY_ROOT:-$HOME/deployments}/$APP"
if [ ! -d "$DEPLOY_DIR" ]; then
    echo "ERROR: $DEPLOY_DIR does not exist."
    exit 1
fi
cd "$DEPLOY_DIR"

for required in .env docker-compose.yml; do
    if [ ! -f "$required" ]; then
        echo "ERROR: $DEPLOY_DIR/$required is missing."
        exit 1
    fi
done

PREVIOUS_TAG="$(cat .deployed_image_tag 2>/dev/null || true)"

start_tag() {
    echo "[$APP] Pulling and starting image tag $1..."
    export IMAGE_TAG="$1"
    docker compose pull -q
    docker compose up -d --remove-orphans
}

# Waits until every container of the compose project is healthy (or running,
# for containers without a HEALTHCHECK).
wait_healthy() {
    local ids status pending
    for _ in $(seq 1 30); do
        ids="$(docker compose ps -aq)"
        if [ -z "$ids" ]; then
            echo "ERROR: no containers found."
            return 1
        fi
        pending=0
        for id in $ids; do
            status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
            case "$status" in
                healthy|running) ;;
                starting|created|restarting) pending=1 ;;
                *)
                    echo "ERROR: container $id is '$status'."
                    docker logs "$id" --tail 50 || true
                    return 1
                    ;;
            esac
        done
        if [ "$pending" -eq 0 ]; then
            echo "[$APP] All containers are healthy."
            return 0
        fi
        sleep 2
    done
    echo "ERROR: containers did not become healthy in time."
    docker compose ps
    docker compose logs --tail 50 || true
    return 1
}

start_tag "$NEW_TAG"

if wait_healthy; then
    echo "$NEW_TAG" > .deployed_image_tag
    docker image prune -f
    echo "[$APP] Deployed $NEW_TAG."
    exit 0
fi

if [ -n "$PREVIOUS_TAG" ] && [ "$PREVIOUS_TAG" != "$NEW_TAG" ]; then
    echo "[$APP] Rolling back to $PREVIOUS_TAG..."
    start_tag "$PREVIOUS_TAG"
    if wait_healthy; then
        echo "[$APP] Rolled back to $PREVIOUS_TAG; $NEW_TAG was NOT deployed."
    else
        echo "ERROR: rollback to $PREVIOUS_TAG is unhealthy as well."
    fi
fi
exit 1

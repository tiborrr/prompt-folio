#!/bin/bash
set -euo pipefail

# Pinned versions: bump them on purpose so a build never picks up an unreviewed release.
HTMX_VERSION="2.0.11"
RESPONSE_TARGETS_VERSION="2.0.4"
SSE_VERSION="2.2.4"

DEST_DIR="app/static/js/htmx"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

echo "Downloading HTMX core..."
curl -fsSL --retry 4 --retry-all-errors --connect-timeout 15 --max-time 120 -o "$DEST_DIR/htmx.min.js" "https://unpkg.com/htmx.org@${HTMX_VERSION}/dist/htmx.min.js"
curl -fsSL --retry 4 --retry-all-errors --connect-timeout 15 --max-time 120 -o "$DEST_DIR/response-targets.js" "https://unpkg.com/htmx-ext-response-targets@${RESPONSE_TARGETS_VERSION}/response-targets.js"
curl -fsSL --retry 4 --retry-all-errors --connect-timeout 15 --max-time 120 -o "$DEST_DIR/sse.js" "https://unpkg.com/htmx-ext-sse@${SSE_VERSION}/sse.js"

echo "HTMX and extensions downloaded successfully to $DEST_DIR/"

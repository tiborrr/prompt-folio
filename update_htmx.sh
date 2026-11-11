#!/bin/bash
set -euo pipefail

# Pinned versions: bump them on purpose so a build never picks up an unreviewed release.
HTMX_VERSION="2.0.11"
RESPONSE_TARGETS_VERSION="2.0.0"
SSE_VERSION="2.2.2"

DEST_DIR="app/static/js/htmx"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

echo "Downloading HTMX core..."
curl -fsSL -o "$DEST_DIR/htmx.min.js" "https://unpkg.com/htmx.org@${HTMX_VERSION}/dist/htmx.min.js"
curl -fsSL -o "$DEST_DIR/response-targets.js" "https://unpkg.com/htmx-ext-response-targets@${RESPONSE_TARGETS_VERSION}/response-targets.js"
curl -fsSL -o "$DEST_DIR/sse.js" "https://unpkg.com/htmx-ext-sse@${SSE_VERSION}/sse.js"

echo "HTMX and extensions downloaded successfully to $DEST_DIR/"

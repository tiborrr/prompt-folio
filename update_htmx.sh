#!/bin/bash
set -e

DEST_DIR="app/static/js/htmx"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

echo "Downloading HTMX core..."
curl -L -o app/static/js/htmx/htmx.min.js https://unpkg.com/htmx.org/dist/htmx.min.js
curl -L -o app/static/js/htmx/response-targets.js https://unpkg.com/htmx-ext-response-targets@2.0.0/response-targets.js
curl -L -o app/static/js/htmx/sse.js https://unpkg.com/htmx-ext-sse@2.2.2/sse.js

echo "HTMX and extensions downloaded successfully to app/static/js/htmx/"

#!/bin/bash
set -euo pipefail

# Pinned version: bump it on purpose and check the avatar cropper still works.
# Cropper.js 2.x is built from web components with their styles in shadow DOM,
# so there is no separate stylesheet.
CROPPER_VERSION="2.3.1"

DEST_DIR="app/static/js/cropper"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

echo "Downloading Cropper.js..."
curl -fsSL --retry 4 --retry-all-errors --connect-timeout 15 --max-time 120 \
    -o "$DEST_DIR/cropper.min.js" \
    "https://cdn.jsdelivr.net/npm/cropperjs@${CROPPER_VERSION}/dist/cropper.min.js"

echo "Cropper.js downloaded successfully to $DEST_DIR/"

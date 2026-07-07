#!/bin/bash
set -e

DEST_DIR="app/static/js/cropper"
CSS_DEST_DIR="app/static/css/cropper"

echo "Creating directories..."
mkdir -p "$DEST_DIR"
mkdir -p "$CSS_DEST_DIR"

echo "Downloading Cropper.js..."
curl -L -o "$DEST_DIR/cropper.min.js" https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js
curl -L -o "$CSS_DEST_DIR/cropper.min.css" https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css

echo "Cropper.js downloaded successfully to local static directories."

#!/bin/bash
set -e

DEST_DIR="app/static/js/editorjs"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

echo "Downloading Editor.js core..."
curl -sL "https://cdn.jsdelivr.net/npm/@editorjs/editorjs@latest/dist/editor.js" -o "$DEST_DIR/editor.js"

echo "Downloading Editor.js Header plugin..."
curl -sL "https://cdn.jsdelivr.net/npm/@editorjs/header@latest/dist/bundle.js" -o "$DEST_DIR/header.js"

echo "Downloading Editor.js List plugin..."
curl -sL "https://cdn.jsdelivr.net/npm/@editorjs/list@latest/dist/bundle.js" -o "$DEST_DIR/list.js"

echo "Downloading Editor.js Undo plugin..."
curl -sL "https://cdn.jsdelivr.net/npm/editorjs-undo@latest/dist/bundle.js" -o "$DEST_DIR/undo.js"

echo "Downloading Editor.js Code plugin..."
curl -sL "https://cdn.jsdelivr.net/npm/@editorjs/code@latest/dist/bundle.js" -o "$DEST_DIR/code.js"

echo "Downloading Editor.js Delimiter plugin..."
curl -sL "https://cdn.jsdelivr.net/npm/@editorjs/delimiter@latest/dist/bundle.js" -o "$DEST_DIR/delimiter.js"

echo "Done! Editor.js dependencies have been downloaded."

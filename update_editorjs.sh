#!/bin/bash
set -euo pipefail

# Pinned versions. These are the builds `@latest` resolved to on jsDelivr when
# they were pinned (newer releases no longer ship these file names). Bump them
# on purpose and check the context editor still works.
EDITORJS_VERSION="2.26.5"
HEADER_VERSION="2.7.0"
LIST_VERSION="1.8.0"
UNDO_VERSION="2.0.28"
CODE_VERSION="2.8.0"
DELIMITER_VERSION="1.3.0"

DEST_DIR="app/static/js/editorjs"
CDN="https://cdn.jsdelivr.net/npm"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

fetch() {
    echo "Downloading $1..."
    curl -fsSL "$CDN/$1" -o "$DEST_DIR/$2"
}

fetch "@editorjs/editorjs@${EDITORJS_VERSION}/dist/editor.js" editor.js
fetch "@editorjs/header@${HEADER_VERSION}/dist/bundle.js" header.js
fetch "@editorjs/list@${LIST_VERSION}/dist/bundle.js" list.js
fetch "editorjs-undo@${UNDO_VERSION}/dist/bundle.js" undo.js
fetch "@editorjs/code@${CODE_VERSION}/dist/bundle.js" code.js
fetch "@editorjs/delimiter@${DELIMITER_VERSION}/dist/bundle.js" delimiter.js

echo "Done! Editor.js dependencies have been downloaded."

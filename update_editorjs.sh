#!/bin/bash
set -euo pipefail

# Pinned versions: bump them on purpose and check the context editor still works.
# The packages ship UMD builds; each one defines a global that context-editor.js
# uses (EditorJS, Header, EditorjsList, CodeTool, Delimiter, Undo).
EDITORJS_VERSION="2.31.7"
HEADER_VERSION="2.8.9"
LIST_VERSION="2.0.9"
UNDO_VERSION="2.0.28"
CODE_VERSION="2.9.4"
DELIMITER_VERSION="1.4.2"

DEST_DIR="app/static/js/editorjs"
CDN="https://cdn.jsdelivr.net/npm"

echo "Creating directory $DEST_DIR..."
mkdir -p "$DEST_DIR"

fetch() {
    echo "Downloading $1..."
    curl -fsSL "$CDN/$1" -o "$DEST_DIR/$2"
}

fetch "@editorjs/editorjs@${EDITORJS_VERSION}/dist/editorjs.umd.js" editor.js
fetch "@editorjs/header@${HEADER_VERSION}/dist/header.umd.js" header.js
fetch "@editorjs/list@${LIST_VERSION}/dist/editorjs-list.umd.js" list.js
fetch "editorjs-undo@${UNDO_VERSION}/dist/bundle.js" undo.js
fetch "@editorjs/code@${CODE_VERSION}/dist/code.umd.js" code.js
fetch "@editorjs/delimiter@${DELIMITER_VERSION}/dist/delimiter.umd.js" delimiter.js

echo "Done! Editor.js dependencies have been downloaded."

#!/bin/bash
set -e

PKG_DIR="dist/StreamDeckCommander"
DMG_NAME="StreamDeckCommander.dmg"

rm -rf "$PKG_DIR" "$DMG_NAME"
mkdir -p "$PKG_DIR"

# Copy project files
rsync -av --exclude='.git' --exclude='dist' --exclude='scripts/OLD' --exclude='scripts/TXT' . "$PKG_DIR"

cd "$PKG_DIR"

# Build the virtual environment inside the package
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate
fi
cd ../..

# Create the DMG (requires create-dmg)
if command -v create-dmg >/dev/null 2>&1; then
    create-dmg --volname "StreamDeckCommander" --window-pos 200 120 --window-size 800 400 --icon-size 100 --app-drop-link 600 185 "$DMG_NAME" "$PKG_DIR"
else
    echo "create-dmg not found. Install it or build the DMG manually."
fi

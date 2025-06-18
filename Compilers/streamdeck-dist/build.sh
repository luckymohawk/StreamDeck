#!/bin/bash

# This script automates the entire build and packaging process for the
# Streamdeck Commander application.
#
# It performs the following steps:
# 1. Cleans up any previous build artifacts.
# 2. Builds the ReactJS frontend for the configuration UI.
# 3. Sets the necessary permissions on the launcher script.
# 4. Runs PyInstaller to create the .app bundle.
# 5. Packages the .app into a distributable .dmg file with a custom background.
#
# Prerequisite: You must have 'create-dmg' installed.
# If you don't have it, run: brew install create-dmg

# --- Configuration ---
set -e # Exit immediately if a command exits with a non-zero status.

APP_NAME="Streamdeck Commander"
SPEC_FILE="streamdeck.spec"
DMG_BACKGROUND="dmg-background.png"
FINAL_DMG_NAME="${APP_NAME}.dmg"
DIST_DIR="dist"
SRC_APP_PATH="${DIST_DIR}/${APP_NAME}.app"

# --- Build Process ---

echo "--- 1. Cleaning up old build artifacts ---"
rm -rf "${DIST_DIR}"
rm -rf build
rm -f "${FINAL_DMG_NAME}"
echo "Cleanup complete."
echo

echo "--- 2. Building React Frontend ---"
# Navigate to the frontend directory, build, and return
if [ -d "browsebuttons" ]; then
  cd browsebuttons
  echo "Installing frontend dependencies..."
  npm install
  echo "Building frontend..."
  npm run build
  cd ..
  echo "Frontend build complete."
else
  echo "[ERROR] 'browsebuttons' directory not found. Cannot build frontend."
  exit 1
fi
echo

echo "--- 3. Setting Launcher Script Permissions ---"
if [ -f "source/run.sh" ]; then
  chmod +x source/run.sh
  echo "Launcher script is now executable."
else
  echo "[ERROR] 'source/run.sh' not found. Please create it first."
  exit 1
fi
echo

echo "--- 4. Running PyInstaller to create .app bundle ---"
pyinstaller "${SPEC_FILE}"
echo ".app bundle created successfully."
echo

echo "--- 5. Packaging application into a DMG ---"
if ! [ -x "$(command -v create-dmg)" ]; then
  echo "[ERROR] 'create-dmg' command not found." >&2
  echo "Please install it to continue: brew install create-dmg" >&2
  exit 1
fi

if [ ! -d "${SRC_APP_PATH}" ]; then
    echo "[ERROR] Source application not found at ${SRC_APP_PATH}" >&2
    exit 1
fi

create-dmg \
  --volname "${APP_NAME}" \
  --background "${DMG_BACKGROUND}" \
  --window-pos 200 120 \
  --window-size 800 525 \
  --icon-size 128 \
  --icon "${APP_NAME}.app" 250 250 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 550 250 \
  "${FINAL_DMG_NAME}" \
  "${DIST_DIR}/"

echo "DMG created successfully."
echo

# --- Final ---
echo "✅ Build Complete!"
echo "Your distributable disk image is ready at: ./${FINAL_DMG_NAME}"

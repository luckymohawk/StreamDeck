#!/bin/bash

APP_NAME="Streamdeck Commander"
VOL_NAME="${APP_NAME}"
DMG_NAME="${APP_NAME}.dmg"
SOURCE_DIR="./source"
ENTITLEMENTS_FILE="entitlements.plist"

echo "--- Starting Self-Contained App Build Process ---"

# --- 0. Pre-flight Check ---
if [ ! -f "${ENTITLEMENTS_FILE}" ]; then
    echo "ERROR: Entitlements file '${ENTITLEMENTS_FILE}' not found. Aborting."
    exit 1
fi
if [ ! -d "${SOURCE_DIR}/browsebuttons" ]; then
    echo "ERROR: React source directory '${SOURCE_DIR}/browsebuttons' not found. Aborting."
    exit 1
fi

# --- 1. Build the React Frontend ---
echo "\n--> Building the static React UI..."
(cd "${SOURCE_DIR}/browsebuttons" && npm install && npm run build)
if [ $? -ne 0 ]; then
    echo "ERROR: React build failed. Aborting."
    exit 1
fi

# --- 2. Build the macOS .app Bundle using py2app ---
echo "\n--> Building the .app bundle with py2app..."
python3 setup.py py2app
if [ $? -ne 0 ]; then
    echo "ERROR: py2app build failed. Aborting."
    exit 1
fi

# --- 3. Robust Code Signing ---
APP_PATH="dist/${APP_NAME}.app"
echo "\n--> Signing the application bundle with Hardened Runtime..."

SIGNING_IDENTITY="-"

echo "--> Signing nested code..."
find "${APP_PATH}" -type f \( -name "*.dylib" -o -name "*.so" \) -exec echo "Signing: {}" \; -exec codesign --force --sign "${SIGNING_IDENTITY}" --timestamp --options runtime {} \;
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to sign one or more dynamic libraries. Aborting."
    exit 1
fi

# Sign the main Python framework
echo "--> Signing Python framework..."
codesign --force --sign "${SIGNING_IDENTITY}" --timestamp --options runtime "${APP_PATH}/Contents/Frameworks/Python.framework/Versions/3.13/Python"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to sign the Python framework. Aborting."
    exit 1
fi

# Sign the main executable
echo "--> Signing main executable..."
codesign --force --sign "${SIGNING_IDENTITY}" --timestamp --options runtime --entitlements "${ENTITLEMENTS_FILE}" "${APP_PATH}/Contents/MacOS/${APP_NAME}"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to sign the main executable. Aborting."
    exit 1
fi

# Finally, sign the entire application bundle
echo "--> Signing the .app bundle..."
codesign --force --sign "${SIGNING_IDENTITY}" --timestamp --options runtime --entitlements "${ENTITLEMENTS_FILE}" "${APP_PATH}"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to sign the application bundle. Aborting."
    exit 1
fi

echo "--> Code signing complete."


# --- 4. Create a clean DMG staging directory ---
echo "\n--> Creating final DMG..."
STAGING_DIR="./dmg-staging"
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"
cp -R "${APP_PATH}" "${STAGING_DIR}/"
ln -s /Applications "${STAGING_DIR}/Applications"

# --- 5. Create the Disk Image ---
hdiutil create -srcfolder "${STAGING_DIR}" -volname "${VOL_NAME}" -fs HFS+ \
  -format UDZO -o "${DMG_NAME}"

# --- Final Cleanup ---
rm -rf ./dist ./build ./dmg-staging
rm -rf "${SOURCE_DIR}/browsebuttons/dist" # Remove the temporary react build
echo "\n--- Build successful ---"
echo "Final DMG is ready: ${PWD}/${DMG_NAME}"

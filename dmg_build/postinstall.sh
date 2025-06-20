#!/bin/zsh
set -e
echo "Starting StreamDeck Driver installation..."

SOURCE_DIR="$( cd "$( dirname "$0" )" && pwd )"
DEST_DIR="$HOME/Library/StreamdeckDriver"
NODE_FINAL_DIR="${DEST_DIR}/nodejs"

echo "Creating application directories..."
mkdir -p "${DEST_DIR}"
mkdir -p "${NODE_FINAL_DIR}"

ARCH=$(uname -m)
echo "Detected user architecture: ${ARCH}"
if [ "$ARCH" = "arm64" ]; then
    echo "Installing Apple Silicon (arm64) version of Node.js..."
    rsync -av "${SOURCE_DIR}/nodejs-arm64/" "${NODE_FINAL_DIR}/"
elif [ "$ARCH" = "x86_64" ]; then
    echo "Installing Intel (x64) version of Node.js..."
    rsync -av "${SOURCE_DIR}/nodejs-x64/" "${NODE_FINAL_DIR}/"
else
    echo "ERROR: Unsupported Mac architecture. Installation failed." && exit 1
fi

echo "Copying application program files..."
rsync -av "${SOURCE_DIR}/" "${DEST_DIR}/" --exclude 'nodejs-arm64' --exclude 'nodejs-x64' --exclude 'postinstall.sh' --exclude 'StreamDeck Commander.app'

# --- THE FIX: Use 'npm install' for better compatibility ---
echo "Configuring Web UI dependencies for your system. This may take a moment..."
WEB_UI_DIR="${DEST_DIR}/browsebuttons"
export PATH="${NODE_FINAL_DIR}/bin:${PATH}"
# Using 'npm install' is more robust for this use case than 'npm ci'
(cd "${WEB_UI_DIR}" && npm install)

echo "Installing launcher into Applications folder..."
cp -R "${SOURCE_DIR}/StreamDeck Commander.app" "/Applications/"
chmod +x "${DEST_DIR}/StreamDeckCommander.command"

echo "✅ Installation Complete!"
echo "The installer will now open System Settings for the final step."
sleep 2
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
exit 0
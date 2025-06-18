#!/bin/bash
set -e

APPDIR="$HOME/Library/StreamdeckDriver"

echo "Creating application directory at $APPDIR"
mkdir -p "$APPDIR"

echo "Copying application files..."
# Copy files excluding development artifacts.
EXCLUDES=(--exclude='.git' --exclude='scripts/OLD' --exclude='scripts/TXT')
# Only exclude the venv when it isn't bundled with the installer
if [ ! -d "./.venv" ]; then
    EXCLUDES+=(--exclude='.venv')
fi
rsync -av "${EXCLUDES[@]}" . "$APPDIR"

cd "$APPDIR"

if [ ! -d ".venv" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv .venv

    echo "Installing dependencies..."
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "Using bundled Python environment"
fi

echo "Setting executable permissions on launchers..."
chmod +x StreamDeckCommander.command launch_driver.sh

echo "Setup complete! Launch with StreamDeckCommander.command"

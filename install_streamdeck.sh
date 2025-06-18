#!/bin/bash
set -e

APPDIR="$HOME/Library/StreamdeckDriver"

echo "Creating application directory at $APPDIR"
mkdir -p "$APPDIR"

echo "Copying application files..."
# Copy all except scripts/OLD and scripts/TXT and .git/.venv
rsync -av --exclude='.git' --exclude='.venv' --exclude='scripts/OLD' --exclude='scripts/TXT' . "$APPDIR"

cd "$APPDIR"

echo "Setting up Python virtual environment..."
python3 -m venv .venv

echo "Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Setting executable permissions on launchers..."
chmod +x StreamDeckCommander.command launch_driver.sh

echo "Setup complete! Launch with StreamDeckCommander.command"

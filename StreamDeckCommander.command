#!/bin/bash

# This makes the script exit immediately if any command fails.
set -e

echo "--- StreamDeck Launcher Script Started ---"

# This line ensures the script runs from its own directory.
cd "$(dirname "$0")"
echo "Changed directory to: $(pwd)"

# Set the application directory
APP_DIR_LAUNCHER="$HOME/Library/StreamdeckDriver"
echo "Application directory set to: ${APP_DIR_LAUNCHER}"

# Check if the virtual environment exists before trying to activate it
if [ ! -f "${APP_DIR_LAUNCHER}/.venv/bin/activate" ]; then
    echo "[FATAL] Virtual environment not found at ${APP_DIR_LAUNCHER}/.venv/"
    echo "Please run the setup steps again."
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Activating virtual environment..."
source "${APP_DIR_LAUNCHER}/.venv/bin/activate"
echo "Virtual environment activated."

# Define the full path to the python executable and the driver script
PYTHON_EXEC="${APP_DIR_LAUNCHER}/.venv/bin/python"
DRIVER_SCRIPT="${APP_DIR_LAUNCHER}/streamdeck_driver.py"

echo "Python executable: ${PYTHON_EXEC}"
echo "Driver script: ${DRIVER_SCRIPT}"

if [ ! -f "${PYTHON_EXEC}" ]; then
    echo "[FATAL] Python executable not found in venv!"
    read -p "Press Enter to exit..."
    exit 1
fi

if [ ! -f "${DRIVER_SCRIPT}" ]; then
    echo "[FATAL] Driver script not found!"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Launching driver now..."
echo "------------------------------------------"

# Run the driver using the venv's Python executable
"${PYTHON_EXEC}" "${DRIVER_SCRIPT}"

echo "------------------------------------------"
echo "Driver script has finished or crashed."
# This line will keep the window open so you can read any errors.
read -p "Press [Enter] to close this window..."
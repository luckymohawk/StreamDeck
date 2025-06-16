#!/bin/zsh

# This line ensures the script runs from its own directory,
# making it runnable from anywhere.
cd "$(dirname "$0")"

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Launching Stream Deck Driver..."
python streamdeck_driver.py

echo "Driver has finished."

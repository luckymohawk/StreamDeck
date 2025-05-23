#!/usr/bin/env bash
# Activates the virtual environment and runs the Stream Deck driver
source "$HOME/Documents/GitHub/StreamDeck/venv/bin/activate"
python3 "$HOME/Documents/GitHub/StreamDeck/streamdeck_driver.py"
# Use python3 explicitly for clarity with venv

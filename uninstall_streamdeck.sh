#!/bin/bash
set -e

APPDIR="$HOME/Library/StreamdeckDriver"

if [ -d "$APPDIR" ]; then
    read -p "Remove $APPDIR and all contents? [y/N] " confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        rm -rf "$APPDIR"
        echo "StreamDeck Commander uninstalled."
    else
        echo "Aborted."
    fi
else
    echo "No installation found at $APPDIR"
fi

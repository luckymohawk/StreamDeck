#!/bin/bash

# This script launches the actual Python executable inside a new Terminal window.

# Get the directory where this script is located.
# This will be .../Streamdeck Commander.app/Contents/MacOS
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# The name of the *real* executable created by PyInstaller.
# We will rename the Python executable to this in the .spec file.
REAL_EXECUTABLE="Streamdeck Commander_internal"

# Use osascript to tell the Terminal to open and run our real executable.
# This makes all the print() statements visible to the user.
osascript <<EOF
tell application "Terminal"
    reopen
    activate
    do script "'$DIR/$REAL_EXECUTABLE'"
end tell
EOF

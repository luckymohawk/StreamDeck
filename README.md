
# StreamDeck Commander

A macOS utility for managing Elgato Stream Deck buttons and automations.

## Features

- Control your Stream Deck from macOS
- Customizable button actions via AppleScript and shell commands
- Web UI for button management
- Easy setup with a single script

## Requirements

- macOS (tested on Ventura/Sonoma)
- Python 3.8+
- Elgato Stream Deck hardware

## Installation

1. Clone the repository and run the install script:

    ```sh
    git clone https://github.com/luckymohawk/StreamDeck.git
    cd StreamDeck
    ./install_streamdeck.sh
    ```

    This will:
    - Copy all necessary files to `~/Library/StreamdeckDriver`
    - Set up a Python virtual environment and install dependencies
    - Set permissions on launchers

## Running the App

After installation, launch the app with:

```sh
open ~/Library/StreamdeckDriver/StreamDeckCommander.command
Or double-click StreamDeckCommander.command in Finder.

Packaging a DMG (Optional)

To distribute as a DMG:

Install create-dmg (or use Disk Utility).

Copy these items into a packaging directory:

StreamDeckCommander.command
All Python files
The scripts/ directory (except scripts/OLD and scripts/TXT)
requirements.txt
install_streamdeck.sh
Any icons or assets needed
Exclude: .venv/, .DS_Store, .git/, and any development folders.

Run (with create-dmg):

sh
create-dmg --volname "StreamDeckCommander" --window-pos 200 120 --window-size 800 400 --icon-size 100 --app-drop-link 600 185 ./StreamDeckCommander.dmg ./your_packaging_directory
Or use Disk Utility to create a disk image from your folder.

Uninstall

Remove everything by deleting the folder:

sh
rm -rf ~/Library/StreamdeckDriver
Contributing

Pull requests and issues are welcome!

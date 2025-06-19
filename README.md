
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
      (or use the bundled environment if present)
    - Set permissions on launchers

## Running the App

After installation, launch the app with:

```sh
open ~/Library/StreamdeckDriver/StreamDeckCommander.command
```

Or double-click `StreamDeckCommander.command` in Finder.

## Packaging a DMG

The `package_dmg.sh` script builds a DMG containing a pre-built Python
environment. `create-dmg` must be available on your system.

```sh
./package_dmg.sh
```

The resulting `StreamDeckCommander.dmg` can be distributed to other Macs.
After opening the DMG, double-click `install_streamdeck.sh` to copy
all required files to `~/Library/StreamdeckDriver`.

## Uninstall

Run the provided script to remove all installed files:

```sh
./uninstall_streamdeck.sh
```

This simply deletes `~/Library/StreamdeckDriver`.

## Contributing

Pull requests and issues are welcome!

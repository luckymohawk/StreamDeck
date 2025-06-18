# Streamdeck Commander for MacOS

This project provides a powerful, highly customizable background driver for the Elgato Stream Deck on macOS. It replaces the official software, offering deep integration with shell commands, AppleScript, and a configuration workflow based entirely in Apple Numbers.

It is managed via a local web UI and is designed for power users who want to control their Mac's command-line tools with the press of a button.

## Key Features

*   **Apple Numbers Configuration:** Configure all your buttons in a user-friendly `Streamdeck` sheet in Apple Numbers.
*   **Web-Based Management:** A lightweight, local web UI (`http://localhost:8765`) allows you to view your button layouts and variables in real-time.
*   **Powerful Flag System:** Augment buttons with simple flags to enable advanced features like device targeting, connection monitoring, background processes, and more.
*   **Variable Support:** Embed dynamic variables like `{{TAKE}}` or `{{IP_ADDRESS}}` directly into your commands. Edit them on the fly with a long-press.
*   **Automated Installer:** A simple, user-friendly `.dmg` installer handles all dependencies and background service setup.
*   **Launchd Service:** The driver runs as a persistent background service that starts automatically on login and restarts itself if it ever crashes.

## Installation

Installation is handled by the custom installer inside the `.dmg` package.

1.  Open the `.dmg` file.
2.  Double-click the **"Install Streamdeck Commander"** icon.
3.  A dialog box will explain the installation process. Click OK.
4.  You will be prompted to enter your administrator password in a standard macOS security dialog. This is required to install the application and authorize it.
5.  Once you see the "Success!" message, the application has been installed. **You must launch it once from your `/Applications` folder to start the background service.**

## How to Use

#### 1. Configure Your Buttons in Numbers
The first time you run the application, it should help you create a `Streamdeck` sheet in a new Apple Numbers document.

*   **Open Apple Numbers:** Find the document with the "Streamdeck" sheet.
*   **Edit the "Commands" Table:** The columns are read in order:
    *   **Column A: Button Name:** The text that appears on the Stream Deck button.
    *   **Column B: Terminal Command:** The shell command to run. Use `{{variable}}` syntax for dynamic values.
    *   **Column C: Feature Flags:** Add flags from the list below to add special behaviors.
    *   **Column D: Monitoring Keyword:** If using the `?` flag, this is the text the driver looks for in the terminal output.

#### 2. Refresh the Driver
The driver does **not** automatically detect changes in Numbers. After you've configured your buttons, press the physical **LOAD** button on your Stream Deck (the top-left key) to pull in your new configuration.

#### 3. Use the Web UI
There are two ways to open the web interface:
*   **Easy Way:** **Long-press the `▼` button** on your Stream Deck.
*   **Manual Way:** Open a web browser and go to `http://localhost:8765`.

## Configuration: Feature Flags

Use these flags in the "Feature Flags" column (Column C) in Numbers to control button behavior.

| Flag | Name | Description |
| :--- | :--- | :--- |
| **`@`** | **Device Target** | Marks a button as a "target device." Other buttons send commands to this device's terminal. |
| **`~`** | **Monitor Connection** | Continuously monitors an `@` device's SSH connection, showing "CONNECTED" or "BROKEN". |
| **`*`** | **Record Button** | A stateful button. Short-press starts/stops the command. Long-press edits variables (`SCENE`, `RECPATH`). |
| **`?`** | **Keyword Monitor** | Runs a command and monitors its terminal output for the "Monitoring Keyword" from Column D. |
| **`#`** | **Numeric Adjust** | Long-press to enter a mode where `▲` and `▼` keys adjust a numeric variable in the command. |
| **`V`** | **Variable Edit** | Allows you to edit any `{{variable}}` in the command with a long-press. |
| **`T`** | **Sticky (Top)** | Pins the button to the top of the Stream Deck screen, regardless of pagination. |
| **`N`** | **New Window** | Forces the command to always execute in a new terminal window. |
| **`K`** | **Keep Local** | Forces a command to run locally, even if an `@` device is active. |
| **`M`** | **Mobile SSH** | Transforms an SSH command (e.g., `ssh root@host`) for a mobile context by changing the user to `mobile@`. |
| **`&`** | **Background Toggle**| Runs the command as a silent background process. Press again to terminate it. |
| **`>`** | **Confirm Action** | Displays a confirmation dialog before running the command. |
| **`1-99`**| **Font Size** | Sets the label's font size. This is just the number (e.g., `22`). Colors are separate flags. Default is 13. |
| **`D`** | **Dim Color** | Dims the selected base color (e.g., `GD` for dim green). |
| **`R,G,B,O,Y,P,S,F,W,L`** | **Colors** | Sets the button's background color (Red, Green, Blue, Orange, etc.). |

## Uninstallation

To completely remove the driver and all its components:

1.  Make sure "Streamdeck Commander" is not running.
2.  Drag **Streamdeck Commander.app** from your `/Applications` folder to the Trash.
3.  (Optional) To remove configuration files, open Finder, click `Go > Go to Folder...` from the menu bar, and enter `~/Library/Application Support/StreamdeckCommander`. Drag this folder to the Trash.

This will remove all related files from your system.

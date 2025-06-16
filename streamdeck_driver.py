#!/usr/bin/env python3

import os
import sys
import time
import textwrap
import re
import json
import sqlite3
import subprocess
import threading
import traceback
import platform
from pathlib import Path
from math import ceil
import shlex
import webbrowser

from flask import Flask, jsonify, request
from flask_cors import CORS
from functools import wraps

try:
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Transport.Transport import TransportError
    from StreamDeck.ImageHelpers import PILHelper
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Missing required Python package: {e.name}", file=sys.stderr)
    print("Install with: pip install streamdeck Pillow Flask Flask-CORS", file=sys.stderr)
    sys.exit(1)

if platform.system() != "Darwin":
    print("This script supports only macOS.", file=sys.stderr)
    sys.exit(1)

APP_DIR = Path.home() / "Library" / "StreamDeckDriver"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "streamdeck.db"
LOAD_SCRIPT = APP_DIR / "streamdeck_db.py"
SCRIPTS_DIR = APP_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
WEB_UI_DIR = APP_DIR / "browsebuttons"

REQUIRED_TEMPLATES = [
    "system_events_dialog.applescript",
    "system_events_confirm.applescript",
    "get_active_terminal_window.applescript",
    "activate_terminal_window.applescript",
    "terminal_check_text.applescript",
    "terminal_keystroke.applescript",
    "terminal_spawn_ssh_and_snapshot.applescript",
    "terminal_spawn_and_snapshot.applescript",
    "terminal_n_for_at_staged_keystroke.applescript",
    "get_window_content.applescript",
]
missing_templates = [
    t for t in REQUIRED_TEMPLATES
    if not (SCRIPTS_DIR / t).exists() and not (APP_DIR / t).exists()
]
if missing_templates:
    print("Missing AppleScript templates:", ", ".join(missing_templates), file=sys.stderr)
    sys.exit(1)

current_session_vars = {}
at_devices_to_reinit_cmd = set()
numeric_step_memory = {}
record_toggle_states = {}
background_processes = {}
monitor_states = {}
monitor_threads = {}
key_to_global_item_idx_map = {}
global_item_idx_to_key_map = {}
monitor_generations = {}

labels, cmds, flags = {}, {}, {}
page_index = 0
numeric_mode, numeric_var = False, None
active_device_key = None
press_times = {}
toggle_keys = set()
long_press_numeric_active = False
flash_state = False
deck = None
items = []
web_ui_process = None

monitor_lock = threading.Lock()
background_lock = threading.Lock()
record_toggle_lock = threading.Lock()

VAR_PATTERN = re.compile(r"\{\{([^:}]+)(:([^}]*))?\}\}")
SSH_USER_HOST_CMD_PATTERN = re.compile(
    r"^(ssh(?:\s+-[a-zA-Z0-9]+(?:\s+\S+)?)*)\s+(\S+)@(\S+)((?:\s+.*)?)$", re.IGNORECASE
)

POLL_INTERVAL = 0.3
LINE_SPACING = 2
VAR_LINE_SPACING = 1
DEFAULT_FONT_SIZE = 13
ARROW_FONT_SIZE = 24
LONG_PRESS_THRESHOLD = 1.0
FONT_PATH = "/System/Library/Fonts/SFNS.ttf"
BOLD_FONT_PATH = "/System/Library/Fonts/SFNSDisplay-Bold.otf"
BASE_COLORS = {
    'R': '#FF0000', 'G': '#00FF00', 'B': '#0066CC',
    'O': '#FF9900', 'Y': '#FFFF00', 'P': '#800080',
    'S': '#C0C0C0', 'F': '#FF00FF', 'W': '#FFFFFF',
    'L': '#FDF6E3'
}
CONFIG_SERVER_PORT = 8765
REACT_APP_DEV_PORT = 5173

ENABLE_API_AUTH = False
API_AUTH_TOKEN = os.environ.get("STREAMDECK_API_TOKEN", "test-token")
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ENABLE_API_AUTH:
            return f(*args, **kwargs)
        token = request.headers.get("Authorization")
        if token != f"Bearer {API_AUTH_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def applescript_escape_string(s):
    s = str(s)
    s = s.replace('“', '"').replace('”', '"')
    s = s.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')
    return s

def load_applescript_template(template_filename, **kwargs):
    primary_name_has_ext = "." in os.path.basename(template_filename)
    potential_filenames = []
    if primary_name_has_ext:
        potential_filenames.append(template_filename)
    base_filename, current_ext = os.path.splitext(template_filename)
    if current_ext != ".applescript":
        potential_filenames.append(f"{base_filename}.applescript")
    if current_ext != ".txt":
        potential_filenames.append(f"{base_filename}.txt")
    if base_filename != template_filename and not primary_name_has_ext:
        potential_filenames.append(base_filename)
    filepath_to_use = None
    seen = set()
    unique_potential_filenames = [x for x in potential_filenames if not (x in seen or seen.add(x))]
    for fname in unique_potential_filenames:
        filepath_scripts = SCRIPTS_DIR / fname
        if filepath_scripts.exists():
            filepath_to_use = filepath_scripts
            break
        filepath_appdir = APP_DIR / fname
        if filepath_appdir.exists():
            filepath_to_use = filepath_appdir
            break
    if not filepath_to_use:
        raise FileNotFoundError(f"AppleScript template not found: {template_filename}")
    with open(filepath_to_use, 'r', encoding='utf-8') as f:
        template_content = f.read()
    for key, value in kwargs.items():
        template_content = template_content.replace("{{" + str(key) + "}}", str(value))
    return template_content

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE':
        return False, False, False, '#000000', DEFAULT_FONT_SIZE, False, False, False, False, False, False, False
    new_win, device, sticky = 'N' in f, '@' in f, 'T' in f
    font_size = int(re.search(r"(\d+)", f).group(1)) if re.search(r"(\d+)", f) else DEFAULT_FONT_SIZE
    force_local_execution, is_mobile_ssh_flag = 'K' in f, 'M' in f
    osa_mon_flag, record_flag = '?' in f, '*' in f
    background_flag, confirm_flag, monitor_flag = '&' in f, '>' in f, '~' in f
    if record_flag:
        is_mobile_ssh_flag = True
    non_color_flags = {'N', 'T', '@', 'D', '#', 'V', '~', 'K', 'M', '?', '*', '&', '>'}
    base_color_char = next((c for c in f if c in BASE_COLORS and c not in non_color_flags), None)
    col = BASE_COLORS.get(base_color_char, '#000000')
    if 'D' in f and base_color_char:
        try:
            col = f"#{''.join(f'{int(col[i:i+2],16)//2:02X}' for i in (1,3,5))}"
        except Exception:
            pass
    return (new_win, device, sticky, col, font_size, force_local_execution, is_mobile_ssh_flag,
            osa_mon_flag, record_flag, background_flag, confirm_flag, monitor_flag)

def text_color(bg_hex):
    if not bg_hex or len(bg_hex) < 6:
        return 'white'
    bg_upper = bg_hex.upper()
    if bg_upper in [BASE_COLORS.get(c) for c in "YSWLP"]:
        return 'black'
    try:
        r, g, b = (int(bg_hex[i:i+2], 16) for i in (1, 3, 5))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return 'black' if lum > 128 else 'white'
    except Exception:
        return 'white'

def dim_color(bg_hex):
    try:
        return '#000000' if bg_hex.upper() == '#000000' else f"#{''.join(f'{int(bg_hex[i:i+2],16)//2:02X}' for i in (1,3,5))}"
    except Exception:
        return bg_hex

def toggle_button_bg(bg_hex):
    try:
        r, g, b = (min(255, int(bg_hex[i:i+2], 16) + 70) for i in (1, 3, 5))
        if r > 250 and g > 250 and b > 250 and bg_hex.upper() != BASE_COLORS['W']:
            r, g, b = (max(0, int(bg_hex[i:i+2], 16) - 70) for i in (1, 3, 5))
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return BASE_COLORS['W']

def hex_to_aps_color_values_str(hex_color):
    try:
        hc = hex_color.lstrip('#')
        return f"{{{','.join(str(int(hc[i:i+2],16)*257) for i in (0,2,4))}}}"
    except Exception:
        return "{0,0,0}"

def applescript_dialog(prompt_message, default_answer=""):
    script_vars = {
        "prompt_message": applescript_escape_string(prompt_message),
        "default_answer": applescript_escape_string(str(default_answer)),
    }
    try:
        script = load_applescript_template("system_events_dialog.applescript", **script_vars)
        proc = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            output = proc.stdout.strip()
            if output.startswith("APPLETSCRIPT_ERROR:"):
                return None
            if output in ("USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"):
                return output
            return output
        else:
            stderr_lower = proc.stderr.lower()
            if proc.returncode == 1 and "(-128)" in stderr_lower:
                return "USER_CANCELLED_PROMPT"
            if "(-1712)" in stderr_lower:
                return "USER_TIMEOUT_PROMPT"
            return None
    except Exception:
        traceback.print_exc()
        return None

def applescript_confirm(prompt_message):
    script_vars = {"prompt_message": applescript_escape_string(prompt_message)}
    try:
        script = load_applescript_template("system_events_confirm.applescript", **script_vars)
        proc = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.stdout.strip() == "YES_CONFIRMED"
    except Exception:
        traceback.print_exc()
        return False

def get_items():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, label, command, flags, monitor_keyword FROM streamdeck ORDER BY id")
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        traceback.print_exc()
        return []

def db_update_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE streamdeck SET label=?,command=?,flags=?,monitor_keyword=? WHERE id=?",
                (
                    button_data.get('label', ''),
                    button_data.get('command', ''),
                    button_data.get('flags', ''),
                    button_data.get('monitor_keyword', ''),
                    button_data.get('id'),
                ),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        traceback.print_exc()
        return False

def db_add_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO streamdeck (label,command,flags,monitor_keyword) VALUES (?,?,?,?)",
                (
                    button_data.get('label', ''),
                    button_data.get('command', ''),
                    button_data.get('flags', ''),
                    button_data.get('monitor_keyword', ''),
                ),
            )
            conn.commit()
            return cur.lastrowid
    except Exception:
        traceback.print_exc()
        return None

def db_delete_button(button_id):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM streamdeck WHERE id=?", (button_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        traceback.print_exc()
        return False

api_app = Flask(__name__)
CORS(api_app, resources={r"/api/*": {"origins": f"http://localhost:{REACT_APP_DEV_PORT}"}})

@api_app.route('/api/buttons', methods=['GET'])
@require_auth
def get_all_buttons_api():
    global items, current_session_vars
    return jsonify({"buttons": items, "variables": current_session_vars})

@api_app.route('/api/buttons/<int:button_id>', methods=['PUT'])
@require_auth
def update_button_config_api(button_id):
    global items, page_index, current_session_vars
    data = request.json
    updated_data = {"id": button_id, **data}
    if not db_update_button(updated_data):
        return jsonify({"error": "DB update failed"}), 500
    item_index = next((i for i, item in enumerate(items) if item['id'] == button_id), None)
    if item_index is not None:
        items[item_index] = updated_data
    return jsonify({"message": "Button updated", "button": updated_data})

@api_app.route('/api/buttons', methods=['POST'])
@require_auth
def add_new_button_api():
    global items, page_index, current_session_vars
    data = request.json
    new_id = db_add_button(data)
    if new_id is None:
        return jsonify({"error": "DB add failed"}), 500
    new_button = {"id": new_id, **data}
    items.append(new_button)
    return jsonify({"message": "Button added", "button": new_button}), 201

@api_app.route('/api/buttons/<int:button_id>', methods=['DELETE'])
@require_auth
def delete_button_config_api(button_id):
    global items, page_index, current_session_vars
    if not db_delete_button(button_id):
        return jsonify({"error": "DB delete failed"}), 500
    items = [i for i in items if i['id'] != button_id]
    return jsonify({"message": "Button deleted"})

@api_app.route('/api/variables', methods=['PUT'])
@require_auth
def update_session_variables_api():
    global current_session_vars, page_index
    data = request.json
    if isinstance(data, dict):
        current_session_vars.update(data)
        return jsonify({"message": "Session variables updated successfully"})
    return jsonify({"error": "Invalid data format, expected a JSON object"}), 400

def run_flask_app_thread():
    print(f"Flask API server starting on http://localhost:{CONFIG_SERVER_PORT}")
    try:
        api_app.run(host='127.0.0.1', port=CONFIG_SERVER_PORT, debug=False, use_reloader=False)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    print("Initializing Stream Deck Driver...")
    try:
        all_decks = DeviceManager().enumerate()
        if not all_decks:
            print("No Stream Deck found. Exiting.")
            sys.exit(1)
        deck = all_decks[0]
        deck.open()
        deck.reset()
        print(f"Opened Stream Deck: {deck.deck_type()} ({deck.key_count()} keys)")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    cnt = deck.key_count()
    rows_sd, cols_sd = deck.key_layout()
    load_key_idx = 0
    up_key_idx = cols_sd if cnt >= 15 else (1 if cnt == 6 else None)
    down_key_idx = 2 * cols_sd if cnt >= 15 else (4 if cnt == 6 else None)
    print(f"Layout: {rows_sd}r,{cols_sd}c. L:{load_key_idx},U:{up_key_idx},D:{down_key_idx}")

    flask_server_thread = threading.Thread(target=run_flask_app_thread, daemon=True)
    flask_server_thread.start()

    try:
        # Application logic to load data, handle StreamDeck events, rendering, and background processes
        print("Stream Deck initialized. Listening for key presses...")
        while True:
            flash_state = not flash_state
            with background_lock:
                for g_idx in list(background_processes.keys()):
                    if background_processes[g_idx].poll() is not None:
                        del background_processes[g_idx]
            # Place core redraw/logic here as needed
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("KeyboardInterrupt: Exiting...")
    except Exception:
        traceback.print_exc()
    finally:
        print("Cleaning up...")
        if 'web_ui_process' in globals() and web_ui_process:
            print("Terminating Web UI server...")
            web_ui_process.terminate()
            try:
                web_ui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                web_ui_process.kill()
        with background_lock:
            for proc in background_processes.values():
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        if deck:
            deck.reset()
            deck.close()
        print("Exited.")

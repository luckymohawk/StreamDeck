# streamdeck_driver_final_v5.py
import sqlite3
import subprocess
import sys
import time
import textwrap
import re
import json
import os
from pathlib import Path
from math import ceil
import shlex
import threading
import webbrowser

# --- IMPORTS for API Server ---
from flask import Flask, jsonify, request
from flask_cors import CORS

# --- DEPENDENCY CHECK ---
try:
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Transport.Transport import TransportError
    from StreamDeck.ImageHelpers import PILHelper
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"[FATAL] Missing required Python package: {e.name}", file=sys.stderr)
    print("Please install necessary packages (e.g., pip install streamdeck Pillow Flask Flask-CORS)", file=sys.stderr)
    sys.exit(1)

# === Application Directories & Files ===
APP_DIR = Path.home() / "Library" / "StreamDeckDriver"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "streamdeck.db"
LOAD_SCRIPT = APP_DIR / "streamdeck_db.py"
SCRIPTS_DIR = APP_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
WEB_UI_DIR = APP_DIR / "browsebuttons"


# === In-memory storage for variables ===
current_session_vars = {}
at_devices_to_reinit_cmd = set()
numeric_step_memory = {}
record_toggle_states = {}
background_processes = {}

# === Variable Pattern (Permissive) ===
VAR_PATTERN = re.compile(r"\{\{([^:}]+)(:([^}]*))?\}\}")
SSH_USER_HOST_CMD_PATTERN = re.compile(r"^(ssh(?:\s+-[a-zA-Z0-9]+(?:\s+\S+)?)*)\s+(\S+)@(\S+)((?:\s+.*)?)$", re.IGNORECASE)


# === Monitoring State Dictionaries ===
monitor_states = {}
monitor_threads = {}
key_to_global_item_idx_map = {}
global_item_idx_to_key_map = {}
monitor_generations = {}


# === Configuration & Constants ===
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

# === Key globals ===
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

# --- HELPER & CORE FUNCTIONS ---

def applescript_escape_string(s):
    s = str(s); s = s.replace('“', '"').replace('”', '"'); s = s.replace('\\', '\\\\'); s = s.replace('\n', '\\n'); s = s.replace('"', '\\"'); return s

def load_applescript_template(template_filename, **kwargs):
    primary_name_has_ext = "." in os.path.basename(template_filename); potential_filenames = []
    if primary_name_has_ext: potential_filenames.append(template_filename)
    base_filename, current_ext = os.path.splitext(template_filename)
    if current_ext != ".applescript": potential_filenames.append(f"{base_filename}.applescript")
    if current_ext != ".txt": potential_filenames.append(f"{base_filename}.txt")
    if base_filename != template_filename and not primary_name_has_ext: potential_filenames.append(base_filename)
    filepath_to_use = None; seen = set(); unique_potential_filenames = [x for x in potential_filenames if not (x in seen or seen.add(x))]
    for fname in unique_potential_filenames:
        filepath_scripts = SCRIPTS_DIR / fname
        if filepath_scripts.exists(): filepath_to_use = filepath_scripts; break
        filepath_appdir = APP_DIR / fname
        if filepath_appdir.exists(): filepath_to_use = filepath_appdir; break
    if not filepath_to_use: raise FileNotFoundError(f"AS template not found from '{template_filename}'")
    with open(filepath_to_use, 'r', encoding='utf-8') as f: template_content = f.read()
    for key, value in kwargs.items(): template_content = template_content.replace("{{" + str(key) + "}}", str(value))
    return template_content

# ##################################################################
# ##### NEW FUNCTION TO RUN INITIAL SETUP APPLESCRIPTS #####
# ##################################################################
def run_initial_setup_scripts():
    """
    Runs AppleScripts required for first-time setup, like creating and
    formatting the Numbers sheet. This function will block until the scripts
    are completed or cancelled by the user.
    """
    print("[INFO] Running initial setup scripts...")
    scripts_to_run = [
        "create_sd_tab.applescript",
        "Update-Streamdeck-Sheet.applescript"
    ]

    for script_name in scripts_to_run:
        script_path = SCRIPTS_DIR / script_name
        if not script_path.exists():
            print(f"[WARNING] Setup script not found, skipping: {script_name}")
            continue

        print(f"[INFO] Executing '{script_name}'. Please follow any on-screen prompts...")
        try:
            # We use subprocess.run to wait for the script to complete.
            # check=True will raise an error if the script fails (e.g., user cancels).
            proc = subprocess.run(
                ["osascript", str(script_path)],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"[INFO] Script '{script_name}' completed successfully.")
            if proc.stdout:
                print(f"  Output: {proc.stdout.strip()}")

        except subprocess.CalledProcessError as e:
            # A non-zero return code from AppleScript usually means the user
            # clicked "Cancel" in a dialog. This is not a fatal error.
            stderr_lower = e.stderr.lower()
            if "(-128)" in stderr_lower:
                print(f"[INFO] User cancelled '{script_name}'. Continuing startup.")
                # We break here because the second script depends on the first.
                # If the user cancels creation, we shouldn't try to format.
                break
            else:
                print(f"[ERROR] An error occurred while running '{script_name}'.", file=sys.stderr)
                print(f"  Return Code: {e.returncode}", file=sys.stderr)
                print(f"  Stderr: {e.stderr.strip()}", file=sys.stderr)
                # Depending on severity, you might want to sys.exit(1) here
        except Exception as e:
            print(f"[ERROR] Failed to execute AppleScript '{script_name}': {e}", file=sys.stderr)


def execute_applescript_dialog(prompt_message, default_answer=""):
    script_vars = {"prompt_message": applescript_escape_string(prompt_message), "default_answer": applescript_escape_string(str(default_answer))}
    script = load_applescript_template("system_events_dialog.applescript", **script_vars)
    proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        output = proc.stdout.strip()
        if output.startswith("APPLETSCRIPT_ERROR:"): print(f"[ERROR] AS Dialog Error: {output}"); return None
        if "USER_CANCELLED_PROMPT" == output: return "USER_CANCELLED_PROMPT"
        if "USER_TIMEOUT_PROMPT" == output: return "USER_TIMEOUT_PROMPT"
        return output
    else:
        stderr_lower = proc.stderr.lower()
        if proc.returncode == 1 and "(-128)" in stderr_lower: return "USER_CANCELLED_PROMPT"
        if "(-1712)" in stderr_lower: return "USER_TIMEOUT_PROMPT"
        print(f"[ERROR] osascript dialog error. RC:{proc.returncode},Err:{proc.stderr.strip()},Out:{proc.stdout.strip()}"); return None

def execute_applescript_confirm(prompt_message):
    script_vars = {"prompt_message": applescript_escape_string(prompt_message)}
    script = load_applescript_template("system_events_confirm.applescript", **script_vars)
    proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False)
    return proc.stdout.strip() == "YES_CONFIRMED"

def get_active_terminal_window_name():
    """Returns the name of the frontmost terminal window."""
    try:
        script = load_applescript_template("get_active_terminal_window.applescript")
        proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False, timeout=2)
        if proc.returncode == 0 and proc.stdout.strip() and proc.stdout.strip() != "NO_WINDOW":
            return proc.stdout.strip()
    except Exception as e:
        print(f"[ERROR] Failed to get active terminal window name: {e}", file=sys.stderr)
    return None

def activate_terminal_window(window_name):
    """Brings a terminal window with the given name to the front."""
    if not window_name: return
    try:
        script = load_applescript_template("activate_terminal_window.applescript", window_name=window_name)
        subprocess.run(["osascript", "-"], input=script, text=True, check=False, timeout=2)
    except Exception as e:
        print(f"[ERROR] Failed to activate terminal window '{window_name}': {e}", file=sys.stderr)
    
def get_terminal_output(window_title):
    """Executes AppleScript to get the text content of a Terminal window by its custom title."""
    script_vars = {"safe_target_title": applescript_escape_string(window_title)}
    try:
        script = load_applescript_template("terminal_check_text.applescript", **script_vars)
        proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False, timeout=5)
        if proc.returncode != 0:
            print(f"[ERROR] AppleScript for getting terminal output failed: {proc.stderr.strip()}", file=sys.stderr)
            return None
        output = proc.stdout.strip()
        if output.startswith("ERROR:") or output.startswith("APPLETSCRIPT_ERROR:"):
            print(f"[ERROR] AppleScript error while getting terminal output: {output}", file=sys.stderr)
            return None
        return output
    except FileNotFoundError:
        print("[ERROR] Could not find 'terminal_check_text.applescript'. Make sure it's in the scripts directory.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] Exception while getting terminal output: {e}", file=sys.stderr)
        return None

def initialize_session_vars_from_items(items_list, session_vars_dict):
    session_vars_dict.clear()
    has_record_button = False
    
    for item_dict in items_list:
        # Check for record flag
        if '*' in item_dict.get('flags', ''):
            has_record_button = True
        
        # Process command variables
        cmd = item_dict.get('command', '')
        if not cmd: continue
        for match in VAR_PATTERN.finditer(cmd):
            var_name, default_value = match.group(1).strip(), match.group(3) if match.group(3) is not None else ""
            if var_name not in session_vars_dict:
                # Use default from command, otherwise empty string, except for TAKE
                if var_name.upper() == 'TAKE':
                    session_vars_dict['TAKE'] = default_value or "1"
                else:
                    session_vars_dict[var_name] = default_value

    # If any record button exists but TAKE was not defined in any command, initialize it.
    if has_record_button and 'TAKE' not in session_vars_dict:
        session_vars_dict['TAKE'] = "1"

def resolve_command_string(command_str_template, session_vars_dict):
    resolved_cmd = command_str_template
    # Handle the global TAKE variable first
    if 'TAKE' in session_vars_dict:
        take_val_str = str(session_vars_dict.get('TAKE', '1'))
        try:
            # Pad with zeros if it's a number
            padded_take = str(int(take_val_str)).zfill(3)
            resolved_cmd = re.sub(r'\{\{TAKE(:[^}]*)?\}\}', padded_take, resolved_cmd, flags=re.IGNORECASE)
        except (ValueError, TypeError):
             # If not a number, just substitute the raw value
            resolved_cmd = re.sub(r'\{\{TAKE(:[^}]*)?\}\}', take_val_str, resolved_cmd, flags=re.IGNORECASE)

    # Handle all other variables
    for var_name, var_value in session_vars_dict.items():
        if var_name.upper() != 'TAKE':
            # This regex ensures we only replace variables with the exact name
            resolved_cmd = re.compile(r"(\{\{)(" + re.escape(var_name) + r")(:[^}]*)?(\}\})").sub(str(var_value), resolved_cmd)

    # Final pass for any remaining placeholders with defaults
    for match in list(VAR_PATTERN.finditer(resolved_cmd)):
        full_placeholder, var_name, default_in_cmd = match.group(0), match.group(1).strip(), match.group(3) if match.group(3) is not None else ""
        if var_name.upper() != 'TAKE' and var_name not in session_vars_dict:
            session_vars_dict[var_name] = default_in_cmd
            resolved_cmd = resolved_cmd.replace(full_placeholder, str(session_vars_dict.get(var_name, default_in_cmd)))

    return resolved_cmd.replace('\\"', '"')

def get_items():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row; cur = conn.cursor()
            cur.execute("SELECT id, label, command, flags, monitor_keyword FROM streamdeck ORDER BY id")
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e: print(f"[ERROR] Database read failed: {e}", file=sys.stderr); return []

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE': return False, False, False, '#000000', DEFAULT_FONT_SIZE, False, False, False, False, False, False, False
    new_win, device, sticky = 'N' in f, '@' in f, 'T' in f
    font_size = int(m.group(1)) if (m := re.search(r"(\d+)", f)) else DEFAULT_FONT_SIZE
    force_local_execution, is_mobile_ssh_flag = 'K' in f, 'M' in f
    osa_mon_flag, record_flag = '?' in f, '*' in f
    background_flag, confirm_flag, monitor_flag = '&' in f, '>' in f, '~' in f

    if record_flag: is_mobile_ssh_flag = True

    non_color_flags = {'N', 'T', '@', 'D', '#', 'V', '~', 'K', 'M', '?', '*', '&', '>'}
    base_color_char = next((c for c in f if c in BASE_COLORS and c not in non_color_flags), None)
    col = BASE_COLORS.get(base_color_char, '#000000')

    if 'D' in f and base_color_char:
        try: col = f"#{''.join(f'{int(col[i:i+2],16)//2:02X}' for i in (1,3,5))}"
        except: pass

    return new_win, device, sticky, col, font_size, force_local_execution, is_mobile_ssh_flag, osa_mon_flag, record_flag, background_flag, confirm_flag, monitor_flag

def text_color(bg_hex):
    if not bg_hex or len(bg_hex) < 6: return 'white'
    bg_upper = bg_hex.upper()
    if bg_upper in [BASE_COLORS.get(c) for c in "YSWLP"]: return 'black'
    try:
        r, g, b = (int(bg_hex[i:i+2], 16) for i in (1, 3, 5))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return 'black' if lum > 128 else 'white'
    except:
        return 'white'

def hex_to_aps_color_values_str(hex_color):
    try: hc = hex_color.lstrip('#'); return f"{{{','.join(str(int(hc[i:i+2],16)*257) for i in (0,2,4))}}}"
    except: return "{0,0,0}"

def toggle_button_bg(bg_hex):
    try:
        r,g,b = (min(255,int(bg_hex[i:i+2],16)+70) for i in (1,3,5))
        if r>250 and g>250 and b>250 and bg_hex.upper()!=BASE_COLORS['W']: r,g,b = (max(0,int(bg_hex[i:i+2],16)-70) for i in (1,3,5))
        return f"#{r:02X}{g:02X}{b:02X}"
    except: return BASE_COLORS['W']

def dim_color(bg_hex):
    try: return '#000000' if bg_hex.upper()=='#000000' else f"#{''.join(f'{int(bg_hex[i:i+2],16)//2:02X}' for i in (1,3,5))}"
    except: return bg_hex

def _transform_ssh_user_for_mobile(command_text):
    if not command_text or not command_text.lower().strip().startswith("ssh "): return command_text
    match = SSH_USER_HOST_CMD_PATTERN.match(command_text)
    if match:
        ssh_options_part, host_part, remote_cmd_part = match.group(1), match.group(3), match.group(4) or ""
        return f"{ssh_options_part} mobile@{host_part}{remote_cmd_part}"
    return command_text

def log_command_to_file(log_path_str, full_command_str):
    try:
        log_dir = Path(log_path_str); log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "streamdeck_commander.log"; timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding='utf-8') as f: f.write(f"{timestamp} - CMD: {full_command_str}\n")
        print(f"[INFO] Logged command to '{log_file}'")
    except Exception as e: print(f"[ERROR] Failed to write to log file '{log_path_str}': {e}")

def log_to_recpath(recpath, message_type, content):
    """Logs a message to log.txt, falling back to the Desktop on permission error."""
    try:
        # First attempt: Use the user-provided path
        log_dir = Path(recpath)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "log.txt"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding='utf-8') as f:
            f.write(f"[{timestamp}] - {message_type}: {content}\n")
    except PermissionError:
        # Fallback on permission error to the Desktop
        fallback_dir = Path.home() / "Desktop"
        print(f"[WARNING] Permission Denied: Could not write to '{recpath}'.")
        print(f"  Please update your 'RECPATH' variable to a directory you have write permissions for.")
        print(f"  Falling back to safe log directory: '{fallback_dir}'")
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_log_file = fallback_dir / "log.txt"
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(fallback_log_file, "a", encoding='utf-8') as f:
                f.write(f"[{timestamp}] - {message_type}: {content} (Original path '{recpath}' was not writable)\n")
        except Exception as e_fallback:
            # If even the fallback fails, print a comprehensive error
            print(f"[ERROR] CRITICAL: Failed to write to fallback recording log file: {e_fallback}")
    except Exception as e:
        # Catch other potential errors
        print(f"[ERROR] Failed to write to recording log file in '{recpath}': {e}")

def send_keystroke_to_terminal(window_title, keystroke):
    script_vars = {"safe_target_title": applescript_escape_string(window_title), "keystroke_content": keystroke}
    try:
        script = load_applescript_template("terminal_keystroke.applescript", **script_vars)
        subprocess.run(["osascript", "-"], input=script, text=True, check=False)
        print(f"[INFO] Sent keystroke '{keystroke}' to window '{window_title}'")
    except FileNotFoundError: print("[ERROR] Could not find terminal_keystroke.applescript")

def render_key(label_text, deck_ref, bg_hex_val, font_size_val, txt_override_color=None, status_text_val=None, vars_text_val=None, flash_active=False, extra_text=None):
    W,H = deck_ref.key_image_format()['size']; img = PILHelper.create_image(deck_ref); draw = ImageDraw.Draw(img)
    try: pil_bg = tuple(int(bg_hex_val.lstrip('#')[i:i+2],16) for i in (0,2,4))
    except: pil_bg = (0,0,0)
    draw.rectangle([(0,0),(W,H)], fill=pil_bg)
    try:
        font_status, font_label, font_vars = ImageFont.truetype(FONT_PATH, 10), ImageFont.truetype(FONT_PATH, font_size_val), ImageFont.truetype(FONT_PATH, 10)
        font_extra = ImageFont.truetype(FONT_PATH, 18) # Font for "SAVE"
    except IOError: font_status, font_label, font_vars, font_extra = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    final_text_color = txt_override_color or text_color(bg_hex_val)
    status_text_height_reserved = 0
    actual_status_text_to_draw = status_text_val # Default to showing text
    if status_text_val:
        s_bbox_temp = font_status.getbbox(status_text_val, anchor="lt") if hasattr(font_status, 'getbbox') else (0,0,*draw.textsize(status_text_val,font=font_status))
        status_text_height_reserved = (s_bbox_temp[3] - s_bbox_temp[1]) + LINE_SPACING
        if flash_active:
            actual_status_text_to_draw = ""
            
    if actual_status_text_to_draw:
        s_bbox = font_status.getbbox(actual_status_text_to_draw,anchor="lt") if hasattr(font_status,'getbbox') else (0,0,*draw.textsize(actual_status_text_to_draw,font=font_status))
        draw.text(((W - (s_bbox[2] - s_bbox[0])) / 2, 3), actual_status_text_to_draw, font=font_status, fill=final_text_color, anchor="lt" if hasattr(draw, 'textbbox') else None)
        
    label_y_start = 3 + status_text_height_reserved; current_label_y = label_y_start
    if label_text:
        wrap_width = max(3, min(W // (font_size_val // 1.8 if font_size_val > 10 else 8), 6 if font_size_val >= ARROW_FONT_SIZE else (9 if font_size_val >= DEFAULT_FONT_SIZE else 12)))
        lines = textwrap.wrap(label_text, width=int(wrap_width), max_lines=3, placeholder="…")
        lh_bbox = font_label.getbbox("Tg",anchor="lt") if hasattr(font_label,'getbbox') else (0,0,*font_label.getsize("Tg"))
        line_height_label = lh_bbox[3] - lh_bbox[1] if lh_bbox[3] > lh_bbox[1] else font_size_val
        total_label_block_height = len(lines) * line_height_label + (len(lines) - 1) * LINE_SPACING if lines else 0
        y_offset = (H - label_y_start - total_label_block_height) / 2 if total_label_block_height < (H - label_y_start) and total_label_block_height > 0 else 0
        current_label_y = label_y_start + y_offset
        for line_item in lines:
            if current_label_y + line_height_label > H : break
            l_bbox = font_label.getbbox(line_item,anchor="lt") if hasattr(font_label,'getbbox') else (0,0,*draw.textsize(line_item,font=font_label))
            draw.text(((W - (l_bbox[2] - l_bbox[0])) / 2, current_label_y), line_item, font=font_label, fill=final_text_color, anchor="lt" if hasattr(draw, 'textbbox') else None)
            current_label_y += line_height_label + LINE_SPACING
    if vars_text_val:
        var_lines_raw = vars_text_val.split(); var_lines_wrapped_final = []
        var_char_width_approx = font_vars.getsize("M")[0] if hasattr(font_vars, 'getsize') else 6
        max_chars_per_var_line_calc = W // var_char_width_approx if var_char_width_approx > 0 else 12
        for v_item_raw in var_lines_raw: var_lines_wrapped_final.extend(textwrap.wrap(v_item_raw, width=int(max_chars_per_var_line_calc), max_lines=1, placeholder="…"))
        var_line_height_render = font_vars.getsize("M")[1] if hasattr(font_vars, 'getsize') else 10; num_var_lines_to_draw_final = min(len(var_lines_wrapped_final), 2)
        start_y_for_vars_block = H - LINE_SPACING - (num_var_lines_to_draw_final * var_line_height_render) - ((num_var_lines_to_draw_final - 1) * VAR_LINE_SPACING if num_var_lines_to_draw_final > 1 else 0)
        actual_y_for_first_var_line = max(start_y_for_vars_block, current_label_y if label_text and lines else label_y_start)
        for i in range(num_var_lines_to_draw_final):
            var_item_to_draw = var_lines_wrapped_final[i]; y_pos_this_var_line = actual_y_for_first_var_line + i * (var_line_height_render + VAR_LINE_SPACING)
            if y_pos_this_var_line + var_line_height_render > H - LINE_SPACING + 2: continue
            v_bbox = font_vars.getbbox(var_item_to_draw,anchor="lt") if hasattr(font_vars,'getbbox') else (0,0,*draw.textsize(var_item_to_draw,font=font_vars))
            draw.text(((W - (v_bbox[2] - v_bbox[0])) / 2, y_pos_this_var_line ), var_item_to_draw, font=font_vars, fill=final_text_color, anchor="lt" if hasattr(draw, 'textbbox') else None)
    if extra_text:
        extra_bbox = font_extra.getbbox(extra_text, anchor="lt") if hasattr(font_extra, 'getbbox') else (0,0,*draw.textsize(extra_text,font=font_extra))
        draw.text(((W - (extra_bbox[2] - extra_bbox[0])) / 2, H - (extra_bbox[3] - extra_bbox[1]) - 5), extra_text, font=font_extra, fill=final_text_color, anchor="lt" if hasattr(draw, 'textbbox') else None)
    return PILHelper.to_native_format(deck_ref,img)

def run_cmd_in_terminal(main_cmd, is_at_act=False, at_has_n=False, btn_style_cfg=None, act_at_lbl=None, is_n_staged=False, ssh_staged="", n_staged="", prepend="", force_new_win_at=False, force_local_execution=False, script_template_override=None, ssh_cmd_to_keystroke=None, actual_cmd_to_keystroke=None):
    eff_cmd = f"{prepend}\n{main_cmd.strip()}" if prepend and main_cmd.strip() else (prepend or main_cmd.strip())
    eff_cmd = eff_cmd.replace('“','"').replace('”','"'); esc_cmd = applescript_escape_string(eff_cmd)
    as_script, script_vars = "", {}
    tpl_map = {"spawn_ssh_and_snapshot": "terminal_spawn_ssh_and_snapshot.applescript","spawn_and_snapshot": "terminal_spawn_and_snapshot.applescript","n_staged": "terminal_n_for_at_staged_keystroke.applescript","at_n": "terminal_activate_new_styled_at_n.applescript","at_only": "terminal_activate_found_at_only.applescript","n_alone": "terminal_activate_standalone_n.applescript","to_active_at": "terminal_command_to_active_at_device.applescript","default": "terminal_do_script_default.applescript","force_local_new_window": "terminal_force_new_window_and_do_script.applescript"}
    template_key = "default"
    if script_template_override and script_template_override in tpl_map: template_key = script_template_override
    elif force_local_execution: template_key = "force_local_new_window"
    elif is_n_staged: template_key = "n_staged"
    elif is_at_act: template_key = "at_n" if at_has_n else "at_only"
    elif btn_style_cfg and btn_style_cfg.get('is_standalone_n_button', False): template_key = "n_alone"
    elif act_at_lbl and not is_at_act: template_key = "to_active_at"
    
    if template_key == "n_staged":
        if not btn_style_cfg or not ssh_staged: print(f"[ERR] N-Staged command missing required info (style or ssh command)."); return None
        script_vars['window_custom_title'] = applescript_escape_string(btn_style_cfg.get('lbl', 'Mobile Session'))
        script_vars['aps_bg_color'] = hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', '#0066CC'))
        script_vars['aps_text_color'] = "{65535,65535,65535}" if btn_style_cfg.get('text_color_name','white')=='white' else "{0,0,0}"
        script_vars['ssh_command_to_keystroke'] = applescript_escape_string(ssh_staged)
        script_vars['actual_n_command_to_keystroke'] = applescript_escape_string(n_staged)
    elif template_key == "spawn_ssh_and_snapshot":
        if not btn_style_cfg or not ssh_cmd_to_keystroke: return None
        script_vars = {'window_custom_title': applescript_escape_string(btn_style_cfg.get('lbl', 'Monitor Window')),'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', '#0066CC')),'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name', 'white') == 'white' else "{0,0,0}",'ssh_command_to_keystroke': applescript_escape_string(ssh_cmd_to_keystroke or ""),'actual_command_to_keystroke': applescript_escape_string(actual_cmd_to_keystroke or "")}
    elif template_key == "spawn_and_snapshot":
        if not btn_style_cfg: return None
        script_vars = {'window_custom_title': applescript_escape_string(btn_style_cfg.get('lbl', 'Monitor Window')),'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', '#0066CC')),'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name', 'white') == 'white' else "{0,0,0}",'initial_command_to_run': esc_cmd}
    elif template_key in ["at_n", "at_only"]:
        if not btn_style_cfg or 'lbl' not in btn_style_cfg:
            script_vars['final_script_payload_for_do_script'] = esc_cmd; template_key = "default"
        else:
            dev_lbl = btn_style_cfg['lbl']
            script_vars.update({'escaped_device_label': applescript_escape_string(dev_lbl),'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', '#000000')),'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name', 'white') == 'white' else "{0,0,0}"})
            if template_key == "at_n": script_vars['final_script_payload'] = esc_cmd
            else: script_vars['final_script_payload_for_do_script'] = esc_cmd; script_vars['force_new_window'] = "true" if force_new_win_at else "false"
    elif template_key in ["force_local_new_window", "n_alone", "default"]:
        script_vars['final_script_payload_for_do_script'] = esc_cmd
        if template_key == "n_alone" and btn_style_cfg:
             script_vars.update({'window_custom_title': applescript_escape_string(btn_style_cfg.get('lbl', 'N Window')),'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', '#000000')),'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name', 'white') == 'white' else "{0,0,0}"})
    elif template_key == "to_active_at":
        script_vars = {'safe_target_title': applescript_escape_string(act_at_lbl), 'final_script_payload_for_do_script': esc_cmd, 'main_command_raw_for_emptiness_check': esc_cmd, 'command_to_type_literally_content': esc_cmd}
    
    if template_key: as_script = load_applescript_template(tpl_map[template_key], **script_vars)
    if as_script:
        try:
            proc = subprocess.run(["osascript","-"],input=as_script,text=True,capture_output=True,check=False, timeout=15)
            stderr_lower = proc.stderr.lower().strip() if proc.stderr else ""
            if proc.returncode != 0 and "(-128)" not in stderr_lower and "(-1712)" not in stderr_lower:
                print(f"[ERROR] AppleScript execution failed (RC:{proc.returncode}).", file=sys.stderr); print(f"  AS STDERR: {proc.stderr.strip()}", file=sys.stderr)
            return proc.stdout.strip()
        except subprocess.TimeoutExpired: print(f"[ERROR] osascript call timed out for command: {main_cmd[:50]}...", file=sys.stderr)
        except Exception as e_as: print(f"[FATAL] Error running osascript: {e_as}", file=sys.stderr)
    return None

def monitor_ssh(global_idx, ssh_cmd_base, generation_id):
    chk_cmd = f"{ssh_cmd_base} exit"
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        if monitor_generations.get(global_idx) != generation_id: break
        new_state = 'BROKEN'; time.sleep(3.0 + (global_idx % 5) * 0.1)
        try:
            res = subprocess.run(shlex.split(chk_cmd) if not any(c in chk_cmd for c in "|;&><") else chk_cmd, shell=any(c in chk_cmd for c in "|;&><"), capture_output=True, text=True, timeout=8)
            if res.returncode == 0: new_state = 'connected'
        except: pass
        if monitor_generations.get(global_idx) == generation_id:
            if monitor_states.get(global_idx) != new_state: monitor_states[global_idx] = new_state
        else: break
def monitor_remote_process(global_idx, ssh_base_cmd, unique_grep_tag, generation_id):
    time.sleep(2.0); quoted_tag = shlex.quote(unique_grep_tag)
    if monitor_generations.get(global_idx) != generation_id: return
    grep_cmd_remote = f"ps auxww | grep -F -- {quoted_tag} | grep -v -F -- 'grep -F -- {quoted_tag}'"; full_ssh_cmd_str = f"{ssh_base_cmd} \"{grep_cmd_remote}\""
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        if monitor_generations.get(global_idx) != generation_id: break
        new_proc_state = 'PROCESS_RUNNING'
        try:
            result = subprocess.run(full_ssh_cmd_str, shell=True, capture_output=True, text=True, timeout=8)
            if result.returncode != 0: new_proc_state = 'PROCESS_BROKEN'
        except: new_proc_state = 'PROCESS_ERROR'
        if monitor_generations.get(global_idx) == generation_id:
            if new_proc_state != 'PROCESS_RUNNING':
                # Use g_idx directly as the key
                record_toggle_states[global_idx] = {"state": "ERROR"}
                monitor_states[global_idx] = new_proc_state
                break
        else: break
        time.sleep(3.0 + (global_idx % 7) * 0.1)

def monitor_window_snapshot(global_idx, window_id, initial_snapshot, keyword, generation_id):
    snapshot_len = len(initial_snapshot)

    def _get_active_context():
        try:
            script_app = 'tell application "System Events" to name of first application process whose frontmost is true'
            proc_app = subprocess.run(["osascript", "-e", script_app], text=True, capture_output=True, check=False, timeout=1)
            if proc_app.returncode != 0: return None, None
            app_name = proc_app.stdout.strip()
            window_name = get_active_terminal_window_name() if app_name == "Terminal" else None
            return app_name, window_name
        except Exception:
            return None, None

    def _restore_context(app_name, window_name):
        if not app_name: return
        try:
            script_activate = f'tell application "{applescript_escape_string(app_name)}" to activate'
            subprocess.run(["osascript", "-e", script_activate], check=False, timeout=1)
            if app_name == "Terminal" and window_name:
                activate_terminal_window(window_name)
        except Exception as e:
            print(f"[WARN] Failed to restore context to {app_name}: {e}")

    def _activate_window_by_id(win_id):
        if not win_id: return
        try:
            script = f'tell application "Terminal" to set index of (first window whose id is {win_id}) to 1'
            subprocess.run(["osascript", "-e", script], check=False, timeout=2, capture_output=True)
        except Exception as e:
            print(f"[ERROR] Failed to activate monitor window ID '{win_id}': {e}", file=sys.stderr)

    time.sleep(1.0) # Initial delay to allow window to launch fully
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        time.sleep(60.0)
        if monitor_generations.get(global_idx) != generation_id: break

        original_app, original_window = (None, None)
        current_content = None

        try:
            # Phase 1: Context switch, grab data, and switch back
            original_app, original_window = _get_active_context()
            _activate_window_by_id(window_id)
            time.sleep(0.2)
            script = load_applescript_template("get_window_content.applescript", window_id=window_id)
            proc_content = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False, timeout=2)
            current_content = proc_content.stdout.strip()
            if original_app:
                _restore_context(original_app, original_window)

        except Exception as e:
            print(f"[ERROR] Snapshot Monitor context switch/grab failed: {e}")
            monitor_states[global_idx] = 'OSA_ERROR'; monitor_generations[global_idx] = None
            break

        # Phase 2: Process data (no more UI interaction)
        if monitor_generations.get(global_idx) != generation_id: break
        if current_content is None: continue

        if current_content == "WINDOW_GONE":
            monitor_states[global_idx] = 'OSA_GONE'; monitor_generations[global_idx] = None
            break
        
        if len(current_content) > snapshot_len:
            new_text = current_content[snapshot_len:]
            if keyword.lower() in new_text.lower():
                monitor_states[global_idx] = 'OSA_FOUND'; monitor_generations[global_idx] = None
                _activate_window_by_id(window_id) # Bring monitor window forward and leave it
                break

def db_update_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur=conn.cursor();cur.execute("UPDATE streamdeck SET label=?,command=?,flags=?,monitor_keyword=? WHERE id=?",(button_data.get('label',''),button_data.get('command',''),button_data.get('flags',''),button_data.get('monitor_keyword',''),button_data['id']));conn.commit();return True
    except sqlite3.Error as e: print(f"[ERROR] DB Update failed: {e}",file=sys.stderr);return False
def db_add_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur=conn.cursor();cur.execute("INSERT INTO streamdeck (label,command,flags,monitor_keyword) VALUES (?,?,?,?)",(button_data.get('label',''),button_data.get('command',''),button_data.get('flags',''),button_data.get('monitor_keyword','')));conn.commit();return cur.lastrowid
    except sqlite3.Error as e: print(f"[ERROR] DB Insert failed: {e}",file=sys.stderr);return None
def db_delete_button(button_id):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur=conn.cursor();cur.execute("DELETE FROM streamdeck WHERE id=?",(button_id,));conn.commit();return cur.rowcount>0
    except sqlite3.Error as e: print(f"[ERROR] DB Delete failed: {e}",file=sys.stderr);return False

# --- FLASK API SERVER ---
api_app=Flask(__name__);CORS(api_app,resources={r"/api/*":{"origins":f"http://localhost:{REACT_APP_DEV_PORT}"}})
@api_app.route('/api/buttons',methods=['GET'])
def get_all_buttons_api():global items,current_session_vars;return jsonify({"buttons":items,"variables":current_session_vars})
@api_app.route('/api/buttons/<int:button_id>',methods=['PUT'])
def update_button_config_api(button_id):
    global items,page_index,current_session_vars;data=request.json;updated_data={"id":button_id,**data}
    if not db_update_button(updated_data): return jsonify({"error":"DB update failed"}),500
    item_index=next((i for i,item in enumerate(items) if item['id']==button_id),None)
    if item_index is not None:items[item_index]=updated_data;initialize_session_vars_from_items(items,current_session_vars);build_page(page_index);
    return jsonify({"message":"Button updated","button":updated_data})
@api_app.route('/api/buttons',methods=['POST'])
def add_new_button_api():
    global items,page_index,current_session_vars;data=request.json;new_id=db_add_button(data)
    if new_id is None:return jsonify({"error":"DB add failed"}),500
    new_button={"id":new_id,**data};items.append(new_button);initialize_session_vars_from_items(items,current_session_vars);build_page(page_index);
    return jsonify({"message":"Button added","button":new_button}),201
@api_app.route('/api/buttons/<int:button_id>',methods=['DELETE'])
def delete_button_config_api(button_id):
    global items,page_index,current_session_vars
    if not db_delete_button(button_id):return jsonify({"error":"DB delete failed"}),500
    items=[i for i in items if i['id']!=button_id];initialize_session_vars_from_items(items,current_session_vars);build_page(page_index);
    return jsonify({"message":"Button deleted"})
@api_app.route('/api/variables', methods=['PUT'])
def update_session_variables_api():
    global current_session_vars, page_index
    data = request.json
    if isinstance(data, dict):
        current_session_vars.update(data)
        build_page(page_index) # Trigger a redraw
        return jsonify({"message": "Session variables updated successfully"})
    return jsonify({"error": "Invalid data format, expected a JSON object"}), 400

def run_flask_app_thread():
    print(f"[INFO] Flask API server starting on http://localhost:{CONFIG_SERVER_PORT}")
    try: api_app.run(host='127.0.0.1',port=CONFIG_SERVER_PORT,debug=False,use_reloader=False)
    except Exception as e: print(f"[FATAL] Flask server failed to start: {e}",file=sys.stderr)

def build_page(idx_param):
    global labels, cmds, flags, items, page_index, key_to_global_item_idx_map, global_item_idx_to_key_map, cnt, load_key_idx, up_key_idx, down_key_idx

    # Create new layout dictionaries that will atomically replace the global ones
    new_labels, new_cmds, new_flags = {}, {}, {}
    new_key_to_g_idx, new_g_idx_to_key = {}, {}
    page_index = 0 if not items else idx_param

    # 1. Categorize all items
    layout_sticky_items, inplace_sticky_items, normal_items = [], [], []
    state_sticky_indices = {g_idx for g_idx, state_info in record_toggle_states.items() if state_info.get('state') in ['RECORDING', 'ERROR']}

    for i, item in enumerate(items):
        flags_tuple = parse_flags(item['flags'])
        mon_state = monitor_states.get(i)
        is_layout_sticky = flags_tuple[2] or (mon_state == 'OSA_FOUND' and '?' in item.get('flags', ''))
        is_inplace_sticky = i in state_sticky_indices

        if is_inplace_sticky:
            inplace_sticky_items.append((i, item))
        elif is_layout_sticky:
            layout_sticky_items.append((i, item))
        else:
            normal_items.append((i, item))

    # 2. Determine which physical slots are available or locked
    slots_taken = set()
    fixed_keys = {load_key_idx, up_key_idx, down_key_idx}
    slots_taken.update(fixed_keys)

    # Lock in-place sticky items to their previous key
    for g_idx, item in inplace_sticky_items:
        if g_idx in global_item_idx_to_key_map:
            key = global_item_idx_to_key_map[g_idx]
            slots_taken.add(key)
            new_labels[key], new_cmds[key], new_flags[key] = item['label'], item['command'], item['flags']
            new_key_to_g_idx[key] = g_idx
            new_g_idx_to_key[g_idx] = key

    # 3. Place layout-sticky items at the top in the first available slots
    avail_slots_for_layout = [s for s in range(cnt) if s not in slots_taken]
    for idx, (g_idx, item) in enumerate(layout_sticky_items):
        if idx < len(avail_slots_for_layout):
            key = avail_slots_for_layout[idx]
            slots_taken.add(key)
            new_labels[key], new_cmds[key], new_flags[key] = item['label'], item['command'], item['flags']
            new_key_to_g_idx[key] = g_idx
            new_g_idx_to_key[g_idx] = key

    # 4. Paginate normal items into the remaining slots
    pagination_slots = sorted([s for s in range(cnt) if s not in slots_taken])
    num_norm_slots = len(pagination_slots)
    tot_norm_pg = ceil(len(normal_items) / num_norm_slots) if normal_items and num_norm_slots > 0 else 1
    page_index = idx_param % tot_norm_pg if tot_norm_pg > 0 else 0
    start_norm_idx = page_index * num_norm_slots

    for i_slot, key in enumerate(pagination_slots):
        item_idx = start_norm_idx + i_slot
        if item_idx < len(normal_items):
            g_idx, item = normal_items[item_idx]
            new_labels[key], new_cmds[key], new_flags[key] = item['label'], item['command'], item['flags']
            new_key_to_g_idx[key] = g_idx
            new_g_idx_to_key[g_idx] = key

    # Place fixed navigation buttons
    for k, l, c, f in [(load_key_idx, "LOAD", "", "W"), (up_key_idx, "▲", "", "W"), (down_key_idx, "▼", "", "W")]:
        if k is not None: new_labels[k], new_cmds[k], new_flags[k] = l, c, f

    # 5. Atomically update the global layout state
    labels, cmds, flags = new_labels, new_cmds, new_flags
    key_to_global_item_idx_map = new_key_to_g_idx
    global_item_idx_to_key_map = new_g_idx_to_key

    if deck: redraw()

def redraw():
    if not deck: return
    for i_key in range(deck.key_count()): render_individual_key(i_key)

def render_individual_key(i_key):
    global deck, key_to_global_item_idx_map, items, monitor_states, record_toggle_states, active_device_key, numeric_mode, long_press_numeric_active, numeric_var, flash_state, current_session_vars, up_key_idx, down_key_idx, labels, flags, cmds, load_key_idx
    if not deck: return

    lbl_render, cmd_render, f_str_render = labels.get(i_key, ""), cmds.get(i_key, ""), flags.get(i_key, "")
    g_idx = key_to_global_item_idx_map.get(i_key)
    
    if g_idx is not None and g_idx < len(items):
        item = items[g_idx]
        lbl_render, cmd_render, f_str_render = item.get('label',''), item.get('command',''), item.get('flags','')
    
    _, dev_flag, _, bg_color, fs, _, is_mobile, osa_mon_flag, record_flag, background_flag, confirm_flag, monitor_flag = parse_flags(f_str_render)
    status_render, vars_render, extra_txt = None, None, None
    bg_render, txt_override_render = bg_color, None
    should_flash_status_text = False

    if i_key == down_key_idx:
        extra_txt = "CONFIG"

    if record_flag:
        state_info = record_toggle_states.get(g_idx, {"state": "OFF"})
        state = state_info.get("state", "OFF")
        
        W, H = deck.key_image_format()['size']
        img = PILHelper.create_image(deck)
        draw = ImageDraw.Draw(img)
        
        final_bg_hex = bg_color
        status_text_to_draw = None

        if state == "ERROR":
            final_bg_hex = BASE_COLORS['R'] if flash_state else dim_color(BASE_COLORS['R'])
            status_text_to_draw = "ERROR"
        
        final_text_color = text_color(final_bg_hex)
        
        try:
            pil_bg = tuple(int(final_bg_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        except:
            pil_bg = (0, 0, 0)
        draw.rectangle([(0, 0), (W, H)], fill=pil_bg)

        if state == "RECORDING" and flash_state:
            ellipse_fill = tuple(int(BASE_COLORS['R'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            draw.ellipse([(10, 10), (W - 10, H - 10)], fill=ellipse_fill)
            final_text_color = text_color(BASE_COLORS['R'])
        
        try:
            font_label = ImageFont.truetype(FONT_PATH, fs)
            font_take = ImageFont.truetype(BOLD_FONT_PATH, 16)
            font_status = ImageFont.truetype(FONT_PATH, 11)
        except IOError:
            font_label, font_take, font_status = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()

        label_y_pos = H * 0.45
        if status_text_to_draw:
            label_y_pos = H * 0.55
            s_bbox = font_status.getbbox(status_text_to_draw, anchor="lt") if hasattr(font_status, 'getbbox') else (0, 0, *draw.textsize(status_text_to_draw, font=font_status))
            draw.text(((W - (s_bbox[2] - s_bbox[0])) / 2, 5), status_text_to_draw, font=font_status, fill=final_text_color)

        wrapped_label = "\n".join(textwrap.wrap(lbl_render, width=10, max_lines=2, placeholder="…"))
        draw.text((W / 2, label_y_pos), wrapped_label, font=font_label, fill=final_text_color, anchor="ma", spacing=LINE_SPACING, align="center")

        take_val_str = current_session_vars.get("TAKE", "1")
        try:
            take_val_display = str(int(take_val_str)).zfill(3)
        except (ValueError, TypeError):
            take_val_display = take_val_str[:3] # Show first 3 chars if not a number

        draw.text((W / 2, H * 0.80), f"TAKE {take_val_display}", font=font_take, fill=final_text_color, anchor="ma")
        
        deck.set_key_image(i_key, PILHelper.to_native_format(deck, img))
        return

    # --- Generic Rendering for all other buttons ---
    if osa_mon_flag:
        mon_state = monitor_states.get(g_idx)
        if mon_state == "OSA_MONITORING":
            status_render = "MONITOR..."
            should_flash_status_text = True
            bg_render = bg_color # Keep original color
        elif mon_state == "OSA_FOUND":
            status_render = "FOUND"
            bg_render = bg_color if flash_state else dim_color(bg_color)
        elif mon_state == "OSA_GONE":
            status_render, bg_render = "WIN GONE", BASE_COLORS['R']
        elif mon_state == "OSA_ERROR":
            status_render, bg_render = "OSA ERROR", BASE_COLORS['R']
        else: # Idle state
            status_render = "OSA Ready"
            bg_render = dim_color(bg_color)
        txt_override_render = text_color(bg_render)
    
    elif dev_flag:
        bg_render=toggle_button_bg(bg_color) if active_device_key==i_key else dim_color(bg_color);txt_override_render=text_color(bg_render)
        if monitor_flag:
            mon_state = monitor_states.get(g_idx)
            if mon_state=='connected': status_render,should_flash_status_text="CONNECTED",True
            elif mon_state=='BROKEN': status_render,should_flash_status_text,bg_render="BROKEN",True,BASE_COLORS['R'] if flash_state else dim_color(bg_color)
            elif mon_state=='initializing':status_render="INIT..."
            elif mon_state:status_render=mon_state.upper()[:10]
    
    elif background_flag and g_idx in background_processes:
        proc = background_processes[g_idx]
        if proc.poll() is None: # Process is still running
            bg_render = BASE_COLORS['B'] if flash_state else dim_color(BASE_COLORS['B'])
            status_render = "RUNNING..."
            txt_override_render = text_color(bg_render)
        else: # Process finished or was killed
            del background_processes[g_idx] # Clean up
            
    if 'V' in f_str_render:
        vars_to_display = []
        for match in VAR_PATTERN.finditer(cmd_render):
            var_name = match.group(1).strip()
            if var_name in current_session_vars: vars_to_display.append(str(current_session_vars[var_name]))
        if vars_to_display: vars_render = " ".join(vars_to_display)

    if numeric_mode and long_press_numeric_active:
        num_key = numeric_var['key']
        if i_key == num_key or i_key in [up_key_idx, down_key_idx]:
            _,_,_,num_orig_bg,_,_,_,_,_,_,_,_ = parse_flags(flags.get(num_key,""));bright_num_bg=toggle_button_bg(num_orig_bg)
            bg_render=bright_num_bg if flash_state else(num_orig_bg if i_key==num_key else dim_color(bright_num_bg));txt_override_render=text_color(bg_render)
            if i_key == num_key: vars_render = str(current_session_vars.get(numeric_var['name'],""))
            elif i_key in [up_key_idx,down_key_idx]:
                op,step=("+",numeric_var.get('step',1.0)) if i_key==up_key_idx else ("-",numeric_var.get('step',1.0)); (status_render,vars_render) = (f"{op}{step}",None) if i_key==down_key_idx else (None,f"{op}{step}")

    if i_key == load_key_idx:
        final_fs = 22
    elif i_key in [up_key_idx, down_key_idx]:
        final_fs = ARROW_FONT_SIZE
    else:
        final_fs = fs
        
    try:
        deck.set_key_image(i_key, render_key(lbl_render, deck, bg_render, final_fs, txt_override_render, status_render, vars_render, flash_active=(should_flash_status_text and flash_state), extra_text=extra_txt))
    except Exception as e:
        print(f"[ERROR] Render key {i_key} failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

# --- START OF REORDERED FUNCTIONS ---

def start_monitoring():
    global items, monitor_threads, monitor_states, current_session_vars, monitor_generations
    for g_idx in list(monitor_threads.keys()):
        monitor_generations[g_idx] = None; monitor_threads.pop(g_idx, None)
    for g_idx, item_data in enumerate(items):
        item_cmd_mon, item_flags_mon = item_data.get('command',''), item_data.get('flags','')
        # --- MODIFIED: Use new parse_flags tuple ---
        _, _, _, _, _, _, _, _, _, _, _, monitor_flag = parse_flags(item_flags_mon)
        if monitor_flag and '@' in item_flags_mon:
            monitor_states[g_idx] = 'initializing'
            current_gen_id = time.time(); monitor_generations[g_idx] = current_gen_id
            resolved_cmd_mon = resolve_command_string(item_cmd_mon, current_session_vars)
            if 'M' in item_flags_mon and resolved_cmd_mon.lower().strip().startswith("ssh "): resolved_cmd_mon = _transform_ssh_user_for_mobile(resolved_cmd_mon)
            ssh_match_mon = re.match(r"^(ssh\s+[^ ]+)", resolved_cmd_mon)
            if ssh_match_mon:
                thread = threading.Thread(target=monitor_ssh, args=(g_idx, ssh_match_mon.group(1), current_gen_id), daemon=True)
                monitor_threads[g_idx] = thread; thread.start()
            else: monitor_states[g_idx] = 'error_config'
    print("[INFO] Monitoring initialized.")

def load_data_and_reinit_vars():
    global items, current_session_vars, page_index, numeric_mode, numeric_var, active_device_key, toggle_keys, long_press_numeric_active, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, global_item_idx_to_key_map, monitor_generations, record_toggle_states
    print("[INFO] Rebuilding database from Numbers & reloading configs...")
    try:
        # NOTE: This now calls your robust database script (renamed to streamdeck_db.py)
        py_exec = sys.executable; load_script_path = APP_DIR/"streamdeck_db.py"
        if not load_script_path.exists(): load_script_path = Path("streamdeck_db.py")
        subprocess.run([py_exec,str(load_script_path),str(DB_PATH)],check=True,capture_output=True,text=True)
    except Exception as e:
        err_out = getattr(e, 'stderr', '') or getattr(e, 'stdout', '') or str(e)
        print(f"[FATAL] DB Load Script failed: {err_out}. Exiting.", file=sys.stderr)
        if deck: deck.close(); sys.exit(1)
    items[:] = get_items()
    initialize_session_vars_from_items(items, current_session_vars)
    page_index=0; numeric_mode=False; numeric_var=None; long_press_numeric_active=False
    active_device_key=None; toggle_keys.clear(); at_devices_to_reinit_cmd.clear()
    flash_state=False; key_to_global_item_idx_map.clear(); global_item_idx_to_key_map.clear(); monitor_generations.clear(); record_toggle_states.clear()
    if not items: print("[WARNING] No items from DB.")
    if deck: build_page(page_index); start_monitoring()

def callback(deck_param, k_idx, pressed):
    global page_index, numeric_mode, numeric_var, active_device_key, labels, cmds, flags, items, toggle_keys, current_session_vars, press_times, long_press_numeric_active, up_key_idx, down_key_idx, load_key_idx, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, monitor_states, monitor_generations, web_ui_process, numeric_step_memory, record_toggle_states, background_processes
    
    if pressed: press_times[k_idx] = time.time(); return
    duration = time.time()-press_times.pop(k_idx,time.time()); lp = duration>=LONG_PRESS_THRESHOLD

    # --- MODIFIED: Centralized variable definition at the start ---
    g_idx_cb = key_to_global_item_idx_map.get(k_idx)
    item_data, orig_item_cmd_from_db, lbl_str, flag_str = {}, "", "", ""
    if g_idx_cb is not None and g_idx_cb < len(items):
        item_data = items[g_idx_cb]
        orig_item_cmd_from_db = item_data.get('command','')
        lbl_str = item_data.get('label','')
        flag_str = item_data.get('flags','')
    
    # Numeric mode intercepts all key presses until it is deactivated.
    if numeric_mode and long_press_numeric_active:
        num_key = numeric_var['key']
        if k_idx == num_key: # Pressing the originating key deactivates numeric mode
            numeric_mode, numeric_var, long_press_numeric_active = False, None, False
            toggle_keys.clear()
            build_page(page_index); return
        elif k_idx in [up_key_idx, down_key_idx]: # Up/Down keys adjust the variable
            step = numeric_var['step'] * (5 if lp else 1)
            curr_val = current_session_vars.get(numeric_var['name'], "0")
            try: curr = float(curr_val)
            except ValueError: curr = 0.0
            new = curr + step if k_idx == up_key_idx else curr - step
            current_session_vars[numeric_var['name']] = new
            cmd_run = resolve_command_string(numeric_var['cmd_template'], current_session_vars)
            if numeric_var.get('is_background'):
                subprocess.Popen(shlex.split(cmd_run))
            else:
                run_cmd_in_terminal(cmd_run, act_at_lbl=labels.get(active_device_key), force_local_execution=numeric_var.get('force_local', False))
            build_page(page_index); return
        else: # Any other key press also deactivates numeric mode
            numeric_mode, numeric_var, long_press_numeric_active = False, None, False
            toggle_keys.clear()
            build_page(page_index); return

    # Fixed buttons (no g_idx) have simple, direct actions
    if g_idx_cb is None:
        if k_idx==down_key_idx and lp:
            if 'web_ui_process' in globals() and (web_ui_process is None or web_ui_process.poll() is not None):
                if not WEB_UI_DIR.exists() or not(WEB_UI_DIR/"package.json").exists():return
                try:web_ui_process=subprocess.Popen(['npm','run','dev'],cwd=WEB_UI_DIR,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);time.sleep(5)
                except Exception as e:print(f"[ERROR] Failed to start Web UI server: {e}",file=sys.stderr);return
            webbrowser.open(f"http://localhost:{REACT_APP_DEV_PORT}");return
        if k_idx==load_key_idx and not lp:load_data_and_reinit_vars();return
        if k_idx == up_key_idx and not lp: page_index -= 1; build_page(page_index)
        if k_idx == down_key_idx and not lp: page_index += 1; build_page(page_index)
        return

    # All standard button logic from here
    _, dev_cb, _, bg_cb, _, force_local_cb, is_mobile_ssh_cb, osa_mon_flag, record_flag, background_flag, confirm_flag, _ = parse_flags(flag_str)

    res_cmd = resolve_command_string(orig_item_cmd_from_db, current_session_vars)

    # --- MODIFIED: New flag handlers ---
    if confirm_flag:
        if not execute_applescript_confirm(f"Run this command?\n\n{res_cmd}"):
            return # User clicked "No"

    if background_flag:
        if g_idx_cb in background_processes and background_processes[g_idx_cb].poll() is None:
            print(f"[INFO] Terminating background process for button {g_idx_cb}.")
            background_processes[g_idx_cb].terminate()
            try:
                background_processes[g_idx_cb].wait(timeout=2)
            except subprocess.TimeoutExpired:
                background_processes[g_idx_cb].kill()
            del background_processes[g_idx_cb]
        else:
            try:
                final_bg_cmd = ""
                if active_device_key is not None and not force_local_cb:
                    # Execute on remote device
                    active_at_cmd = resolve_command_string(cmds.get(active_device_key, ""), current_session_vars)
                    _, _, _, _, _, _, active_at_is_mobile, _, _, _, _, _ = parse_flags(flags.get(active_device_key, ""))
                    if active_at_is_mobile:
                        active_at_cmd = _transform_ssh_user_for_mobile(active_at_cmd)
                    
                    ssh_match = re.match(r"^(ssh\s+\S+)", active_at_cmd)
                    if ssh_match:
                        ssh_base = ssh_match.group(1)
                        escaped_res_cmd = res_cmd.replace('"', '\\"')
                        final_bg_cmd = f'{ssh_base} "{escaped_res_cmd}"'
                        print(f"[INFO] Executing remote background command: {final_bg_cmd}")
                    else:
                        print(f"[ERROR] Background task failed: Active @ device is not a valid SSH command.")
                        return
                else:
                    # Execute locally
                    final_bg_cmd = res_cmd
                    print(f"[INFO] Executing local background command: {final_bg_cmd}")

                proc = subprocess.Popen(shlex.split(final_bg_cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                background_processes[g_idx_cb] = proc

            except Exception as e:
                print(f"[ERROR] Failed to run background command: {e}", file=sys.stderr)
        build_page(page_index)
        return

    # Standard execution flow for all other flags
    if record_flag:
        recpath = resolve_command_string("{{RECPATH}}", current_session_vars)
        if not recpath or recpath == "{{RECPATH}}":
            print("[WARNING] RECPATH variable not set. Recording logging is disabled.")
            recpath = None

        state_info = record_toggle_states.get(g_idx_cb, {"state": "OFF"})
        current_state = state_info.get("state", "OFF")

        if lp: # Long Press to edit variables
            if current_state == "RECORDING": return
            
            original_scene_value = str(current_session_vars.get('SCENE', ''))
            
            variables_to_edit = [match for match in VAR_PATTERN.finditer(orig_item_cmd_from_db) if match.group(1).upper() != 'TAKE']
            for match in variables_to_edit:
                var_name = match.group(1).strip()
                default_val = match.group(3) if match.group(3) is not None else ""
                current_val = str(current_session_vars.get(var_name, default_val))
                user_input = execute_applescript_dialog(f"Enter value for {var_name}:", current_val)
                if user_input is None or user_input in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                    build_page(page_index); return
                if user_input != current_val:
                    current_session_vars[var_name] = user_input

            new_scene_value = str(current_session_vars.get('SCENE', ''))
            scene_changed = original_scene_value != new_scene_value
            
            take_match = re.search(r'\{\{TAKE:([^}]+)\}\}', orig_item_cmd_from_db, re.IGNORECASE)
            default_take_str = "1"
            if take_match and take_match.group(1).isdigit():
                default_take_str = take_match.group(1)
            
            suggested_take = default_take_str if scene_changed else str(current_session_vars.get('TAKE', default_take_str))
            prompt_message_take = f"SCENE changed. Reset TAKE or enter new value:" if scene_changed else "Enter TAKE number:"
            
            user_input_take = execute_applescript_dialog(prompt_message_take, suggested_take)
            if user_input_take and user_input_take not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                current_session_vars['TAKE'] = user_input_take
            build_page(page_index); return

        if current_state == "ERROR":
            record_toggle_states.pop(g_idx_cb, None)
            build_page(page_index); return

        if current_state == "OFF":
            if active_device_key is None:
                print("[ERROR] REC Start: No active @-device selected."); record_toggle_states[g_idx_cb] = {"state": "ERROR"}; build_page(page_index); return
            
            active_at_cmd = resolve_command_string(cmds.get(active_device_key, ""), current_session_vars)
            _, _, _, _, _, _, active_at_is_mobile, _, _, _, _, _ = parse_flags(flags.get(active_device_key, ""))
            final_command = resolve_command_string(orig_item_cmd_from_db, current_session_vars)

            target_window_title = ""
            if active_at_is_mobile:
                target_window_title = labels.get(active_device_key)
                run_cmd_in_terminal(final_command, act_at_lbl=target_window_title)
            else:
                target_window_title = f"{lbl_str}-REC"
                print(f"[INFO] * button '{lbl_str}' targeting non-mobile @-device. Spawning new mobile session for recording.")
                mobile_ssh_cmd = _transform_ssh_user_for_mobile(active_at_cmd)
                btn_cfg_for_new_win = {"lbl": target_window_title, "bg_hex": bg_cb, "text_color_name": text_color(bg_cb)}
                run_cmd_in_terminal("", is_n_staged=True, ssh_staged=mobile_ssh_cmd, n_staged=final_command, btn_style_cfg=btn_cfg_for_new_win)
            
            time.sleep(0.5)
            if recpath:
                terminal_output = get_terminal_output(target_window_title)
                log_content = final_command
                prefix = "CMD"
                if terminal_output:
                    match = re.search(r"(Will capture.*?Session start status: 0)", terminal_output, re.DOTALL)
                    if match:
                        log_content = match.group(1).strip()
                        prefix = "START_OUTPUT"
                log_to_recpath(recpath, prefix, log_content)

            record_toggle_states[g_idx_cb] = {"state": "RECORDING", "window_title": target_window_title}
            build_page(page_index); return

        elif current_state == "RECORDING":
            target_window_title = state_info.get("window_title")
            if not target_window_title:
                print("[ERROR] REC Stop: Cannot find window title from recording start."); record_toggle_states[g_idx_cb] = {"state": "ERROR"}; build_page(page_index); return

            send_keystroke_to_terminal(target_window_title, "\\r"); time.sleep(0.5)
            terminal_output = get_terminal_output(target_window_title)
            
            has_error = False
            if terminal_output:
                error_keywords = ["failed", "bad output", "MovieSamplerCheckMovie failed", "-12848"]
                for line in terminal_output.split('\n')[-15:]:
                    if any(keyword.lower() in line.lower() for keyword in error_keywords):
                        has_error = True
                        print(f"[INFO] Recording error detected in window '{target_window_title}'.")
                        if recpath: log_to_recpath(recpath, "ERR", line.strip())
                        break
            
            if has_error:
                record_toggle_states[g_idx_cb] = {"state": "ERROR"}
            else:
                try:
                    current_take_num = int(current_session_vars.get('TAKE', "1"))
                    current_session_vars['TAKE'] = str(current_take_num + 1)
                except (ValueError, TypeError):
                    current_session_vars['TAKE'] = "1" # Reset if not a number
                record_toggle_states.pop(g_idx_cb, None)
            
            build_page(page_index); return
        return

    if osa_mon_flag and not lp:
        current_mon_state = monitor_states.get(g_idx_cb)
        if current_mon_state in ["OSA_MONITORING", "OSA_FOUND"]:
            print(f"[INFO] User cancelled/dismissed OSA monitor for button {g_idx_cb}.")
            monitor_generations[g_idx_cb] = None
            monitor_states.pop(g_idx_cb, None)
            redraw()
            return

        if g_idx_cb in monitor_threads and monitor_generations.get(g_idx_cb) is not None:
             monitor_generations[g_idx_cb] = None; time.sleep(0.1)

        keyword=item_data.get('monitor_keyword',''); keyword = keyword[:-2] if keyword.endswith(".0") else keyword
        if not keyword:
            monitor_states[g_idx_cb]='OSA_ERROR'; print("[ERROR] OSA Monitor keyword is missing."); redraw(); return

        command_to_run=resolve_command_string(orig_item_cmd_from_db,current_session_vars)
        style={"lbl":lbl_str,"bg_hex":bg_cb,"text_color_name":text_color(bg_cb)}; result_str=None
        
        if active_device_key is not None:
            ssh_cmd=resolve_command_string(cmds.get(active_device_key,""),current_session_vars)
            if ssh_cmd:
                result_str=run_cmd_in_terminal("",btn_style_cfg=style,script_template_override="spawn_ssh_and_snapshot",ssh_cmd_to_keystroke=ssh_cmd,actual_cmd_to_keystroke=command_to_run)
        else:
            result_str=run_cmd_in_terminal(command_to_run,btn_style_cfg=style,script_template_override="spawn_and_snapshot")
        
        if result_str and "::::" in result_str:
            window_id_str,initial_snapshot=result_str.split("::::",1)
            if window_id_str.isdigit():
                window_id=int(window_id_str);monitor_states[g_idx_cb]='OSA_MONITORING';gen_id=time.time();monitor_generations[g_idx_cb]=gen_id
                thread=threading.Thread(target=monitor_window_snapshot,args=(g_idx_cb,window_id,initial_snapshot,keyword,gen_id),daemon=True)
                monitor_threads[g_idx_cb]=thread;thread.start()
            else:
                monitor_states[g_idx_cb]='OSA_ERROR'
        else:
            monitor_states[g_idx_cb]='OSA_ERROR'
        redraw();return
    
    if'#'in flag_str: # --- MODIFIED: Corrected to handle short-press
        if lp: # Long-press enters numeric adjustment mode
            m=VAR_PATTERN.search(orig_item_cmd_from_db)
            if not m:return
            v_n,d_v=m.group(1).strip(),m.group(3)or"0";s_v_s=execute_applescript_dialog(f"START {v_n}:",current_session_vars.get(v_n,d_v))
            if not s_v_s or s_v_s in["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]:redraw();return
            last_step=numeric_step_memory.get(k_idx,"1");stp_s=execute_applescript_dialog(f"STEP {v_n}:",last_step)
            if not stp_s or stp_s in["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]:redraw();return
            try:s_v,stp_v=float(s_v_s),float(stp_s);numeric_step_memory[k_idx]=stp_s
            except:redraw();return
            current_session_vars[v_n]=s_v;numeric_mode=True;long_press_numeric_active=True
            numeric_var={"name":v_n,"value":s_v,"step":stp_v,"cmd_template":orig_item_cmd_from_db,"key":k_idx,"force_local":force_local_cb,"is_mobile_ssh":is_mobile_ssh_cb, "is_background": background_flag}
            toggle_keys.clear();toggle_keys.add(k_idx);build_page(page_index);return
        else: # Short-press just runs the command once
            run_cmd_in_terminal(res_cmd, act_at_lbl=labels.get(active_device_key), force_local_execution=force_local_cb)

    elif dev_cb and not lp:
        style={"lbl":lbl_str,"bg_hex":bg_cb,"text_color_name":text_color(bg_cb)};force=k_idx in at_devices_to_reinit_cmd
        if force:at_devices_to_reinit_cmd.remove(k_idx)
        if active_device_key==k_idx and not force:active_device_key=None;toggle_keys.discard(k_idx)
        else:
            if active_device_key is not None:toggle_keys.discard(active_device_key)
            active_device_key=k_idx;toggle_keys.add(k_idx)
            cmd_r=resolve_command_string(orig_item_cmd_from_db,current_session_vars)
            if is_mobile_ssh_cb and cmd_r.lower().strip().startswith("ssh ") and not force_local_cb:cmd_r=_transform_ssh_user_for_mobile(cmd_r)
            run_cmd_in_terminal(cmd_r,is_at_act=True,at_has_n=('N' in flag_str),btn_style_cfg=style,force_new_win_at=force,force_local_execution=force_local_cb)
        build_page(page_index);return
        
    elif'V'in flag_str.upper() and lp:
        v_f=list(VAR_PATTERN.finditer(orig_item_cmd_from_db))
        if not v_f:return
        chg=False
        for m in v_f:
            v_n,d_v=m.group(1).strip(),m.group(3)or"";c_v=str(current_session_vars.get(v_n,d_v))
            n_v=execute_applescript_dialog(f"Val for {v_n}:",c_v)
            if n_v and n_v not in["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None] and n_v!=c_v:current_session_vars[v_n]=n_v;chg=True
        if dev_cb:
            at_devices_to_reinit_cmd.add(k_idx)
            if k_idx==active_device_key and chg:active_device_key=None;toggle_keys.discard(k_idx)
        build_page(page_index);return
    
    # This is the final, generic command execution for simple buttons
    elif not any([dev_cb, record_flag, osa_mon_flag, '#' in flag_str]):
        run_cmd_in_terminal(res_cmd, act_at_lbl=labels.get(active_device_key), force_local_execution=force_local_cb)

    redraw()

# --- Main Execution Block ---
if __name__ == "__main__":
    print("[INFO] Initializing Stream Deck Driver...")
    try:
        all_decks = DeviceManager().enumerate()
        if not all_decks: print("No Stream Deck found. Exiting."); sys.exit(1)
        deck = all_decks[0]; deck.open(); deck.reset()
        print(f"[INFO] Opened Stream Deck: {deck.deck_type()} ({deck.key_count()} keys)")
    except Exception as e: print(f"[FATAL] Deck init error: {e}"); sys.exit(1)
    cnt = deck.key_count(); rows_sd, cols_sd = deck.key_layout()
    load_key_idx = 0; up_key_idx = cols_sd if cnt >= 15 else (1 if cnt == 6 else None); down_key_idx = 2 * cols_sd if cnt >= 15 else (4 if cnt == 6 else None)
    print(f"[INFO] Layout: {rows_sd}r,{cols_sd}c. L:{load_key_idx},U:{up_key_idx},D:{down_key_idx}")
    
    flask_server_thread = threading.Thread(target=run_flask_app_thread, daemon=True); flask_server_thread.start()
    
    # ##################################################################
    # ##### RUNNING THE NEW SETUP SCRIPTS ON INITIAL LAUNCH #####
    # ##################################################################
    run_initial_setup_scripts()

    load_data_and_reinit_vars()
    deck.set_key_callback(callback)
    redraw()
    print("[INFO] Stream Deck initialized. Listening for key presses...")
    try:
        while True:
            flash_state = not flash_state
            # --- NEW: Check status of background processes ---
            for g_idx in list(background_processes.keys()):
                if background_processes[g_idx].poll() is not None:
                    del background_processes[g_idx]
            
            redraw(); time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt: print("\n[INFO] KeyboardInterrupt: Exiting...")
    finally:
        print("[INFO] Cleaning up...")
        if 'web_ui_process' in globals() and web_ui_process:
            print("[INFO] Terminating Web UI server..."); web_ui_process.terminate()
            try: web_ui_process.wait(timeout=5)
            except subprocess.TimeoutExpired: print("[WARN] Web UI server did not terminate gracefully, killing."); web_ui_process.kill()
        
        # --- NEW: Terminate any running background processes on exit ---
        for proc in background_processes.values():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

        if deck: deck.reset(); deck.close()
        print("[INFO] Exited.")

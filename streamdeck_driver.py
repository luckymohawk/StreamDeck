# START OF FILE: streamdeck_driver.py
#!/usr/bin/env python3
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
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Transport.Transport import TransportError
from StreamDeck.ImageHelpers import PILHelper
from PIL import Image, ImageDraw, ImageFont
import shlex

# === Application Directories & Files ===
APP_DIR = Path.home() / "Library" / "StreamDeckDriver"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "streamdeck.db"
LOAD_SCRIPT = APP_DIR / "streamdeck_db.py"
SCRIPTS_DIR = APP_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


# === In-memory storage for variables ===
current_session_vars = {}
at_devices_to_reinit_cmd = set()

# === Variable Pattern ===
VAR_PATTERN = re.compile(r"\{\{([A-Z][A-Z0-9_]*)(:([^}]*))?\}\}")


def applescript_escape_string(s):
    s = str(s)
    s = s.replace('“', '"').replace('”', '"')
    s = s.replace('\\', '\\\\')
    s = s.replace('\n', '\\n')
    s = s.replace('"', '\\"')
    return s

def load_applescript_template(template_filename, **kwargs):
    base_filename, _ = os.path.splitext(template_filename)
    potential_filenames = [template_filename, f"{base_filename}.applescript", f"{base_filename}.txt"]
    
    filepath_to_use = None

    for fname in potential_filenames:
        filepath_scripts = SCRIPTS_DIR / fname
        if filepath_scripts.exists():
            filepath_to_use = filepath_scripts
            break
        filepath_appdir = APP_DIR / fname
        if filepath_appdir.exists():
            filepath_to_use = filepath_appdir
            break
            
    if not filepath_to_use:
        raise FileNotFoundError(f"AppleScript template not found: {template_filename} (with extensions or exact name) in {SCRIPTS_DIR} or {APP_DIR}")

    with open(filepath_to_use, 'r', encoding='utf-8') as f:
        template_content = f.read()
    
    for key, value in kwargs.items():
        template_content = template_content.replace("{{" + str(key) + "}}", str(value))
        
    return template_content

def execute_applescript_dialog(prompt_message, default_answer=""):
    script_vars = {
        "prompt_message": applescript_escape_string(prompt_message),
        "default_answer": applescript_escape_string(str(default_answer))
    }
    script = load_applescript_template("system_events_dialog.txt", **script_vars)
    
    proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True, check=False)
    
    if proc.returncode == 0:
        output = proc.stdout.strip()
        if output.startswith("APPLETSCRIPT_ERROR:"):
            print(f"[ERROR] AppleScript Dialog Error: {output}")
            return None
        if "USER_CANCELLED_PROMPT" == output :
            return "USER_CANCELLED_PROMPT"
        if "USER_TIMEOUT_PROMPT" == output:
            return "USER_TIMEOUT_PROMPT"
        return output
    else:
        stderr_lower = proc.stderr.lower()
        if proc.returncode == 1 and "(-128)" in stderr_lower:
             print(f"[INFO] User cancelled AppleScript Dialog (RC: {proc.returncode}, Err: {proc.stderr.strip()}).")
             return "USER_CANCELLED_PROMPT"
        if "(-1712)" in stderr_lower:
            print(f"[INFO] AppleScript Dialog timed out (RC: {proc.returncode}, Err: {proc.stderr.strip()}).")
            return "USER_TIMEOUT_PROMPT"
            
        print(f"[ERROR] osascript process error for dialog. RC: {proc.returncode}, Err: {proc.stderr.strip()}, Out: {proc.stdout.strip()}")
        return None

def initialize_session_vars_from_items(items_list, session_vars_dict):
    session_vars_dict.clear()
    for _label, cmd, _flags in items_list:
        if not cmd: continue
        for match in VAR_PATTERN.finditer(cmd):
            var_name = match.group(1)
            default_value = match.group(3) if match.group(3) is not None else ""
            
            if var_name not in session_vars_dict:
                session_vars_dict[var_name] = default_value
    print(f"[INFO] Initialized/Reset session variables from command defaults: {session_vars_dict}")


def resolve_command_string(command_str_template, session_vars_dict):
    resolved_cmd = command_str_template
    for var_name_in_session, var_value_in_session in session_vars_dict.items():
        placeholder_pattern_for_session_var = re.compile(r"(\{\{)(" + re.escape(var_name_in_session) + r")(:[^}]*)?(\}\})")
        resolved_cmd = placeholder_pattern_for_session_var.sub(str(var_value_in_session), resolved_cmd)

    matches_to_process = list(VAR_PATTERN.finditer(resolved_cmd))
    for match in matches_to_process:
        full_placeholder = match.group(0)
        var_name = match.group(1)
        default_in_cmd = match.group(3) if match.group(3) is not None else ""
        
        val_to_use = default_in_cmd
        if var_name not in session_vars_dict:
            session_vars_dict[var_name] = val_to_use
        resolved_cmd = resolved_cmd.replace(full_placeholder, str(val_to_use))
    
    if '\\"' in resolved_cmd:
        resolved_cmd = resolved_cmd.replace('\\"', '"')
            
    return resolved_cmd

# === Configuration & Constants ===
POLL_INTERVAL = 0.3
LINE_SPACING = 4; DEFAULT_FONT_SIZE = 16; ARROW_FONT_SIZE = 24
LONG_PRESS_THRESHOLD = 1.0
FONT_PATH = "/System/Library/Fonts/SFNS.ttf"; BOLD_FONT_PATH = "/System/Library/Fonts/SFNSDisplay-Bold.otf"
BASE_COLORS = {'K':'#000000','R':'#FF0000','G':'#00FF00','O':'#FF9900','B':'#0066CC','Y':'#FFFF00','U':'#800080','S':'#00FFFF','E':'#808080','W':'#FFFFFF','L':'#FDF6E3','P':'#FFC0CB'}

# === Helper Functions ===
def get_items():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT label,command,newwin FROM streamdeck ORDER BY id"); rows = cur.fetchall()
    conn.close(); return [(lbl or "", cmd or "", nw or "") for lbl, cmd, nw in rows]

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE': return False, False, False, BASE_COLORS['K'], DEFAULT_FONT_SIZE
    
    new_win_flag = 'N' in f
    device_flag = '@' in f
    sticky_flag = 'T' in f or device_flag

    size_match = re.search(r"(\d+)", f)
    font_size = int(size_match.group(1)) if size_match else DEFAULT_FONT_SIZE
    
    non_color_flags_chars = {'N', 'T', '@', 'D', '#', 'V'}
    base_color_char = 'K'
    for char_in_flag in f:
        if char_in_flag.isalpha() and char_in_flag not in non_color_flags_chars and char_in_flag in BASE_COLORS:
            base_color_char = char_in_flag
            break
            
    col = BASE_COLORS.get(base_color_char, BASE_COLORS['K'])

    if 'D' in f and base_color_char != 'K':
        try:
            r_val,g_val,b_val = [int(col[i:i+2], 16)//2 for i in (1,3,5)]; col = f"#{r_val:02X}{g_val:02X}{b_val:02X}"
        except: pass
        
    return new_win_flag, device_flag, sticky_flag, col, font_size

def text_color(bg_hex_str):
    if not bg_hex_str or len(bg_hex_str) < 6 : return 'white'
    
    bg_hex_upper = bg_hex_str.upper()
    if bg_hex_upper in [BASE_COLORS['Y'], BASE_COLORS['S'], BASE_COLORS['W'], BASE_COLORS['L'], BASE_COLORS['P']]:
        return 'black'
    if bg_hex_upper in [BASE_COLORS['K'], BASE_COLORS['R'], BASE_COLORS['B'], BASE_COLORS['U']]:
        return 'white'
    if bg_hex_upper == BASE_COLORS['E']:
        return 'white'

    try:
        r, g, b = int(bg_hex_str[1:3], 16), int(bg_hex_str[3:5], 16), int(bg_hex_str[5:7], 16)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return 'black' if luminance > 128 else 'white'
    except:
        return 'white'


def hex_to_aps_color_values_str(hex_color_str):
    try:
        hex_color_str = hex_color_str.lstrip('#')
        r = int(hex_color_str[0:2], 16) * 257
        g = int(hex_color_str[2:4], 16) * 257
        b = int(hex_color_str[4:6], 16) * 257
        return f"{{{r},{g},{b}}}"
    except:
        return "{0,0,0}"

def toggle_button_bg(bg_hex):
    try:
        r_val,g_val,b_val = [min(255, int(bg_hex[i:i+2],16)+70) for i in (1,3,5)]
        if r_val > 250 and g_val > 250 and b_val > 250 and (bg_hex.upper() != BASE_COLORS['W']):
             r_val,g_val,b_val = [max(0, int(bg_hex[i:i+2],16)-70) for i in (1,3,5)]
        return f"#{r_val:02X}{g_val:02X}{b_val:02X}"
    except (ValueError, TypeError, IndexError): return BASE_COLORS['W']


def render_key(label, deck, bg_hex, fs, text_color_override=None, value_str=None, value_font_size=16):
    W, H = deck.key_image_format()['size']; img = PILHelper.create_image(deck); draw = ImageDraw.Draw(img)
    try: pr,pg,pb = [int(bg_hex[i:i+2],16) for i in (1,3,5)]
    except: pr=pg=pb=0
    draw.rectangle([(0,0),(W,H)], fill=(pr,pg,pb))
    
    try: fnt = ImageFont.truetype(FONT_PATH, fs)
    except IOError: fnt = ImageFont.truetype(BOLD_FONT_PATH, fs) if BOLD_FONT_PATH and os.path.exists(BOLD_FONT_PATH) else ImageFont.load_default()
    
    char_width_approx, line_height_approx = fs * 0.6, fs
    try:
        mask_A = fnt.getmask('A');
        cw = mask_A.size[0] if mask_A and mask_A.size[0] > 0 else char_width_approx
        lh = mask_A.size[1] if mask_A and mask_A.size[1] > 0 else line_height_approx
    except AttributeError: cw = char_width_approx; lh = line_height_approx
        
    lines = textwrap.wrap(label, width=max(1, int(W//cw)))
    
    final_text_color_val = text_color_override if text_color_override else text_color(bg_hex)

    if value_str is not None:
        try: val_fnt = ImageFont.truetype(FONT_PATH, value_font_size)
        except IOError: val_fnt = ImageFont.truetype(BOLD_FONT_PATH, value_font_size) if BOLD_FONT_PATH and os.path.exists(BOLD_FONT_PATH) else ImageFont.load_default()
        
        val_lh_approx = value_font_size
        display_value_str = str(value_str)

        if display_value_str:
            try:
                val_mask_0 = val_fnt.getmask('0')
                val_lh = val_mask_0.size[1] if val_mask_0 and val_mask_0.size[1] > 0 else val_lh_approx
            except AttributeError: val_lh = val_lh_approx
        else: val_lh = 0
        
        val_y_margin = 5
        val_y = H - val_lh - val_y_margin
        
        total_label_h = lh*len(lines) + LINE_SPACING*(len(lines)-1 if len(lines)>0 else 0)
        available_h_for_label = val_y - LINE_SPACING if display_value_str and val_lh > 0 else H
        
        y_label_start = (available_h_for_label - total_label_h) // 2
        if y_label_start < 2 : y_label_start = 2

        current_y_for_label = y_label_start
        for ln_item in lines:
            try:
                line_mask = fnt.getmask(ln_item)
                line_width = line_mask.size[0] if line_mask else len(ln_item) * cw
            except AttributeError: line_width = len(ln_item) * cw
            x = (W - line_width)//2; draw.text((x,current_y_for_label), ln_item, font=fnt, fill=final_text_color_val); current_y_for_label += lh + LINE_SPACING
        
        if display_value_str and val_lh > 0:
            temp_display_str = display_value_str
            val_char_width_approx = value_font_size * 0.6
            try:
                val_mask_str = val_fnt.getmask(temp_display_str)
                current_text_width = val_mask_str.size[0] if val_mask_str else len(temp_display_str) * val_char_width_approx
            except AttributeError: current_text_width = len(temp_display_str) * val_char_width_approx

            margin_right = 2
            while current_text_width > (W - margin_right - 2) and len(temp_display_str) > 1:
                temp_display_str = temp_display_str[1:]
                try:
                    val_mask_str_trunc = val_fnt.getmask(temp_display_str)
                    current_text_width = val_mask_str_trunc.size[0] if val_mask_str_trunc else len(temp_display_str) * val_char_width_approx
                except AttributeError: current_text_width = len(temp_display_str) * val_char_width_approx
            
            final_display_value_str = temp_display_str
            final_val_line_width = current_text_width
            val_x = W - final_val_line_width - margin_right
            if val_x < 2: val_x = 2
            draw.text((val_x, val_y), final_display_value_str, font=val_fnt, fill=final_text_color_val)
    else:
        total_h = lh*len(lines) + LINE_SPACING*(len(lines)-1 if len(lines)>0 else 0)
        y = (H - total_h)//2
        if y < 2 : y = 2
        for ln_item in lines:
            try:
                line_mask_no_val = fnt.getmask(ln_item)
                line_width = line_mask_no_val.size[0] if line_mask_no_val else len(ln_item) * cw
            except AttributeError: line_width = len(ln_item) * cw
            x = (W - line_width)//2; draw.text((x,y), ln_item, font=fnt, fill=final_text_color_val); y += lh + LINE_SPACING
            
    return PILHelper.to_native_format(deck, img)

def run_cmd_in_terminal(main_command_resolved,
                        is_activating_at_device=False,
                        at_device_also_has_n_flag=False,
                        button_style_config=None,
                        active_at_device_label=None,
                        is_n_for_at_device_staged_keystroke=False,
                        ssh_command_for_staging="",
                        n_command_for_staging="",
                        prepend_command="",
                        force_new_window_for_at_device=False):

    current_effective_command = main_command_resolved
    if prepend_command:
        current_effective_command = f"{prepend_command}\n{current_effective_command}" if current_effective_command.strip() else prepend_command
    
    current_effective_command = current_effective_command.replace('“', '"').replace('”', '"')
    escaped_command_for_as_do_script = applescript_escape_string(current_effective_command)
    # DEFINE main_command_raw_for_as_logic_check here for all paths
    main_command_raw_for_as_logic_check = applescript_escape_string(current_effective_command)
    
    constructed_applescript = ""
    script_vars = {}
    
    is_cmd_to_active_at_session = active_at_device_label and \
                                  not is_activating_at_device and \
                                  not (button_style_config and button_style_config.get('is_standalone_n_button', False)) and \
                                  not is_n_for_at_device_staged_keystroke

    if not current_effective_command.strip() and \
       not is_activating_at_device and \
       not is_cmd_to_active_at_session and \
       not (is_n_for_at_device_staged_keystroke and ssh_command_for_staging):
        print("[DEBUG] run_cmd_in_terminal: No script payload and no relevant device interaction. No action.")
        return

    if is_n_for_at_device_staged_keystroke:
        if not button_style_config or not ssh_command_for_staging:
            print(f"[ERROR] run_cmd_in_terminal: Missing info for N-for-@-staged. Style: {button_style_config}, SSH: {ssh_command_for_staging}")
            return
        print(f"[DEBUG] N-Button (for active @, staged): New window styled like '{button_style_config['lbl']}'.")
        script_vars['window_custom_title'] = applescript_escape_string(button_style_config['lbl'])
        script_vars['aps_bg_color'] = hex_to_aps_color_values_str(button_style_config['bg_hex'])
        script_vars['aps_text_color'] = "{65535,65535,65535}" if button_style_config.get('text_color_name', 'white') == 'white' else "{0,0,0}"
        script_vars['ssh_command_to_keystroke'] = applescript_escape_string(ssh_command_for_staging)
        script_vars['actual_n_command_to_keystroke'] = applescript_escape_string(n_command_for_staging)
        constructed_applescript = load_applescript_template("terminal_n_for_at_staged_keystroke.txt", **script_vars)

    elif is_activating_at_device:
        if not button_style_config or 'lbl' not in button_style_config:
            print(f"[ERROR] run_cmd_in_terminal: Missing style config for @-device activation. Button Label: {button_style_config.get('lbl','Unknown') if button_style_config else 'None'}")
            if current_effective_command.strip():
                script_vars['final_script_payload_for_do_script'] = escaped_command_for_as_do_script
                print(f"[WARN] Missing style config for @-device activation, falling back to default execution for: {current_effective_command}")
                constructed_applescript = load_applescript_template("terminal_do_script_default.txt", **script_vars)
            else: return
        else:
            device_label = button_style_config['lbl']
            script_vars['escaped_device_label'] = applescript_escape_string(device_label)
            script_vars['aps_bg_color'] = hex_to_aps_color_values_str(button_style_config['bg_hex'])
            script_vars['aps_text_color'] = "{65535,65535,65535}" if button_style_config.get('text_color_name', 'white') == 'white' else "{0,0,0}"
            
            if at_device_also_has_n_flag:
                print(f"[DEBUG] @N-Button '{device_label}': Forcing new styled window.")
                script_vars['final_script_payload'] = escaped_command_for_as_do_script
                constructed_applescript = load_applescript_template("terminal_activate_new_styled_at_n.txt", **script_vars)
            else:
                print(f"[DEBUG] @-Button '{device_label}': Find existing or new styled window.")
                script_vars['final_script_payload_for_do_script'] = escaped_command_for_as_do_script
                script_vars['force_new_window'] = "true" if force_new_window_for_at_device else "false"
                constructed_applescript = load_applescript_template("terminal_activate_found_at_only.txt", **script_vars)

    elif button_style_config and button_style_config.get('is_standalone_n_button', False):
        cfg = button_style_config
        script_vars['window_custom_title'] = applescript_escape_string(cfg['lbl'])
        script_vars['aps_bg_color'] = hex_to_aps_color_values_str(cfg['bg_hex'])
        script_vars['aps_text_color'] = "{65535,65535,65535}" if cfg.get('text_color_name', 'white') == 'white' else "{0,0,0}"
        script_vars['final_script_payload_for_do_script'] = escaped_command_for_as_do_script
        print(f"[DEBUG] N-Button (standalone) creating new window titled '{cfg['lbl']}'.")
        constructed_applescript = load_applescript_template("terminal_activate_standalone_n.txt", **script_vars)
        
    elif is_cmd_to_active_at_session:
        script_vars['safe_target_title'] = applescript_escape_string(active_at_device_label)
        script_vars['final_script_payload_for_do_script'] = escaped_command_for_as_do_script
        script_vars['main_command_raw_for_emptiness_check'] = main_command_raw_for_as_logic_check
        script_vars['command_to_type_literally_content'] = escaped_command_for_as_do_script
        
        print(f"[DEBUG] Command to active @-device '{active_at_device_label}'. Using 'terminal_command_to_active_at_device.txt'.")
        constructed_applescript = load_applescript_template("terminal_command_to_active_at_device.txt", **script_vars)
        
    else:
        if not current_effective_command.strip():
            print("[DEBUG] Default execution path, but command is empty.")
        else:
            script_vars['final_script_payload_for_do_script'] = escaped_command_for_as_do_script
            print(f"[DEBUG] Default command execution. Payload: '{escaped_command_for_as_do_script}'")
            constructed_applescript = load_applescript_template("terminal_do_script_default.txt", **script_vars)

    if constructed_applescript:
        proc_term = subprocess.run(["osascript", "-"], input=constructed_applescript, text=True, capture_output=True, check=False)
        
        if proc_term.returncode != 0:
            stderr_lower_run = proc_term.stderr.lower()
            if "(-128)" in stderr_lower_run:
                 print(f"[INFO] osascript execution cancelled by user (RC: {proc_term.returncode}). stderr: {proc_term.stderr.strip()}")
            elif "(-1712)" in stderr_lower_run:
                print(f"[INFO] osascript execution timed out (RC: {proc_term.returncode}). stderr: {proc_term.stderr.strip()}")
            else:
                print(f"[ERROR] AppleScript for Terminal failed. RC: {proc_term.returncode}\nSTDERR: {proc_term.stderr.strip()}\nSTDOUT: {proc_term.stdout.strip()}")
                print(f"--- PROBLEM AS SCRIPT START (RC: {proc_term.returncode}) ---\n{constructed_applescript}\n--- PROBLEM AS SCRIPT END ---", file=sys.stderr)
        
        if proc_term.stderr.strip() and \
           "(-128)" not in proc_term.stderr and \
           not ("execution error" in proc_term.stderr.strip().lower() and "(-1753)" in proc_term.stderr.strip()):
             print(f"[INFO] AppleScript internal log/stderr: {proc_term.stderr.strip()}")

# (The rest of the file is from streamdeck_driver_Works.py, with noted integrations)
# Key globals
labels, cmds, flags = {}, {}, {} # From Works
page_index = 0                 # From Works
numeric_mode, numeric_var = False, None # From Works
active_device_key = None       # Added for @-device tracking
press_times, toggle_keys = {}, set() # From Works (toggle_keys might need refinement for @ vs #)
long_press_numeric_active = False # Added for full numeric mode state
flash_state = False             # Added for numeric mode flashing
deck = None                     # From Works
items = []                      # Added to be global for build_page

if __name__ == "__main__":
    print("[INFO] Initializing Stream Deck Driver...")
    
    def build_page(idx): # Based on Works, uses global items
        global labels, cmds, flags, items, up_key_idx, down_key_idx, load_key_idx, cnt, page_index
        
        if not items and idx != 0 :
            print(f"[WARN] build_page called for index {idx} with no items. Page remains {page_index}.")
            idx = page_index

        parsed_flags_list = [(it_item, parse_flags(it_item[2])) for it_item in items]
        sticky_items_with_flags = [pf for pf in parsed_flags_list if pf[1][2]]
        normal_items_with_flags = [pf for pf in parsed_flags_list if not pf[1][2]]
        
        # load_key_idx, up_key_idx, down_key_idx are now set globally after deck init
        fixed_slots = {load_key_idx, up_key_idx, down_key_idx}
        all_slots = list(range(cnt))
        available_slots_for_buttons = [s for s in all_slots if s not in fixed_slots]
        
        new_labels, new_cmds_dict, new_flgs = {}, {}, {}

        current_sticky_idx_in_available = 0
        for item_data_tuple, _parsed_flag_tuple in sticky_items_with_flags:
            if current_sticky_idx_in_available < len(available_slots_for_buttons):
                slot_key = available_slots_for_buttons[current_sticky_idx_in_available]
                new_labels[slot_key], new_cmds_dict[slot_key], new_flgs[slot_key] = item_data_tuple
                current_sticky_idx_in_available += 1
            else: break
            
        slots_for_normal_items = available_slots_for_buttons[current_sticky_idx_in_available:]
        num_normal_slots_per_page = len(slots_for_normal_items)

        if num_normal_slots_per_page == 0 and normal_items_with_flags:
            print("[WARN] No slots for normal items after sticky ones.")
        
        total_normal_pages = 1
        if normal_items_with_flags and num_normal_slots_per_page > 0:
            total_normal_pages = ceil(len(normal_items_with_flags) / num_normal_slots_per_page)
        
        current_page_num_for_normal = idx % total_normal_pages if total_normal_pages > 0 else 0
        start_normal_item_idx_from_list = current_page_num_for_normal * num_normal_slots_per_page
        
        for i_slot_for_normal in range(len(slots_for_normal_items)):
            slot_key = slots_for_normal_items[i_slot_for_normal]
            current_normal_item_overall_idx = start_normal_item_idx_from_list + i_slot_for_normal
            
            if current_normal_item_overall_idx < len(normal_items_with_flags):
                item_data_tuple, _ = normal_items_with_flags[current_normal_item_overall_idx]
                new_labels[slot_key], new_cmds_dict[slot_key], new_flgs[slot_key] = item_data_tuple
            else:
                new_labels[slot_key], new_cmds_dict[slot_key], new_flgs[slot_key] = "", "", ""

        new_labels[load_key_idx], new_cmds_dict[load_key_idx], new_flgs[load_key_idx] = "LOAD","","W"
        new_labels[up_key_idx], new_cmds_dict[up_key_idx], new_flgs[up_key_idx] = "▲","","W"
        new_labels[down_key_idx], new_cmds_dict[down_key_idx], new_flgs[down_key_idx] = "▼","","W"
        
        labels, cmds, flags = new_labels, new_cmds_dict, new_flgs

    def redraw():
        global labels, cmds, flags, numeric_mode, numeric_var, active_device_key, current_session_vars, up_key_idx, down_key_idx, load_key_idx, cnt, deck, long_press_numeric_active, flash_state
        
        if not deck: return

        for i_key in range(cnt):
            f_str = flags.get(i_key, ""); cmd_str = cmds.get(i_key, "")
            lbl_str = labels.get(i_key, "")
            
            is_up_arrow = (i_key == up_key_idx)
            is_down_arrow = (i_key == down_key_idx)

            _nw_flag_rd, dev_flag_rd, _sticky_flag_rd, bg_color_val_rd, fs_val_rd = parse_flags(f_str)
            
            current_bg_to_use = bg_color_val_rd
            text_color_to_use_auto = text_color(current_bg_to_use)
            value_to_display_on_key = None
            is_styled_by_active_numeric_mode = False

            if numeric_mode and long_press_numeric_active and numeric_var:
                numeric_var_key_idx_frm_dict = numeric_var.get('key')
                
                if i_key == numeric_var_key_idx_frm_dict or is_up_arrow or is_down_arrow:
                    is_styled_by_active_numeric_mode = True
                    original_flags_of_numeric_trigger = flags.get(numeric_var_key_idx_frm_dict, "")
                    _, _, _, color_of_numeric_trigger, _ = parse_flags(original_flags_of_numeric_trigger)
                    bright_color_for_numeric_mode = toggle_button_bg(color_of_numeric_trigger)

                    if flash_state:
                        current_bg_to_use = bright_color_for_numeric_mode
                    else:
                        if i_key == numeric_var_key_idx_frm_dict:
                            current_bg_to_use = color_of_numeric_trigger
                        else:
                            try:
                                r_dim, g_dim, b_dim = [int(bright_color_for_numeric_mode[c:c+2],16)//2 for c in (1,3,5)]
                                current_bg_to_use = f"#{r_dim:02X}{g_dim:02X}{b_dim:02X}"
                            except: current_bg_to_use = BASE_COLORS['E']
                    text_color_to_use_auto = text_color(current_bg_to_use)

                    if i_key == numeric_var_key_idx_frm_dict:
                        var_val_numeric = current_session_vars.get(numeric_var['name'])
                        if isinstance(var_val_numeric, (int, float)):
                            try:
                                f_val = float(var_val_numeric)
                                value_to_display_on_key = f"{f_val:.1f}" if not f_val.is_integer() else str(int(f_val))
                            except (TypeError, ValueError): value_to_display_on_key = str(var_val_numeric)[:6]
                        else: value_to_display_on_key = str(var_val_numeric)[:6]
                    elif is_up_arrow or is_down_arrow:
                        step = numeric_var.get('step', 1.0)
                        op = "+" if is_up_arrow else "-"
                        try:
                            f_step = float(step)
                            value_to_display_on_key = f"{op}{f_step:.1f}" if not f_step.is_integer() else f"{op}{int(f_step)}"
                        except (TypeError, ValueError): value_to_display_on_key = f"{op}{step}"

            if not is_styled_by_active_numeric_mode and dev_flag_rd:
                if active_device_key == i_key:
                    current_bg_to_use = toggle_button_bg(bg_color_val_rd)
                else:
                    if bg_color_val_rd != BASE_COLORS['K']:
                        try:
                            r_dim_at, g_dim_at, b_dim_at = [int(bg_color_val_rd[c:c+2],16)//2 for c in (1,3,5)]
                            current_bg_to_use = f"#{r_dim_at:02X}{g_dim_at:02X}{b_dim_at:02X}"
                        except: pass
                text_color_to_use_auto = text_color(current_bg_to_use)

            if not is_styled_by_active_numeric_mode and not (dev_flag_rd and active_device_key == i_key) :
                if 'V' in f_str.upper() or ('#' in f_str and not (numeric_mode and numeric_var and i_key == numeric_var.get('key')) ) :
                    all_vars_in_cmd = VAR_PATTERN.finditer(cmd_str)
                    values_to_show = []
                    for var_match_val_disp in all_vars_in_cmd:
                        var_name_val_disp = var_match_val_disp.group(1)
                        var_val_on_btn = current_session_vars.get(var_name_val_disp)
                        if var_val_on_btn is not None:
                            if '#' in f_str:
                                try:
                                    num_val_on_btn = float(var_val_on_btn)
                                    values_to_show.append(f"{num_val_on_btn:.1f}" if not num_val_on_btn.is_integer() else str(int(num_val_on_btn)))
                                except ValueError:
                                    values_to_show.append(str(var_val_on_btn))
                            else:
                                values_to_show.append(str(var_val_on_btn))
                    
                    if values_to_show:
                        value_to_display_on_key = " ".join(values_to_show)
            
            final_font_size = ARROW_FONT_SIZE if (is_up_arrow or is_down_arrow) else fs_val_rd
            
            try:
                deck.set_key_image(i_key, render_key(lbl_str, deck, current_bg_to_use, final_font_size,
                                                     text_color_override=text_color_to_use_auto,
                                                     value_str=value_to_display_on_key,
                                                     value_font_size=DEFAULT_FONT_SIZE-2))
            except Exception as e_render:
                print(f"[ERROR] Failed to render/set key {i_key} ('{lbl_str}'): {e_render}")
                error_img = PILHelper.create_image(deck)
                draw_err = ImageDraw.Draw(error_img)
                draw_err.rectangle([(0,0),deck.key_image_format()['size']], fill='red')
                draw_err.text((5,5), "ERR", fill='white', font=ImageFont.load_default())
                try:
                    deck.set_key_image(i_key, PILHelper.to_native_format(deck, error_img))
                except: pass
    
    def load_data_and_reinit_vars():
        global items, current_session_vars, page_index, numeric_mode, numeric_var, active_device_key, toggle_keys, long_press_numeric_active, deck, at_devices_to_reinit_cmd, flash_state
        print("[INFO] Rebuilding database from Numbers and reloading configurations...")
        if os.path.exists(DB_PATH):
            try: os.remove(DB_PATH)
            except OSError as e: print(f"[ERROR] Could not remove old DB {DB_PATH}: {e}")
        
        try:
            python_executable = sys.executable
            load_proc_result = subprocess.run([python_executable, str(LOAD_SCRIPT), str(DB_PATH)], check=True, capture_output=True, text=True)
            if load_proc_result.stdout: print(f"[INFO] DB Load Script STDOUT:\n{load_proc_result.stdout.strip()}")
            if load_proc_result.stderr: print(f"[ERROR] DB Load Script STDERR:\n{load_proc_result.stderr.strip()}")
        except subprocess.CalledProcessError as load_err:
             print(f"[FATAL] DB Load Script failed with RC {load_err.returncode}.")
             if load_err.stdout: print(f"    STDOUT:\n{load_err.stdout}")
             if load_err.stderr: print(f"    STDERR:\n{load_err.stderr}")
             if deck:
                 try: deck.reset(); deck.close()
                 except: pass
             sys.exit(1)
        except Exception as load_err_generic:
            print(f"[FATAL] DB Load Script failed: {load_err_generic}. Exiting.")
            if deck:
                try: deck.reset(); deck.close()
                except: pass
            sys.exit(1)

        items[:] = get_items()
        initialize_session_vars_from_items(items, current_session_vars)

        page_index = 0
        numeric_mode = False ; numeric_var = None; long_press_numeric_active = False
        active_device_key = None
        toggle_keys.clear()
        at_devices_to_reinit_cmd.clear()
        flash_state = False
        
        if not items: print("[WARNING] No items loaded from database after rebuild.")
        if deck: build_page(page_index)

    try:
        all_decks = DeviceManager().enumerate()
        if not all_decks: print("No Stream Deck found"); sys.exit(1)
        deck = all_decks[0]
        deck.open()
        deck.reset()
        print(f"[INFO] Opened Stream Deck: {deck.deck_type()} ({deck.key_count()} keys)")
    except TransportError as e_transport:
        print(f"[FATAL] Could not connect to Stream Deck (TransportError): {e_transport}")
        print("         Ensure no other Stream Deck software is running.")
        sys.exit(1)
    except Exception as e_deck_init:
        print(f"[FATAL] Could not initialize Stream Deck: {e_deck_init}")
        if deck:
            try: deck.close()
            except: pass
        sys.exit(1)
    
    cnt = deck.key_count()
    key_layout = deck.key_layout()
    cols = key_layout[1]
    
    load_key_idx = 0
    if cnt == 15 and cols == 5:
        up_key_idx = 5
        down_key_idx = 10
    else: # Fallback to original Works.py logic
        up_key_idx = cnt // 3
        down_key_idx = 2 * (cnt // 3)
        
    print(f"[INFO] Key layout: {key_layout[0]} rows, {cols} cols. LOAD: {load_key_idx}, UP: {up_key_idx}, DOWN: {down_key_idx}")

    load_data_and_reinit_vars()

    def callback(deck_param, key_index, state):
        global page_index, numeric_mode, numeric_var, active_device_key, labels, cmds, flags, items, toggle_keys, current_session_vars, press_times, long_press_numeric_active, up_key_idx, down_key_idx, load_key_idx, at_devices_to_reinit_cmd, flash_state

        k_idx = key_index
        if state:
            press_times[k_idx] = time.time()
            return

        press_duration = time.time() - press_times.pop(k_idx, time.time())
        is_long_press = press_duration >= LONG_PRESS_THRESHOLD
        
        current_cmd_str_template = cmds.get(k_idx,"")
        current_flag_str = flags.get(k_idx,"")
        current_label_str = labels.get(k_idx, "")
        nw_flag_cb, dev_flag_cb, _sticky_flag_cb, bg_color_val_cb, _fs_val_cb = parse_flags(current_flag_str)
        
        print(f"\n--- Callback Start (Key Released) ---")
        print(f"[PY_DEBUG] Key: {k_idx}, Label: '{current_label_str}', Flags: '{current_flag_str}', LongPress: {is_long_press}, Duration: {press_duration:.2f}s")
        
        if k_idx == load_key_idx and not is_long_press:
            print("[DEBUG] Callback: LOAD key pressed.");
            load_data_and_reinit_vars()
            return

        if numeric_mode and long_press_numeric_active and numeric_var:
            numeric_var_key_idx_nm = numeric_var.get('key')
            
            if k_idx == numeric_var_key_idx_nm:
                print(f"[DEBUG] Exiting numeric mode (was active) due to press on its own key {k_idx}.")
                numeric_mode = False; numeric_var = None; long_press_numeric_active = False; flash_state = False
                toggle_keys.clear()
                if active_device_key is not None: toggle_keys.add(active_device_key)
                return

            elif k_idx == up_key_idx or k_idx == down_key_idx:
                step_val = numeric_var.get('step', 1.0)
                if is_long_press: step_val *= 5
                
                try: current_val_num = float(current_session_vars.get(numeric_var['name'], "0.0"))
                except ValueError: current_val_num = 0.0
                
                new_value_num = current_val_num + step_val if k_idx == up_key_idx else current_val_num - step_val
                current_session_vars[numeric_var['name']] = new_value_num
                
                cmd_to_run_num_adj = resolve_command_string(numeric_var['cmd_template'], current_session_vars)
                print(f"[DEBUG] Numeric {'LP ' if is_long_press else ''}{'increment' if k_idx == up_key_idx else 'decrement'}. Var: {numeric_var['name']}, NewVal: {new_value_num}, Step: {step_val}, Cmd: '{cmd_to_run_num_adj}'")
                
                active_at_device_label_for_num_cmd = labels.get(active_device_key) if active_device_key is not None else None
                run_cmd_in_terminal(cmd_to_run_num_adj,
                                    active_at_device_label=active_at_device_label_for_num_cmd)
                return
            
            else:
                print(f"[DEBUG] Exiting numeric mode (was active) due to press on other key {k_idx}. Will proceed to handle key {k_idx}.")
                numeric_mode = False; numeric_var = None; long_press_numeric_active = False; flash_state = False
                toggle_keys.clear()
                if active_device_key is not None: toggle_keys.add(active_device_key)
        
        if not (numeric_mode and long_press_numeric_active) and not is_long_press:
             if k_idx == up_key_idx:
                 page_index = (page_index - 1)
                 print(f"[DEBUG] Page UP. New index: {page_index}")
                 build_page(page_index); return
             if k_idx == down_key_idx:
                 page_index = (page_index + 1)
                 print(f"[DEBUG] Page DOWN. New index: {page_index}")
                 build_page(page_index); return
        
        if '#' in current_flag_str and is_long_press:
            print(f"[DEBUG] LONG press on # button {k_idx}. Entering numeric adjust setup.")
            var_match_num_setup = VAR_PATTERN.search(current_cmd_str_template)
            if not var_match_num_setup:
                print(f"[ERROR] Command for # button {k_idx} ('{current_label_str}') has no variable: '{current_cmd_str_template}'"); return
            
            var_name_num_mode = var_match_num_setup.group(1)
            default_val_from_cmd_num = var_match_num_setup.group(3) if var_match_num_setup.group(3) is not None else "0"
            current_val_for_prompt_num_start = current_session_vars.get(var_name_num_mode, default_val_from_cmd_num)
            
            start_value_num_str = str(current_val_for_prompt_num_start)
            try:
                float(start_value_num_str)
            except ValueError:
                user_start_val_str = execute_applescript_dialog(f"Enter START value for {var_name_num_mode}:", start_value_num_str)
                if user_start_val_str and user_start_val_str not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT", None]:
                    start_value_num_str = user_start_val_str
                elif user_start_val_str is None:
                    print(f"[ERROR] Start value prompt failed for {var_name_num_mode}. Aborting numeric mode setup."); return
                else:
                    print(f"[INFO] Start value prompt cancelled/timed out for {var_name_num_mode}. Aborting numeric mode setup."); return
            
            try: start_value_for_num_mode = float(start_value_num_str)
            except ValueError: start_value_for_num_mode = 0.0; print(f"[WARN] Invalid start value '{start_value_num_str}', using 0.0.")
            
            user_step_str = execute_applescript_dialog(f"Enter INCREMENT for {var_name_num_mode} (e.g., 1 or -0.5):", "1")
            if user_step_str is None or user_step_str in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                print(f"[INFO] Step prompt cancelled/timed out for {var_name_num_mode}. Aborting numeric mode setup."); return

            try: step_for_num_var = float(user_step_str)
            except ValueError: step_for_num_var = 1.0; print(f"[WARN] Invalid step '{user_step_str}', using 1.0.")

            current_session_vars[var_name_num_mode] = start_value_for_num_mode
            numeric_mode = True; long_press_numeric_active = True; flash_state = True
            numeric_var = {"name": var_name_num_mode, "value": start_value_for_num_mode, "step": step_for_num_var, "cmd_template": current_cmd_str_template, "key": k_idx}
            
            toggle_keys.clear();
            toggle_keys.add(k_idx);
            print(f"[INFO] Entered numeric mode for var '{var_name_num_mode}', key {k_idx}. Start: {start_value_for_num_mode}, Step: {step_for_num_var}.")
            return
        
        elif dev_flag_cb and not is_long_press: # Press on an @-button (or @N button)
            print(f"[PY_DEBUG] @-Device button action for key {k_idx} ('{current_label_str}')")
            # This config is for styling the new window IF one is created for THIS @-device.
            run_cfg_button_style_config = {
                "lbl": current_label_str,
                "bg_hex": bg_color_val_cb,
                "text_color_name": text_color(bg_color_val_cb)
            }
            
            force_reinit_this_time = False
            if k_idx in at_devices_to_reinit_cmd:
                force_reinit_this_time = True
                at_devices_to_reinit_cmd.remove(k_idx)
                print(f"[DEBUG] Forcing command re-execution (re-init) for @-device {k_idx} ('{current_label_str}')")

            if active_device_key == k_idx and not force_reinit_this_time:
                print(f"[PY_DEBUG] Toggling OFF @-device: {k_idx} ('{current_label_str}')")
                active_device_key = None
                if k_idx in toggle_keys: toggle_keys.remove(k_idx)
            else:
                if active_device_key is not None and active_device_key in toggle_keys and active_device_key != k_idx:
                    print(f"[PY_DEBUG] Deactivating previous @-device: {active_device_key} ('{labels.get(active_device_key,'')}')")
                    toggle_keys.remove(active_device_key)
                
                print(f"[PY_DEBUG] Toggling ON @-device: {k_idx} ('{current_label_str}')")
                active_device_key = k_idx
                toggle_keys.add(k_idx)
                
                at_device_cmd_resolved = resolve_command_string(current_cmd_str_template, current_session_vars)
                print(f"[DEBUG] Executing @-device activation command: '{at_device_cmd_resolved}' for key {k_idx} ('{current_label_str}')")
                
                run_cmd_in_terminal(
                    at_device_cmd_resolved,
                    is_activating_at_device=True, # This button itself is an @ or @N
                    at_device_also_has_n_flag=nw_flag_cb, # If it's an @N
                    button_style_config=run_cfg_button_style_config, # Its own style
                    force_new_window_for_at_device=force_reinit_this_time
                )
            return
        
        elif 'V' in current_flag_str.upper() and is_long_press:
            print(f"[DEBUG] V-flag LP on key {k_idx} for command: '{current_cmd_str_template}'")
            variables_found_in_command = list(VAR_PATTERN.finditer(current_cmd_str_template))
            
            if not variables_found_in_command:
                print(f"[ERROR] V-flag button {k_idx} ('{current_label_str}') has no variables in command: '{current_cmd_str_template}'"); return

            made_a_change_in_v_vars = False
            for var_match_v_loop in variables_found_in_command:
                var_name_v = var_match_v_loop.group(1)
                default_val_v_from_template = var_match_v_loop.group(3) if var_match_v_loop.group(3) is not None else ""
                current_val_for_prompt_v = str(current_session_vars.get(var_name_v, default_val_v_from_template))
                
                print(f"[DEBUG] V-flag: Prompting for '{var_name_v}'. Current value: '{current_val_for_prompt_v}' (template default: '{default_val_v_from_template}')")
                user_input_v = execute_applescript_dialog(f"Enter value for {var_name_v}:", current_val_for_prompt_v)
                
                if user_input_v == "USER_CANCELLED_PROMPT" or user_input_v == "USER_TIMEOUT_PROMPT":
                    print(f"[INFO] V-flag prompt for '{var_name_v}' cancelled or timed out. No change for this variable.")
                elif user_input_v is None:
                    print(f"[ERROR] V-flag prompt for '{var_name_v}' resulted in an error. No change for this variable.")
                else:
                    if current_session_vars.get(var_name_v) != user_input_v:
                        current_session_vars[var_name_v] = user_input_v
                        print(f"[DEBUG] Updated session var '{var_name_v}' to '{user_input_v}' via LP 'V'.")
                        made_a_change_in_v_vars = True
                    else:
                        print(f"[DEBUG] Session var '{var_name_v}' remains '{user_input_v}' (no change entered by user).")
            
            if dev_flag_cb:
                at_devices_to_reinit_cmd.add(k_idx)
                print(f"[DEBUG] @-device {k_idx} ('{current_label_str}') marked for re-initialization due to V-flag Long Press (actual value change: {made_a_change_in_v_vars}).")
                if k_idx == active_device_key:
                    active_device_key = None
                    if k_idx in toggle_keys: toggle_keys.remove(k_idx)
            return
        
        elif is_long_press and current_cmd_str_template and not dev_flag_cb and '#' not in current_flag_str and 'V' not in current_flag_str.upper() and k_idx not in [load_key_idx, up_key_idx, down_key_idx]:
            label_for_prompt_edit = current_label_str or f"Button {k_idx}"
            print(f"[DEBUG] Generic LP on key {k_idx} ('{label_for_prompt_edit}'). Prompting to edit command.")
            user_input_edit = execute_applescript_dialog(f"Edit command for '{label_for_prompt_edit}':", current_cmd_str_template)
            
            if user_input_edit and user_input_edit not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT", None]:
                if user_input_edit != current_cmd_str_template:
                    cmds[k_idx] = user_input_edit
                    initialize_session_vars_from_items(items, current_session_vars)
                    print(f"[INFO] Command for key {k_idx} ('{label_for_prompt_edit}') updated in memory to: '{user_input_edit}'. Session vars re-initialized.")
                    print(f"[WARNING] This in-memory command edit will be lost on next LOAD from Numbers or restart.")
                else: print(f"[INFO] Command for key {k_idx} ('{label_for_prompt_edit}') not changed by user.")
            elif user_input_edit is None: print(f"[ERROR] Edit command dialog failed for key {k_idx}.")
            else: print(f"[INFO] Edit command cancelled/timed out for key {k_idx}.")
            return

        if not current_cmd_str_template and not (k_idx == load_key_idx or k_idx == up_key_idx or k_idx == down_key_idx) :
            print(f"[DEBUG] Callback: No command configured for key {k_idx} ('{current_label_str}'). Doing nothing."); return
        
        # --- Final Command Execution Logic (for non-@-activation presses, non-LP special V/#) ---
        print(f"[PY_DEBUG_CMD_EXEC] Key Press for command processing: {k_idx}, Label: '{current_label_str}'")
        
        command_from_button_resolved = resolve_command_string(current_cmd_str_template, current_session_vars)
        
        # Params for run_cmd_in_terminal
        param_main_command = command_from_button_resolved
        param_is_activating_at_device = False # This path is for *non* @-activation presses
        param_at_device_also_has_n_flag = False # Not relevant if not activating @-device
        param_button_style_config = None
        param_active_at_device_label = labels.get(active_device_key) if active_device_key is not None else None
        param_is_n_for_at_device_staged_keystroke = False
        param_ssh_command_for_staging = ""
        param_n_command_for_staging = ""

        if nw_flag_cb: # Current button has N-flag (and it's NOT an @N button, as dev_flag_cb was false here)
            if not dev_flag_cb: # Pure N-button
                if param_active_at_device_label and active_device_key is not None:
                    # Pure N-button WITH an active @-device: Use STAGED KEYSTROKE approach
                    param_is_n_for_at_device_staged_keystroke = True
                    
                    active_at_device_flag_str = flags.get(active_device_key, "")
                    _, _, _, at_device_bg_hex, _ = parse_flags(active_at_device_flag_str)
                    
                    param_button_style_config = {
                        "lbl": param_active_at_device_label,
                        "bg_hex": at_device_bg_hex,
                        "text_color_name": text_color(at_device_bg_hex)
                    }
                    print(f"[DEBUG_CB] N-Button '{current_label_str}' for active @-device '{param_active_at_device_label}'. Staged keystroke. New window styled like @-device.")

                    active_at_device_cmd_template = cmds.get(active_device_key, "")
                    if active_at_device_cmd_template:
                        resolved_at_device_cmd = resolve_command_string(active_at_device_cmd_template, current_session_vars)
                        ssh_match = re.match(r"^(ssh\s+[\w\.-]+@[\w\.-]+|ssh\s+[\w\.-]+)", resolved_at_device_cmd, re.IGNORECASE)
                        if ssh_match:
                            param_ssh_command_for_staging = ssh_match.group(0)
                            param_n_command_for_staging = command_from_button_resolved
                            param_main_command = "" # Main command ignored for staged, uses specific vars for keystrokes
                            print(f"[DEBUG_CB]   SSH part: '{param_ssh_command_for_staging}', N-Cmd part: '{param_n_command_for_staging}'")
                        else:
                            print(f"[WARN] Could not extract SSH prefix for staged N. N-command '{command_from_button_resolved}' runs locally in new window styled like @-device.")
                            param_is_n_for_at_device_staged_keystroke = False
                            if param_button_style_config: param_button_style_config['is_standalone_n_button'] = True
                            else: param_button_style_config = {"lbl": current_label_str or "N-Window", "bg_hex": bg_color_val_cb, "text_color_name": text_color(bg_color_val_cb), "is_standalone_n_button": True}
                            param_main_command = command_from_button_resolved # Fallback to local execution
                    else:
                        print(f"[WARN] Active @-device {active_device_key} has no command. Staged N cannot get SSH. Runs locally.")
                        param_is_n_for_at_device_staged_keystroke = False
                        if param_button_style_config: param_button_style_config['is_standalone_n_button'] = True
                        else: param_button_style_config = {"lbl": current_label_str or "N-Window", "bg_hex": bg_color_val_cb, "text_color_name": text_color(bg_color_val_cb), "is_standalone_n_button": True}
                        param_main_command = command_from_button_resolved
                else:
                    # Pure N-button, NO active @-device.
                    print(f"[DEBUG_CB] Pure N-button '{current_label_str}' (no active @-device). New window styled by N-button's flags.")
                    param_button_style_config = {
                        "lbl": current_label_str or "N-Window",
                        "bg_hex": bg_color_val_cb,
                        "text_color_name": text_color(bg_color_val_cb),
                        "is_standalone_n_button": True
                    }
                    param_main_command = command_from_button_resolved
        
        print(f"[DEBUG] Calling run_cmd_in_terminal. Main cmd: '{param_main_command}', IsStagedN: {param_is_n_for_at_device_staged_keystroke}")
        run_cmd_in_terminal(
            param_main_command,
            is_activating_at_device=param_is_activating_at_device, # Should be False here
            at_device_also_has_n_flag=param_at_device_also_has_n_flag, # Should be False here
            button_style_config=param_button_style_config,
            active_at_device_label=param_active_at_device_label if not param_is_n_for_at_device_staged_keystroke else None,
            is_n_for_at_device_staged_keystroke=param_is_n_for_at_device_staged_keystroke,
            ssh_command_for_staging=param_ssh_command_for_staging,
            n_command_for_staging=param_n_command_for_staging
        )

    deck.set_key_callback(callback)
    redraw()

    print("Stream Deck initialized. Listening for key presses...")
    try:
        while True:
            if numeric_mode and long_press_numeric_active:
                flash_state = not flash_state
            elif flash_state:
                flash_state = False
            
            redraw()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt: print("\nExiting Stream Deck driver...")
    except Exception as e_main_loop:
        print(f"[FATAL] Unhandled exception in main loop: {e_main_loop}")
        import traceback
        traceback.print_exc()
    finally:
        print("Resetting and closing Stream Deck.")
        if deck:
            try:
                deck.reset()
                deck.close()
            except Exception as e_close:
                print(f"[ERROR] Exception during Stream Deck close: {e_close}")
        print("Exited.")

# END OF FILE: streamdeck_driver.py

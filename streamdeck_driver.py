#!/usr/bin/env python3
import sqlite3
import subprocess
import sys
import time
import textwrap
import re
import json
from pathlib import Path
from math import ceil
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    Image = ImageDraw = ImageFont = None
    print(f"[WARNING] Pillow library missing: {e}")

try:
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Transport.Transport import TransportError
    from StreamDeck.ImageHelpers import PILHelper
except ImportError as e:
    DeviceManager = None
    class TransportError(Exception):
        pass
    class DummyPILHelper:
        @staticmethod
        def create_image(deck):
            return Image.new('RGB', deck.key_image_format()['size']) if Image else None
        @staticmethod
        def to_native_format(deck, img):
            return img
    PILHelper = DummyPILHelper
    print(f"[WARNING] StreamDeck library missing: {e}")

# === Application Directories & Files ===
APP_DIR = Path.home() / "Library" / "StreamDeckDriver"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "streamdeck.db"
LOAD_SCRIPT = APP_DIR / "streamdeck_db.py"
PERSISTENT_VARS_FILE = APP_DIR / "persistent_vars.json"

# === Persistent Vars ===
VAR_PATTERN = re.compile(r"\{\{([A-Z][A-Z0-9_]*)[:]?([^}]*)?\}\}")

def load_persistent_vars():
    try:
        with open(PERSISTENT_VARS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_persistent_vars(data):
    with open(PERSISTENT_VARS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def applescript_escape_string(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')

def execute_applescript_dialog(prompt_message, default_answer=""):
    default_answer_literal = json.dumps(default_answer)
    script = f'''
    tell application "System Events"
        try
            activate 
            display dialog "{prompt_message}" default answer {default_answer_literal} buttons {{"Cancel", "OK"}} default button "OK" cancel button "Cancel" giving up after 120
            set dialog_result to the result
            if button returned of dialog_result is "OK" then
                return text returned of dialog_result
            else
                return "USER_CANCELLED_PROMPT"
            end if
        on error errMsg number errNum
            if errNum is -128 then return "USER_CANCELLED_PROMPT"
            if errNum is -1712 then return "USER_TIMEOUT_PROMPT"
            return "APPLETSCRIPT_ERROR:" & errNum & ":" & errMsg
        end try
    end tell
    '''
    # print(f"[DEBUG] Executing AppleScript Dialog:\n{script}")
    proc = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True)
    if proc.returncode == 0:
        output = proc.stdout.strip()
        if output.startswith("APPLETSCRIPT_ERROR:"):
            print(f"[ERROR] AppleScript Dialog Error: {output}")
            return None
        return output
    else:
        print(f"[ERROR] osascript process error for dialog. RC: {proc.returncode}, Err: {proc.stderr.strip()}")
        return None


def handle_numeric_toggle_init(key, cmd, persistent_vars, prompt_for_initial_value=True):
    match = VAR_PATTERN.search(cmd)
    if not match: return None
    var_name = match.group(1)
    raw_default_from_cmd = match.group(2)
    initial_val_str = persistent_vars.get(var_name, raw_default_from_cmd if raw_default_from_cmd else "0")
    
    if prompt_for_initial_value:
        user_input = execute_applescript_dialog(f"Confirm or set start value for {var_name}:", str(initial_val_str))
        if user_input and user_input not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]: initial_val_str = user_input
        elif user_input == "USER_TIMEOUT_PROMPT": print(f"[INFO] Prompt for {var_name} timed out. Using: '{initial_val_str}'")
        elif user_input == "USER_CANCELLED_PROMPT": print(f"[INFO] User cancelled prompt for {var_name}. Using: '{initial_val_str}'")
        
    try: final_value = float(initial_val_str)
    except ValueError: final_value = 0.0; print(f"[ERROR] Invalid float '{initial_val_str}' for {var_name}. Defaulting to 0.0.")
    
    current_persistent_val = persistent_vars.get(var_name)
    if prompt_for_initial_value or current_persistent_val is None or str(current_persistent_val) != str(final_value):
        persistent_vars[var_name] = final_value; save_persistent_vars(persistent_vars)
    
    step = 1.0
    step_match_re = re.search(r"#([+-]?\d*\.?\d*)", cmd)
    if step_match_re:
        raw_step_val_from_cmd = step_match_re.group(1)
        if not (raw_step_val_from_cmd == "" or raw_step_val_from_cmd in ('+', '-')):
            try: step = float(raw_step_val_from_cmd)
            except ValueError: print(f"[ERROR] Failed to parse step '{raw_step_val_from_cmd}' from cmd. Using 1.0.")
    return {"name": var_name, "value": final_value, "step": step, "cmd": cmd, "key": key}

# === Configuration & Constants ===
POLL_INTERVAL = 0.5
LINE_SPACING = 4; DEFAULT_FONT_SIZE = 16; ARROW_FONT_SIZE = 24
LONG_PRESS_THRESHOLD = 1.0
FONT_PATH = "/System/Library/Fonts/SFNS.ttf"; BOLD_FONT_PATH = "/System/Library/Fonts/SFNSDisplay-Bold.otf"
BASE_COLORS = {'K':'#000000','R':'#FF0000','G':'#00FF00','O':'#FF9900','B':'#0066CC','Y':'#FFFF00','U':'#800080','S':'#00FFFF','E':'#808080','W':'#FFFFFF','L':'#FDF6E3','P':'#FFC0CB'}
NUMERIC_ADJUST_ACTIVE_BG = BASE_COLORS['Y']
NUMERIC_ADJUST_ACTIVE_FG = BASE_COLORS['K']

# === Helper Functions ===
def get_items():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT label,command,newwin FROM streamdeck ORDER BY id"); rows = cur.fetchall()
    conn.close(); return [(lbl or "", cmd or "", nw or "") for lbl, cmd, nw in rows]

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE': return False, False, BASE_COLORS['K'], DEFAULT_FONT_SIZE, 1.0
    new_win_flag = 'N' in f; device_flag = '@' in f # Renamed for clarity within this function
    size_match = re.search(r"(\d+)", f)
    font_size = int(size_match.group(1)) if size_match else DEFAULT_FONT_SIZE
    step = 1.0
    if '#' in f:
        step_match = re.search(r"#([+-]?\d*\.?\d*)", f)
        if step_match and step_match.group(1) not in ('', '+', '-'):
            try: step = float(step_match.group(1))
            except ValueError: pass
    base = next((c for c in BASE_COLORS if c in f and c not in ('N','D','@','#','V') and not c.isdigit()), 'K')
    col = BASE_COLORS.get(base, BASE_COLORS['K'])
    if 'D' in f and base != 'K':
        r_val,g_val,b_val = [int(col[i:i+2], 16)//2 for i in (1,3,5)]; col = f"#{r_val:02X}{g_val:02X}{b_val:02X}"
    return new_win_flag, device_flag, col, font_size, step

def text_color(bg_hex_str):
    if bg_hex_str.upper() == BASE_COLORS['R'].upper(): return 'white'
    if bg_hex_str.upper() == BASE_COLORS['G'].upper(): return 'black'
    if bg_hex_str.upper() == BASE_COLORS['Y'].upper(): return 'black'
    if bg_hex_str.upper() == BASE_COLORS['S'].upper(): return 'black'
    try:
        r, g, b = int(bg_hex_str[1:3], 16), int(bg_hex_str[3:5], 16), int(bg_hex_str[5:7], 16)
    except: return 'white'
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return 'black' if luminance > 140 else 'white'


def hex_to_aps_color_tuple_str(hex_color_str): # Returns string like "{65535,0,0}"
    try:
        hex_color_str = hex_color_str.lstrip('#')
        r = int(hex_color_str[0:2], 16) * 257
        g = int(hex_color_str[2:4], 16) * 257
        b = int(hex_color_str[4:6], 16) * 257
        return f"{{{r},{g},{b}}}"
    except:
        return "{0,0,0}" # Default black if conversion fails


def toggle_button_bg(bg_hex):
    try:
        r_val,g_val,b_val = [min(255, int(bg_hex[i:i+2],16)+60) for i in (1,3,5)]
        return f"#{r_val:02X}{g_val:02X}{b_val:02X}"
    except (ValueError, TypeError, IndexError): return BASE_COLORS['W']

def render_key(label, deck, bg_hex, fs, text_color_override=None, value_str=None):
    W, H = deck.key_image_format()['size']; img = PILHelper.create_image(deck); draw = ImageDraw.Draw(img)
    try: pr,pg,pb = [int(bg_hex[i:i+2],16) for i in (1,3,5)]
    except : pr=pg=pb=0 # Default to black if bg_hex is invalid
    draw.rectangle([(0,0),(W,H)], fill=(pr,pg,pb))
    try: fnt = ImageFont.truetype(FONT_PATH, fs)
    except IOError: fnt = ImageFont.truetype(BOLD_FONT_PATH, fs) if BOLD_FONT_PATH else ImageFont.load_default()
    
    try: mask_A = fnt.getmask('A'); cw = mask_A.size[0] if mask_A.size[0] > 0 else 10; lh = mask_A.size[1] if mask_A.size[1] > 0 else fs
    except AttributeError: cw = 10; lh = fs
        
    lines = textwrap.wrap(label, width=max(1, W//cw))
    if value_str is not None: lines.append(str(value_str))
    
    total_h = lh*len(lines) + LINE_SPACING*(len(lines)-1); y = (H - total_h)//2
    final_text_color_val = text_color_override if text_color_override else text_color(bg_hex)
    
    for ln_item in lines:
        try: line_width = fnt.getmask(ln_item).size[0]
        except AttributeError: line_width = len(ln_item) * cw
        x = (W - line_width)//2; draw.text((x,y), ln_item, font=fnt, fill=final_text_color_val); y += lh + LINE_SPACING
    return PILHelper.to_native_format(deck, img)

def run_cmd_in_terminal(main_command_to_run, # The N button's command, or regular command
                        button_label_for_new_window_title="", # Title for N window or @ window
                        button_bg_color_hex_for_new_window="", # BG for N window or @ window
                        is_activating_at_device=False,    # True if an @ button itself is pressed
                        at_device_own_command="",         # The command of the @ button (e.g. ssh)
                        active_at_device_label_to_target=None # Label of an already active @ device to send command to
                        ):

    main_cmd_escaped = applescript_escape_string(main_command_to_run)
    at_device_cmd_escaped = applescript_escape_string(at_device_own_command)
    osa_script = ""

    # Determine final payload and target type
    # TYPE 1: New, styled window (for N button, or for initial @ device activation)
    if button_label_for_new_window_title: # This implies N flag OR @ device activation
        window_custom_title = applescript_escape_string(button_label_for_new_window_title)
        bg_aps_str = hex_to_aps_color_tuple_str(button_bg_color_hex_for_new_window)
        
        text_col_name = text_color(button_bg_color_hex_for_new_window) # 'white' or 'black'
        text_aps_str = "{65535,65535,65535}" if text_col_name == 'white' else "{0,0,0}"

        script_payload_for_new_window = main_cmd_escaped
        if is_activating_at_device: # If it's an @ button itself, its command is the main payload
            script_payload_for_new_window = at_device_cmd_escaped
        elif at_device_own_command: # An N button, and an @ device is active, so prepend @ command
             script_payload_for_new_window = f"{at_device_cmd_escaped}\\n{main_cmd_escaped}" if main_cmd_escaped.strip() else at_device_cmd_escaped
        
        # If an @-device window with this title already exists, activate and run its command. Otherwise, create.
        osa_script = f'''
        tell application "Terminal"
            activate
            set target_window to missing value
            set window_found to false
            if "{window_custom_title}" is not "" then -- Only search if title is defined (for @ devices)
                repeat with w_obj in windows
                    if custom title of w_obj is "{window_custom_title}" then
                        set target_window to w_obj
                        set window_found to true
                        exit repeat
                    end if
                end repeat
            end if

            if window_found then
                -- Window exists, run the @-device's own command in it to re-establish connection if needed
                if "{at_device_cmd_escaped}" is not "" and "{main_cmd_escaped}" is "" then -- Only if it's an @ device activation
                     tell target_window to do script "{at_device_cmd_escaped}"
                else if "{script_payload_for_new_window}" is not "" then -- For N-flag button that might reuse an existing @-window (less likely but handles it)
                     tell target_window to do script "{script_payload_for_new_window}"
                end if
            else
                -- Window not found, create it
                if "{script_payload_for_new_window}" is not "" then
                    set new_terminal_entity to do script "{script_payload_for_new_window}"
                else
                    set new_terminal_entity to do script "" -- Create with empty command if needed
                end if
                delay 0.3
                if class of new_terminal_entity is tab then
                    set target_window to window of new_terminal_entity
                else if class of new_terminal_entity is window then
                    set target_window to new_terminal_entity
                else
                    set target_window to front window
                end if
            end if
            
            try
                tell target_window
                    set custom title to "{window_custom_title}"
                    set background color to {bg_aps_str}
                    set normal text color to {text_aps_str}
                    set cursor color to {text_aps_str}
                    set bold text color to {text_aps_str}
                    set index to 1 
                end tell
            on error msg
                log "Error styling window '{window_custom_title}': " & msg
            end try
        end tell'''

    # TYPE 2: Command for an existing active @ device window
    elif active_at_device_label_to_target:
        safe_target_title = applescript_escape_string(active_at_device_label_to_target)
        osa_script = f'''
        tell application "Terminal"
            activate
            set found_window to false
            repeat with w in windows
                if custom title of w is "{safe_target_title}" then
                    tell w to do script "{main_cmd_escaped}" 
                    set index of w to 1
                    set found_window to true
                    exit repeat
                end if
            end repeat
            if not found_window then
                log "Target window '{safe_target_title}' not found for command: {main_cmd_escaped}"
            end if
        end tell'''
        
    # TYPE 3: Default execution (no @ active, not N button)
    else:
        osa_script = f'''
        tell application "Terminal"
            activate
            if (count windows) is 0 then
                do script "{main_cmd_escaped}"
            else
                try
                    do script "{main_cmd_escaped}" in selected tab of front window
                on error
                    try 
                        do script "{main_cmd_escaped}" in front window
                    on error
                        do script "{main_cmd_escaped}"
                    end try
                end try
            end if
        end tell'''
    
    print(f"[DEBUG] Executing AppleScript for Terminal:\n{osa_script}")
    proc_term = subprocess.run(["osascript","-"],input=osa_script,text=True, capture_output=True)
    if proc_term.returncode != 0:
        print(f"[ERROR] AppleScript for Terminal execution failed. RC: {proc_term.returncode}, STDERR: {proc_term.stderr.strip()}, STDOUT: {proc_term.stdout.strip()}")


# === Stream Deck Runtime ===
if __name__ == "__main__":
    # ... (Initial setup as before) ...
    print("[INFO] Initializing Stream Deck Driver...")

    if DeviceManager is None or Image is None:
        print("[ERROR] Required libraries not available. Exiting.")
        sys.exit(1)
    persistent_vars = load_persistent_vars()
    items = []
    try:
        print("[INFO] Attempting to load items from database...")
        items = get_items()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            print("[INFO] 'streamdeck' table not found. Attempting to create/load database.")
            try:
                load_proc_result = subprocess.run([sys.executable, str(LOAD_SCRIPT), str(DB_PATH)], check=True, capture_output=True, text=True)
                print(f"[INFO] DB Load Script STDOUT: {load_proc_result.stdout}")
                if load_proc_result.stderr: print(f"[ERROR] DB Load Script STDERR: {load_proc_result.stderr}")
                items = get_items()
            except Exception as load_err: print(f"[ERROR] DB Load Script failed: {load_err}")
        else: raise
    if not items: print("[WARNING] No items loaded from database.")

    labels, cmds, flags, page_index = {}, {}, {}, 0
    numeric_mode, numeric_var, active_device_key = False, None, None
    press_times, toggle_keys = {}, set()
    long_press_numeric_active = False
    
    decks = DeviceManager().enumerate()
    if not decks: print("No Stream Deck found"); sys.exit(1)
    deck = decks[0]
    try: deck.open()
    except TransportError: print("Could not open Stream Deck"); sys.exit(1)
    deck.reset()

    cnt = deck.key_count(); up = cnt // 3; down = 2 * (cnt // 3)

    def build_page(idx):
        global labels, cmds, flags, items
        sticky_items = [it_item for it_item in items if parse_flags(it_item[2])[1]]
        normal_items = [it_item for it_item in items if not parse_flags(it_item[2])[1]]
        fixed_slots = {0, up, down}
        available_slots = [i for i in range(cnt) if i not in fixed_slots]
        num_available_slots = len(available_slots)
        num_sticky_to_place = min(len(sticky_items), num_available_slots)
        slots_for_normal_items_template = num_available_slots - num_sticky_to_place
        normCount_per_page = max(1, slots_for_normal_items_template) if slots_for_normal_items_template > 0 else 1
        total_pages = ceil(len(normal_items) / normCount_per_page) if normal_items and normCount_per_page > 0 else 1
        current_page_num = idx % total_pages
        new_labels, new_cmds_dict, new_flgs = {}, {}, {}
        current_slot_list_idx = 0
        for i_sticky, it_sticky in enumerate(sticky_items):
            if i_sticky < num_sticky_to_place:
                s_idx = available_slots[current_slot_list_idx]
                new_labels[s_idx], new_cmds_dict[s_idx], new_flgs[s_idx] = it_sticky
                current_slot_list_idx += 1
            else: break
        start_normal_item_idx_in_list = current_page_num * normCount_per_page
        for j_normal_on_page in range(normCount_per_page):
            if current_slot_list_idx < num_available_slots:
                s_idx = available_slots[current_slot_list_idx]
                pos_in_overall_normal_list = start_normal_item_idx_in_list + j_normal_on_page
                if pos_in_overall_normal_list < len(normal_items):
                    new_labels[s_idx], new_cmds_dict[s_idx], new_flgs[s_idx] = normal_items[pos_in_overall_normal_list]
                else:
                    new_labels[s_idx], new_cmds_dict[s_idx], new_flgs[s_idx] = "", "", ""
                current_slot_list_idx += 1
            else: break
        while current_slot_list_idx < num_available_slots:
            s_idx = available_slots[current_slot_list_idx]
            new_labels[s_idx], new_cmds_dict[s_idx], new_flgs[s_idx] = "", "", ""
            current_slot_list_idx += 1
        new_labels[0], new_cmds_dict[0], new_flgs[0] = "LOAD","","W"
        new_labels[up], new_cmds_dict[up], new_flgs[up] = "▲","","W"
        new_labels[down], new_cmds_dict[down], new_flgs[down] = "▼","","W"
        labels, cmds, flags = new_labels, new_cmds_dict, new_flgs
    build_page(page_index)

    def redraw():
        global labels, cmds, flags, numeric_mode, numeric_var, active_device_key, toggle_keys, persistent_vars, up, down, cnt, deck, long_press_numeric_active
        for i_key in range(cnt):
            f_str = flags.get(i_key, ""); nw_flag_rd, dev_flag_rd, bg_color_val_rd, fs_val_rd, _ = parse_flags(f_str)
            current_bg = bg_color_val_rd; key_text_color_override = None
            
            if numeric_mode and long_press_numeric_active and numeric_var and i_key == numeric_var.get('key') :
                 current_bg = NUMERIC_ADJUST_ACTIVE_BG
                 key_text_color_override = NUMERIC_ADJUST_ACTIVE_FG
            elif numeric_mode and long_press_numeric_active and i_key in (up, down):
                current_bg = BASE_COLORS['W']; key_text_color_override = "black"
            elif i_key == active_device_key:
                 current_bg = toggle_button_bg(bg_color_val_rd)
            elif dev_flag_rd and active_device_key != i_key :
                try:
                    r_dim, g_dim, b_dim = int(bg_color_val_rd[1:3],16)//2, int(bg_color_val_rd[3:5],16)//2, int(bg_color_val_rd[5:7],16)//2
                    current_bg = f"#{r_dim:02X}{g_dim:02X}{b_dim:02X}"
                except: pass
            
            current_value_to_display = None
            if numeric_mode and numeric_var and long_press_numeric_active:
                if i_key == numeric_var.get('key'):
                    var_val_disp = persistent_vars.get(numeric_var['name'])
                    if isinstance(var_val_disp, float) and var_val_disp.is_integer(): current_value_to_display = str(int(var_val_disp))
                    else: current_value_to_display = f"{var_val_disp:.1f}" if isinstance(var_val_disp, float) else str(var_val_disp)

                elif i_key == up: current_value_to_display = f"+{numeric_var.get('step',1.0):.1f}"
                elif i_key == down: current_value_to_display = f"-{numeric_var.get('step',1.0):.1f}"
            
            deck.set_key_image(i_key, render_key(labels.get(i_key,""), deck, current_bg, fs_val_rd, key_text_color_override, current_value_to_display))
    
    def callback(deck_param, key_index, state):
        global page_index, numeric_mode, numeric_var, active_device_key, labels, cmds, flags, items, toggle_keys, persistent_vars, press_times, long_press_numeric_active
        
        k_idx = key_index; s_state = state
        if s_state: press_times[k_idx] = time.time(); return
        
        long_press_event = (time.time() - press_times.get(k_idx,0)) >= LONG_PRESS_THRESHOLD
        press_times.pop(k_idx,None)
        
        current_cmd_str_original = cmds.get(k_idx,"")
        current_flag_str = flags.get(k_idx,"")
        # nw_flag_cb is True if 'N' is in flags
        # dev_flag_cb is True if '@' is in flags
        nw_flag_cb, dev_flag_cb, bg_color_val_cb, fs_val_cb, flag_step_val = parse_flags(current_flag_str)

        processed_cmd_str = current_cmd_str_original # This will be substituted with vars before execution
        for m_var_sub in VAR_PATTERN.finditer(processed_cmd_str):
            ph_sub, var_n_sub, var_df_sub = m_var_sub.group(0), m_var_sub.group(1), m_var_sub.group(2) or ""
            processed_cmd_str = processed_cmd_str.replace(ph_sub, str(persistent_vars.get(var_n_sub, var_df_sub)))

        needs_redraw_after_action = False

        # --- Action Prioritization ---
        # 1. LOAD Button
        if k_idx == 0 and not long_press_event:
            print("[DEBUG] Callback: LOAD key pressed.");
            try:
                load_proc = subprocess.run([sys.executable, str(LOAD_SCRIPT), str(DB_PATH)], check=True, capture_output=True, text=True)
                if load_proc.stdout: print(f"[INFO] LOAD_SCRIPT STDOUT:\n{load_proc.stdout}")
                if load_proc.stderr: print(f"[ERROR] LOAD_SCRIPT STDERR:\n{load_proc.stderr}")
                items[:] = get_items()
                persistent_vars.clear(); persistent_vars.update(load_persistent_vars())
                print("[INFO] Database reloaded.")
            except Exception as e_load: print(f"[ERROR] LOAD key operation failed: {e_load}")
            page_index=0; build_page(page_index);
            numeric_mode=False; numeric_var=None; long_press_numeric_active = False;
            active_device_key=None; toggle_keys.clear();
            redraw(); return

        # 2. Numeric Mode Operations (#, Up, Down)
        if '#' in current_flag_str:
            if not long_press_event: # SHORT PRESS on '#'
                print(f"[DEBUG] SHORT press on # button {k_idx}. Command: '{processed_cmd_str}'")
                if numeric_mode and long_press_numeric_active and numeric_var and numeric_var.get('key') == k_idx:
                    print(f"[DEBUG] Exiting numeric mode (LP active) by short press on its key {k_idx}.")
                    if numeric_var.get('key') in toggle_keys: toggle_keys.remove(numeric_var.get('key'))
                    numeric_mode=False; numeric_var=None; long_press_numeric_active = False
                    # Ensure active @ device (if any) remains visually toggled
                    if active_device_key is not None and parse_flags(flags.get(active_device_key, ""))[1]:
                        if active_device_key not in toggle_keys: toggle_keys.add(active_device_key)
                    redraw(); return
                else: # Execute command, routed to active @ device or default
                    target_title = labels.get(active_device_key) if active_device_key is not None else None
                    run_cmd_in_terminal(processed_cmd_str, active_at_device_label_to_target=target_title)
                    return
            else: # LONG PRESS on '#'
                print(f"[DEBUG] LONG press on # button {k_idx}. Entering numeric adjust.")
                parsed_var_info = handle_numeric_toggle_init(k_idx, current_cmd_str_original, persistent_vars, prompt_for_initial_value=True)
                if not parsed_var_info: redraw(); return
                step_for_prompt = flag_step_val
                user_val_str = execute_applescript_dialog(f"Enter step for {parsed_var_info['name']}:", str(step_for_prompt))
                user_confirmed_step = step_for_prompt
                if user_val_str and user_val_str not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                    try: user_confirmed_step = float(user_val_str)
                    except ValueError: print(f"[ERROR] Invalid step: '{user_val_str}'. Using {step_for_prompt}.")
                
                numeric_mode = True; long_press_numeric_active = True
                numeric_var = {"name": parsed_var_info['name'], "value": parsed_var_info['value'], "step": user_confirmed_step, "cmd": current_cmd_str_original, "key": k_idx}
                current_active_dev = active_device_key if active_device_key is not None and parse_flags(flags.get(active_device_key, ""))[1] else None
                toggle_keys.clear(); toggle_keys.add(k_idx)
                if current_active_dev is not None: toggle_keys.add(current_active_dev)
                redraw(); return

        if not long_press_event and numeric_mode and long_press_numeric_active and numeric_var and k_idx in (up, down):
            # ... (Numeric adjustment as before)
            step_val=numeric_var.get('step',1.0)
            try: current_val = float(persistent_vars.get(numeric_var['name'], 0.0))
            except ValueError: current_val = 0.0
            new_value = current_val + step_val if k_idx==up else current_val - step_val
            persistent_vars[numeric_var['name']]=new_value; save_persistent_vars(persistent_vars)
            numeric_var['value'] = new_value
            cmd_template_num_adj = numeric_var['cmd']
            cmd_to_run_num_adj = cmd_template_num_adj
            var_name_exact_numeric = numeric_var['name']
            specific_var_pattern_numeric = re.compile(r"\{\{" + re.escape(var_name_exact_numeric) + r"(:[^}]*)?\}\}")
            cmd_to_run_num_adj = specific_var_pattern_numeric.sub(str(new_value), cmd_to_run_num_adj)
            for m_sub in VAR_PATTERN.finditer(cmd_to_run_num_adj):
                if m_sub.group(1) != var_name_exact_numeric:
                    cmd_to_run_num_adj = cmd_to_run_num_adj.replace(m_sub.group(0), str(persistent_vars.get(m_sub.group(1), m_sub.group(2) or "")))
            print(f"[DEBUG] Numeric inc/dec. Key: {k_idx}, Var: {var_name_exact_numeric}, Val: {new_value}, Cmd: '{cmd_to_run_num_adj}'")
            target_terminal_title_num_adj = labels.get(active_device_key) if active_device_key is not None else None
            run_cmd_in_terminal(cmd_to_run_num_adj, active_at_device_label_to_target=target_terminal_title_num_adj)
            redraw(); return

        # 3. @ Device Button Press
        if dev_flag_cb and not long_press_event:
            print(f"[DEBUG] @ Device button {k_idx} ('{labels.get(k_idx)}') press.")
            lp_numeric_active_before = long_press_numeric_active
            if active_device_key == k_idx: # Toggle OFF
                active_device_key = None
                if k_idx in toggle_keys: toggle_keys.remove(k_idx)
                print(f"[DEBUG] Device {k_idx} ('{labels.get(k_idx)}') toggled OFF.")
            else: # Toggle ON
                if active_device_key is not None and active_device_key in toggle_keys: toggle_keys.remove(active_device_key)
                active_device_key = k_idx
                toggle_keys.add(k_idx)
                print(f"[DEBUG] Device {k_idx} ('{labels.get(k_idx)}') toggled ON. Executing its command: '{processed_cmd_str}'")
                
                run_cmd_in_terminal(main_command_to_run=processed_cmd_str,  # This is the @-button's own command
                                    button_label_for_new_window_title=labels.get(k_idx),  # It creates/targets its own title
                                    button_bg_color_hex_for_new_window=bg_color_val_cb,
                                    is_activating_at_device=True)  # Special flag for this case
            
            if lp_numeric_active_before:
                print("[DEBUG] Exiting numeric mode (LP) due to @ press.")
                if numeric_var and numeric_var.get('key') in toggle_keys: toggle_keys.remove(numeric_var.get('key'))
                numeric_mode = False; numeric_var = None; long_press_numeric_active = False
            redraw(); return

        # 4. Exit numeric mode if another key is pressed
        if not long_press_event and numeric_mode and long_press_numeric_active and numeric_var and k_idx not in (up, down, numeric_var.get('key')):
            print(f"[DEBUG] Exiting numeric mode (LP) due to press on other key {k_idx}.")
            if numeric_var.get('key') in toggle_keys: toggle_keys.remove(numeric_var.get('key'))
            numeric_mode=False; numeric_var=None; long_press_numeric_active = False;
            needs_redraw_after_action = True # Will fall through, redraw if this was the only action that changed state

        # 5. Long Press 'V' or Plain Key Edit
        if long_press_event:
            if 'V' in current_flag_str:
                match_v = VAR_PATTERN.search(current_cmd_str_original)
                if match_v:
                    ph_v,var_n_v,var_df_v = match_v.group(0),match_v.group(1),match_v.group(2) or ""
                    prompt_val_str_v = str(persistent_vars.get(var_n_v,var_df_v))
                    user_input_v = execute_applescript_dialog(f"Enter value for {var_n_v}:", prompt_val_str_v)
                    if user_input_v and user_input_v not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                        persistent_vars[var_n_v]=user_input_v; save_persistent_vars(persistent_vars)
                        print(f"[DEBUG] Updated persistent var '{var_n_v}' to '{user_input_v}' via LP 'V'.")
                    redraw(); return # Redraw might be needed if var appears on key (not current)
                return
            elif not ('#' in current_flag_str or '@' in current_flag_str) and current_cmd_str_original: # Plain key edit
                label_for_prompt_edit = labels.get(k_idx, "Button " + str(k_idx))
                user_input_edit = execute_applescript_dialog(f"Edit command for {label_for_prompt_edit}:", current_cmd_str_original)
                if user_input_edit and user_input_edit not in ["USER_CANCELLED_PROMPT", "USER_TIMEOUT_PROMPT"]:
                    if user_input_edit != current_cmd_str_original:
                        cmds[k_idx] = user_input_edit
                        print(f"[INFO] Command for key {k_idx} ('{label_for_prompt_edit}') updated in memory to: '{user_input_edit}'")
                        print(f"[TODO] Implement saving updated command for key {k_idx} to DB.")
                return
            else: # Other unhandled long presses
                if needs_redraw_after_action: redraw()
                return

        # 6. Page Navigation (if not in LP numeric mode and not other caught actions)
        if not long_press_event and not (numeric_mode and long_press_numeric_active):
             if k_idx == up: page_index -=1; build_page(page_index); redraw(); return
             if k_idx == down: page_index +=1; build_page(page_index); redraw(); return

        # 7. Default Execution (Regular button, or N button, or # short press that fell through)
        if not current_cmd_str_original: # No command to run
            print(f"[DEBUG] Callback: No command for key {k_idx}. Doing nothing.");
            if needs_redraw_after_action: redraw() # If numeric mode exited to a blank key
            return

        print(f"[DEBUG] Final Execution Path for key {k_idx}. CMD: '{processed_cmd_str}'")
        
        if nw_flag_cb:
            print(f"[DEBUG] N-Flag button {k_idx} routing.")
            prepend_cmd = ""
            if active_device_key is not None:
                active_dev_cmd_orig = cmds.get(active_device_key, "")
                prepend_cmd = active_dev_cmd_orig
                for m_dev_sub in VAR_PATTERN.finditer(prepend_cmd):
                    ph_s, vn_s, vd_s = m_dev_sub.group(0), m_dev_sub.group(1), m_dev_sub.group(2) or ""
                    prepend_cmd = prepend_cmd.replace(ph_s, str(persistent_vars.get(vn_s, vd_s)))
                print(f"[DEBUG] N-Flag will prepend active @ device cmd: {prepend_cmd}")

            run_cmd_in_terminal(
                main_command_to_run=processed_cmd_str,
                button_label_for_new_window_title=labels.get(k_idx, "New Window"),
                button_bg_color_hex_for_new_window=bg_color_val_cb,
                at_device_own_command=prepend_cmd
            )
        elif active_device_key is not None:
            target_title = labels.get(active_device_key)
            print(f"[DEBUG] Regular cmd, targeting active @ device: {target_title}")
            run_cmd_in_terminal(
                main_command_to_run=processed_cmd_str,
                active_at_device_label_to_target=target_title
            )
        else:
            run_cmd_in_terminal(main_command_to_run=processed_cmd_str)
        
        if needs_redraw_after_action: redraw() # If numeric mode was exited just before this.

    deck.set_key_callback(callback)
    redraw()
    print("Stream Deck initialized. Listening for key presses...")
    try:
        while True: time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt: print("\nExiting Stream Deck driver...")
    finally:
        print("Saving persistent variables before exit...")
        save_persistent_vars(persistent_vars)
        print("Resetting and closing Stream Deck.")
        deck.reset(); deck.close()
        print("Exited.")

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

# === Variable Pattern (Permissive) ===
VAR_PATTERN = re.compile(r"\{\{([^:}]+)(:([^}]*))?\}\}")
SSH_USER_HOST_CMD_PATTERN = re.compile(r"^(ssh(?:\s+-[a-zA-Z0-9]+(?:\s+\S+)?)*)\s+(\S+)@(\S+)((?:\s+.*)?)$", re.IGNORECASE)


# === Monitoring State Dictionaries ===
monitor_states = {}
monitor_threads = {}
key_to_global_item_idx_map = {}
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
BASE_COLORS = {'K':'#000000','R':'#FF0000','G':'#00FF00','O':'#FF9900','B':'#0066CC','Y':'#FFFF00','U':'#800080','S':'#00FFFF','E':'#808080','W':'#FFFFFF','L':'#FDF6E3','P':'#FFC0CB'}
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

# --- ALL FUNCTION DEFINITIONS (GLOBAL SCOPE) ---

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

def initialize_session_vars_from_items(items_list, session_vars_dict):
    session_vars_dict.clear()
    for item_dict in items_list:
        cmd = item_dict.get('command', '')
        if not cmd: continue
        for match in VAR_PATTERN.finditer(cmd):
            var_name, default_value = match.group(1).strip(), match.group(3) if match.group(3) is not None else ""
            if var_name not in session_vars_dict: session_vars_dict[var_name] = default_value

def resolve_command_string(command_str_template, session_vars_dict):
    resolved_cmd = command_str_template
    for var_name, var_value in session_vars_dict.items():
        resolved_cmd = re.compile(r"(\{\{)(" + re.escape(var_name) + r")(:[^}]*)?(\}\})").sub(str(var_value), resolved_cmd)
    for match in list(VAR_PATTERN.finditer(resolved_cmd)):
        full_placeholder, var_name, default_in_cmd = match.group(0), match.group(1).strip(), match.group(3) if match.group(3) is not None else ""
        if var_name not in session_vars_dict: session_vars_dict[var_name] = default_in_cmd
        resolved_cmd = resolved_cmd.replace(full_placeholder, str(session_vars_dict.get(var_name, default_in_cmd)))
    return resolved_cmd.replace('\\"', '"')

def get_items():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, label, command, flags, monitor_keyword FROM streamdeck ORDER BY id")
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        print(f"[ERROR] Database read failed: {e}", file=sys.stderr)
        return []

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE': return False, False, False, BASE_COLORS['K'], DEFAULT_FONT_SIZE, False, False
    new_win, device, sticky = 'N' in f, '@' in f, 'T' in f or '@' in f
    font_size = int(m.group(1)) if (m := re.search(r"(\d+)", f)) else DEFAULT_FONT_SIZE
    force_local_execution, is_mobile_ssh_flag = 'K' in f, 'M' in f
    base_color_char_for_display = 'K'
    non_k_color_found = False
    color_priority_chars = [c for c in BASE_COLORS.keys() if c != 'K']
    for char_code in f:
        if char_code in color_priority_chars: base_color_char_for_display, non_k_color_found = char_code, True; break
    if not non_k_color_found and force_local_execution: base_color_char_for_display = 'K'
    col = BASE_COLORS.get(base_color_char_for_display, BASE_COLORS['K'])
    if 'D' in f and base_color_char_for_display != 'K':
        try: col = f"#{''.join(f'{int(col[i:i+2],16)//2:02X}' for i in (1,3,5))}"
        except: pass
    return new_win, device, sticky, col, font_size, force_local_execution, is_mobile_ssh_flag

def text_color(bg_hex):
    if not bg_hex or len(bg_hex) < 6: return 'white'
    bg_upper = bg_hex.upper()
    if bg_upper in [BASE_COLORS[c] for c in "YSWLP"]: return 'black'
    if bg_upper in [BASE_COLORS[c] for c in "KRBUE"]: return 'white'
    try: r,g,b = (int(bg_hex[i:i+2],16) for i in (1,3,5)); lum = 0.299*r+0.587*g+0.114*b; return 'black' if lum > 128 else 'white'
    except: return 'white'

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
    try: return BASE_COLORS['K'] if bg_hex.upper()==BASE_COLORS['K'] else f"#{''.join(f'{int(bg_hex[i:i+2],16)//2:02X}' for i in (1,3,5))}"
    except: return bg_hex

def _transform_ssh_user_for_mobile(command_text):
    if not command_text or not command_text.lower().strip().startswith("ssh "): return command_text
    match = SSH_USER_HOST_CMD_PATTERN.match(command_text)
    if match:
        ssh_options_part, host_part, remote_cmd_part = match.group(1), match.group(3), match.group(4) or ""
        return f"{ssh_options_part} mobile@{host_part}{remote_cmd_part}"
    return command_text

def render_key(label_text, deck_ref, bg_hex_val, font_size_val, txt_override_color=None, status_text_val=None, vars_text_val=None, flash_active=False, extra_text=None):
    W,H = deck_ref.key_image_format()['size']; img = PILHelper.create_image(deck_ref); draw = ImageDraw.Draw(img)
    try: pil_bg = tuple(int(bg_hex_val.lstrip('#')[i:i+2],16) for i in (0,2,4))
    except: pil_bg = (0,0,0)
    draw.rectangle([(0,0),(W,H)], fill=pil_bg)
    try:
        font_status, font_label, font_vars = ImageFont.truetype(FONT_PATH, 10), ImageFont.truetype(FONT_PATH, font_size_val), ImageFont.truetype(FONT_PATH, 10)
        font_extra = ImageFont.truetype(FONT_PATH, 14)
    except IOError: font_status, font_label, font_vars, font_extra = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    final_text_color = txt_override_color or text_color(bg_hex_val)
    status_text_height_reserved = 0
    actual_status_text_to_draw = ""
    if status_text_val:
        s_bbox_temp = font_status.getbbox(status_text_val, anchor="lt") if hasattr(font_status, 'getbbox') else (0,0,*draw.textsize(status_text_val,font=font_status))
        status_text_height_reserved = (s_bbox_temp[3] - s_bbox_temp[1]) + LINE_SPACING
        if not (flash_active and status_text_val.upper() == "CONNECTED"):
            actual_status_text_to_draw = status_text_val
    if actual_status_text_to_draw:
        s_bbox = font_status.getbbox(actual_status_text_to_draw,anchor="lt") if hasattr(font_status,'getbbox') else (0,0,*draw.textsize(actual_status_text_to_draw,font=font_status))
        draw.text(((W - (s_bbox[2] - s_bbox[0])) / 2, 3), actual_status_text_to_draw, font=font_status, fill=final_text_color, anchor="lt" if hasattr(draw, 'textbbox') else None)
    label_y_start = 3 + status_text_height_reserved
    current_label_y = label_y_start
    if label_text:
        wrap_width = max(3, min(W // (font_size_val // 1.8 if font_size_val > 10 else 8), 6 if font_size_val >= ARROW_FONT_SIZE else (9 if font_size_val >= DEFAULT_FONT_SIZE else 12)))
        lines = textwrap.wrap(label_text, width=int(wrap_width), max_lines=3, placeholder="…")
        lh_bbox = font_label.getbbox("Tg",anchor="lt") if hasattr(font_label,'getbbox') else (0,0,*font_label.getsize("Tg"))
        line_height_label = lh_bbox[3] - lh_bbox[1]
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
        var_line_height_render = font_vars.getsize("M")[1] if hasattr(font_vars, 'getsize') else 10
        num_var_lines_to_draw_final = min(len(var_lines_wrapped_final), 2)
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

def run_cmd_in_terminal(main_cmd, is_at_act=False, at_has_n=False, btn_style_cfg=None, act_at_lbl=None, is_n_staged=False, ssh_staged="", n_staged="", prepend="", force_new_win_at=False, force_local_execution=False):
    eff_cmd = f"{prepend}\n{main_cmd.strip()}" if prepend and main_cmd.strip() else (prepend or main_cmd.strip())
    eff_cmd = eff_cmd.replace('“','"').replace('”','"')
    esc_cmd = applescript_escape_string(eff_cmd)
    as_script, script_vars = "", {}
    tpl_map = {"n_staged":"terminal_n_for_at_staged_keystroke.applescript", "at_n":"terminal_activate_new_styled_at_n.applescript", "at_only":"terminal_activate_found_at_only.applescript", "n_alone":"terminal_activate_standalone_n.applescript", "to_active_at":"terminal_command_to_active_at_device.applescript", "default":"terminal_do_script_default.applescript", "force_local_new_window": "terminal_force_new_window_and_do_script.applescript"}
    if force_local_execution:
        if eff_cmd: script_vars['final_script_payload_for_do_script'] = esc_cmd; as_script = load_applescript_template(tpl_map["force_local_new_window"], **script_vars)
        else: return
    else:
        is_cmd_to_act_at = act_at_lbl and not is_at_act and not (btn_style_cfg and btn_style_cfg.get('is_standalone_n_button',False)) and not is_n_staged
        if not eff_cmd and not is_at_act and not is_cmd_to_act_at and not (is_n_staged and ssh_staged): return
        if is_n_staged:
            if not btn_style_cfg or not ssh_staged: print(f"[ERR] N-Staged missing info"); return
            script_vars.update({'window_custom_title': applescript_escape_string(btn_style_cfg.get('lbl','N-Staged Window')), 'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', BASE_COLORS['K'])), 'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name','white')=='white' else "{0,0,0}", 'ssh_command_to_keystroke': applescript_escape_string(ssh_staged), 'actual_n_command_to_keystroke': applescript_escape_string(n_staged)})
            as_script = load_applescript_template(tpl_map["n_staged"], **script_vars)
        elif is_at_act:
            if not btn_style_cfg or 'lbl' not in btn_style_cfg:
                if eff_cmd: script_vars['final_script_payload_for_do_script']=esc_cmd; as_script=load_applescript_template(tpl_map["default"],**script_vars)
                else: return
            else:
                dev_lbl = btn_style_cfg['lbl']; script_vars.update({'escaped_device_label': applescript_escape_string(dev_lbl), 'aps_bg_color': hex_to_aps_color_values_str(btn_style_cfg.get('bg_hex', BASE_COLORS['K'])), 'aps_text_color': "{65535,65535,65535}" if btn_style_cfg.get('text_color_name','white')=='white' else "{0,0,0}"})
                if at_has_n: script_vars['final_script_payload']=esc_cmd; as_script=load_applescript_template(tpl_map["at_n"],**script_vars)
                else: script_vars['final_script_payload_for_do_script']=esc_cmd; script_vars['force_new_window']="true" if force_new_win_at else "false"; as_script=load_applescript_template(tpl_map["at_only"],**script_vars)
        elif btn_style_cfg and btn_style_cfg.get('is_standalone_n_button',False):
            cfg = btn_style_cfg; script_vars.update({'window_custom_title': applescript_escape_string(cfg.get('lbl', 'N Window')), 'aps_bg_color': hex_to_aps_color_values_str(cfg.get('bg_hex', BASE_COLORS['K'])), 'aps_text_color': "{65535,65535,65535}" if cfg.get('text_color_name','white')=='white' else "{0,0,0}", 'final_script_payload_for_do_script': esc_cmd}); as_script = load_applescript_template(tpl_map["n_alone"], **script_vars)
        elif is_cmd_to_act_at:
            script_vars.update({'safe_target_title': applescript_escape_string(act_at_lbl), 'final_script_payload_for_do_script': esc_cmd, 'main_command_raw_for_emptiness_check': esc_cmd, 'command_to_type_literally_content': esc_cmd});
            as_script = load_applescript_template(tpl_map["to_active_at"],**script_vars)
        elif eff_cmd: script_vars['final_script_payload_for_do_script']=esc_cmd; as_script=load_applescript_template(tpl_map["default"],**script_vars)
    if as_script:
        try:
            proc = subprocess.run(["osascript","-"],input=as_script,text=True,capture_output=True,check=False, timeout=15)
            stderr_lower = proc.stderr.lower().strip() if proc.stderr else ""
            if proc.returncode != 0 and "(-128)" not in stderr_lower and "(-1712)" not in stderr_lower:
                print(f"[ERROR] AppleScript execution failed (RC:{proc.returncode}).", file=sys.stderr); print(f"  AS STDERR: {proc.stderr.strip()}", file=sys.stderr)
        except subprocess.TimeoutExpired: print(f"[ERROR] osascript call timed out for command: {main_cmd[:50]}...", file=sys.stderr)
        except Exception as e_as: print(f"[FATAL] Error running osascript: {e_as}", file=sys.stderr)

def monitor_ssh(global_idx, ssh_cmd_base, generation_id):
    chk_cmd = f"{ssh_cmd_base} exit"
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        if monitor_generations.get(global_idx) != generation_id: break
        new_state = 'BROKEN'
        try:
            res = subprocess.run(shlex.split(chk_cmd) if not any(c in chk_cmd for c in "|;&><") else chk_cmd, shell=any(c in chk_cmd for c in "|;&><"), capture_output=True, text=True, timeout=8)
            if res.returncode == 0: new_state = 'connected'
        except: pass
        if monitor_generations.get(global_idx) == generation_id:
            if monitor_states.get(global_idx) != new_state: monitor_states[global_idx] = new_state
        else: break
        sleep_duration = 3 + (global_idx % 5) * 0.1
        for _ in range(int(sleep_duration / 0.1)):
            if monitor_generations.get(global_idx) != generation_id: break
            time.sleep(0.1)
        if monitor_generations.get(global_idx) != generation_id: break

def monitor_remote_process(global_idx, ssh_base_cmd, unique_grep_tag, generation_id):
    time.sleep(2.0)
    if monitor_generations.get(global_idx) != generation_id: return
    quoted_tag = shlex.quote(unique_grep_tag)
    grep_cmd_remote = f"ps auxww | grep -F -- {quoted_tag} | grep -v -F -- 'grep -F -- {quoted_tag}'"
    full_ssh_cmd_str = f"{ssh_base_cmd} \"{grep_cmd_remote}\""
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        if monitor_generations.get(global_idx) != generation_id: break
        new_proc_state = 'PROCESS_BROKEN'
        try:
            result = subprocess.run(full_ssh_cmd_str, shell=True, capture_output=True, text=True, timeout=8)
            if result.returncode == 0 and result.stdout.strip(): new_proc_state = 'PROCESS_RUNNING'
            elif result.returncode == 1: new_proc_state = 'PROCESS_BROKEN'
            else: new_proc_state = 'PROCESS_ERROR'
        except: new_proc_state = 'PROCESS_ERROR'
        if monitor_generations.get(global_idx) == generation_id:
            if monitor_states.get(global_idx) != new_proc_state: monitor_states[global_idx] = new_proc_state
        else: break
        sleep_duration = 3 + (global_idx % 7) * 0.1
        for _ in range(int(sleep_duration / 0.1)):
            if monitor_generations.get(global_idx) != generation_id: break
            time.sleep(0.1)
        if monitor_generations.get(global_idx) != generation_id: break

# --- Database Interaction Functions for API ---
def db_update_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE streamdeck SET label = ?, command = ?, flags = ?, monitor_keyword = ? WHERE id = ?", (button_data.get('label',''), button_data.get('command',''), button_data.get('flags',''), button_data.get('monitor_keyword', ''), button_data['id']))
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"[ERROR] DB Update failed for ID {button_data.get('id')}: {e}", file=sys.stderr)
        return False

def db_add_button(button_data):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO streamdeck (label, command, flags, monitor_keyword) VALUES (?, ?, ?, ?)", (button_data.get('label','(No Label)'), button_data.get('command',''), button_data.get('flags',''), button_data.get('monitor_keyword', '')))
            conn.commit()
            return cur.lastrowid
    except sqlite3.Error as e:
        print(f"[ERROR] DB Insert failed: {e}", file=sys.stderr)
        return None

def db_delete_button(button_id):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM streamdeck WHERE id = ?", (button_id,))
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.Error as e:
        print(f"[ERROR] DB Delete failed for ID {button_id}: {e}", file=sys.stderr)
        return False

# --- Flask API Server ---
api_app = Flask(__name__)
CORS(api_app, resources={r"/api/*": {"origins": f"http://localhost:{REACT_APP_DEV_PORT}"}})

@api_app.route('/api/buttons', methods=['GET'])
def get_all_buttons_api():
    global items, current_session_vars
    return jsonify({"buttons": items, "variables": current_session_vars})

@api_app.route('/api/buttons/<int:button_id>', methods=['PUT'])
def update_button_config_api(button_id):
    global items, page_index, current_session_vars
    data = request.json
    if not data: return jsonify({"error": "No data provided"}), 400
    updated_data = {"id": button_id, "label": data.get("label", ""), "command": data.get("command", ""), "flags": data.get("flags", ""), "monitor_keyword": data.get("monitor_keyword", "")}
    if not db_update_button(updated_data):
        return jsonify({"error": "Failed to update database"}), 500
    item_index = next((i for i, item in enumerate(items) if item['id'] == button_id), None)
    if item_index is not None:
        items[item_index] = updated_data
        initialize_session_vars_from_items(items, current_session_vars)
        build_page(page_index)
        redraw()
    return jsonify({"message": "Button updated", "button": updated_data})

@api_app.route('/api/buttons', methods=['POST'])
def add_new_button_api():
    global items, page_index, current_session_vars
    data = request.json
    if not data or not data.get("label","").strip(): return jsonify({"error": "Label is required"}), 400
    new_id = db_add_button(data)
    if new_id is None: return jsonify({"error": "Failed to add to database"}), 500
    new_button_with_id = {**data, "id": new_id}
    items.append(new_button_with_id)
    initialize_session_vars_from_items(items, current_session_vars)
    build_page(page_index)
    redraw()
    return jsonify({"message": "Button added", "button": new_button_with_id}), 201

@api_app.route('/api/buttons/<int:button_id>', methods=['DELETE'])
def delete_button_config_api(button_id):
    global items, page_index, current_session_vars
    item_index = next((i for i, item in enumerate(items) if item['id'] == button_id), None)
    if item_index is None: return jsonify({"error": "Button not found"}), 404
    if not db_delete_button(button_id): return jsonify({"error": "Failed to delete from database"}), 500
    del items[item_index]
    initialize_session_vars_from_items(items, current_session_vars)
    build_page(page_index)
    redraw()
    return jsonify({"message": "Button deleted"})

def run_flask_app_thread():
    print(f"[INFO] Flask API server starting on http://localhost:{CONFIG_SERVER_PORT}")
    try: api_app.run(host='127.0.0.1', port=CONFIG_SERVER_PORT, debug=False, use_reloader=False)
    except Exception as e: print(f"[FATAL] Flask server failed to start: {e}", file=sys.stderr)


# --- Main Application Logic Functions ---
def build_page(idx_param):
    global labels, cmds, flags, items, page_index, key_to_global_item_idx_map, cnt, load_key_idx, up_key_idx, down_key_idx
    key_to_global_item_idx_map.clear()
    if not items: idx_param = 0
    indexed_items = [(i, item, parse_flags(item['flags'])) for i, item in enumerate(items)]
    sticky = [p for p in indexed_items if p[2][2]]
    normal = [p for p in indexed_items if not p[2][2]]
    fixed = {load_key_idx, up_key_idx, down_key_idx}
    avail_slots = [s for s in range(cnt) if s not in fixed]
    new_lbl, new_cmd, new_flg = {}, {}, {}
    s_idx = 0
    for orig_i, item_data, _ in sticky:
        if s_idx < len(avail_slots):
            key = avail_slots[s_idx]
            new_lbl[key], new_cmd[key], new_flg[key] = item_data['label'], item_data['command'], item_data['flags']
            key_to_global_item_idx_map[key] = orig_i; s_idx+=1
        else: break
    norm_slots = avail_slots[s_idx:]
    num_norm_slots = len(norm_slots)
    tot_norm_pg = ceil(len(normal)/num_norm_slots) if normal and num_norm_slots>0 else 1
    page_index = idx_param % tot_norm_pg if tot_norm_pg > 0 else 0
    start_norm_idx = page_index * num_norm_slots
    for i_slot, key in enumerate(norm_slots):
        if start_norm_idx + i_slot < len(normal):
            orig_i, item_data, _ = normal[start_norm_idx + i_slot]
            new_lbl[key],new_cmd[key],new_flg[key] = item_data['label'],item_data['command'],item_data['flags']
            key_to_global_item_idx_map[key] = orig_i
        else: new_lbl[key],new_cmd[key],new_flg[key] = "","",""
    for k,l,c,f in [(load_key_idx,"LOAD","","W"),(up_key_idx,"▲","","W"),(down_key_idx,"▼","","W")]:
        if k is not None: new_lbl[k],new_cmd[k],new_flg[k]=l,c,f
    labels,cmds,flags = new_lbl,new_cmd,new_flg

def redraw():
    global labels, cmds, flags, numeric_mode, numeric_var, active_device_key, current_session_vars, up_key_idx, down_key_idx, load_key_idx, cnt, deck, long_press_numeric_active, flash_state, items, key_to_global_item_idx_map, monitor_states
    if not deck: return
    for i_key in range(cnt):
        f_str_pg, cmd_str_pg, lbl_str_pg = flags.get(i_key,""), cmds.get(i_key,""), labels.get(i_key,"")
        _, dev_flag_pg, _, bg_pg, fs_pg, _, _ = parse_flags(f_str_pg)
        lbl_render, status_render, vars_render, extra_txt = lbl_str_pg, None, None, None
        bg_render, txt_override_render, flash_this_key_active = bg_pg, None, False
        styled = False; fs_render = fs_pg
        if i_key == down_key_idx: extra_txt = "CONFIG"
        g_idx = key_to_global_item_idx_map.get(i_key)
        if g_idx is not None and g_idx < len(items):
            item_dict = items[g_idx]
            item_lbl, item_cmd_db, item_flags_str = item_dict.get('label',''), item_dict.get('command',''), item_dict.get('flags','')
            _,item_is_at,_,item_orig_bg,item_orig_fs_from_db, _, _ = parse_flags(item_flags_str)
            fs_render = item_orig_fs_from_db
            mon_state = monitor_states.get(g_idx)
            if item_is_at and '!' in item_flags_str:
                styled=True; lbl_render=item_lbl; bg_render = dim_color(item_orig_bg) if active_device_key!=i_key else toggle_button_bg(item_orig_bg)
                if mon_state=='connected':
                    status_render="CONNECTED"
                    if not (numeric_mode and long_press_numeric_active): flash_this_key_active = flash_state
                elif mon_state=='BROKEN':
                    status_render="BROKEN"
                    if flash_state: bg_render = BASE_COLORS['R']
                elif mon_state == 'initializing': status_render = "INIT..."
                elif mon_state: status_render=mon_state.upper()[:10];
                if mon_state in ['error_config','error'] or ('config' in (mon_state or "")): bg_render = BASE_COLORS['R']
                txt_override_render = text_color(bg_render)
                vars_render = " ".join(str(current_session_vars.get(m.group(1).strip())) for m in VAR_PATTERN.finditer(item_cmd_db) if current_session_vars.get(m.group(1).strip()) is not None) or None
            elif not item_is_at and '!' in item_flags_str:
                proc_state = monitor_states.get(g_idx)
                if proc_state:
                    styled=True; lbl_render=item_lbl; bg_render=item_orig_bg
                    if proc_state == "PROCESS_INIT": status_render="INIT..."; bg_render=BASE_COLORS['O']
                    elif proc_state == "PROCESS_RUNNING": status_render="RUNNING"; bg_render=BASE_COLORS['G']
                    elif proc_state == "PROCESS_BROKEN": status_render="BROKEN"; bg_render=BASE_COLORS['R']
                    elif proc_state == "PROCESS_NO_AT": status_render="NO @DEV"; bg_render=BASE_COLORS['E']
                    elif proc_state == "PROCESS_NO_KW": status_render="NO TAG"; bg_render=BASE_COLORS['E']
                    elif proc_state == "PROCESS_ERROR": status_render="P_ERROR"; bg_render=BASE_COLORS['R']
                    else: status_render = proc_state[:10]
                    txt_override_render = text_color(bg_render)
            elif 'V' in item_flags_str:
                styled = True
                lbl_render = item_lbl
                bg_render = item_orig_bg
                vals = [str(current_session_vars.get(m.group(1).strip())) for m in VAR_PATTERN.finditer(item_cmd_db) if current_session_vars.get(m.group(1).strip()) is not None]
                if vals: vars_render = " ".join(vals)
        if not styled and numeric_mode and long_press_numeric_active and numeric_var:
            num_key = numeric_var.get('key')
            if i_key==num_key or i_key==up_key_idx or i_key==down_key_idx:
                styled=True; lbl_render=lbl_str_pg; _,_,_,num_orig_bg,_,_,_ = parse_flags(flags.get(num_key,"")); bright_num_bg = toggle_button_bg(num_orig_bg)
                bg_render = bright_num_bg if flash_state else (num_orig_bg if i_key==num_key else dim_color(bright_num_bg)); txt_override_render = text_color(bg_render)
                if i_key==num_key:
                    vars_val = current_session_vars.get(numeric_var['name'])
                    vars_render = str(vars_val) if vars_val is not None else ""
                elif i_key in [up_key_idx, down_key_idx]:
                    step = numeric_var.get('step', 1.0)
                    op = "+" if i_key == up_key_idx else "-"
                    step_text = f"{op}{step}"
                    # --- FIX: Move step text to the top for the down arrow to avoid overlap with "CONFIG" ---
                    if i_key == down_key_idx:
                        status_render = step_text
                    else:
                        vars_render = step_text
        if not styled and dev_flag_pg:
            styled=True; lbl_render=lbl_str_pg; bg_render = toggle_button_bg(bg_pg) if active_device_key==i_key else dim_color(bg_pg); txt_override_render = text_color(bg_render)
            vars_render = " ".join(str(current_session_vars.get(m.group(1).strip())) for m in VAR_PATTERN.finditer(cmd_str_pg) if current_session_vars.get(m.group(1).strip()) is not None) or None
        final_fs_to_use = ARROW_FONT_SIZE if i_key in [up_key_idx,down_key_idx] else fs_render
        try: deck.set_key_image(i_key, render_key(lbl_render,deck,bg_render,final_fs_to_use,txt_override_render,status_render,vars_render,flash_active=flash_this_key_active,extra_text=extra_txt))
        except Exception as e_render: print(f"[ERROR] Render key {i_key} failed: {e_render}", file=sys.stderr)

def start_monitoring():
    global items, monitor_threads, monitor_states, current_session_vars, monitor_generations
    for g_idx in list(monitor_threads.keys()):
        monitor_generations[g_idx] = None
        if g_idx in monitor_threads: del monitor_threads[g_idx]
    for g_idx, item_data in enumerate(items):
        item_cmd_mon, item_flags_mon = item_data.get('command',''), item_data.get('flags','')
        _, _, _, _, _, _, item_is_mobile_mon = parse_flags(item_flags_mon)
        if '!' in item_flags_mon and '@' in item_flags_mon:
            monitor_states.pop(g_idx, None); monitor_states[g_idx] = 'initializing'
            current_gen_id = time.time(); monitor_generations[g_idx] = current_gen_id
            resolved_cmd_mon = resolve_command_string(item_cmd_mon, current_session_vars)
            if item_is_mobile_mon and resolved_cmd_mon.lower().strip().startswith("ssh "): resolved_cmd_mon = _transform_ssh_user_for_mobile(resolved_cmd_mon)
            ssh_match_mon = re.match(r"^(ssh\s+[^ ]+)", resolved_cmd_mon)
            if ssh_match_mon:
                thread = threading.Thread(target=monitor_ssh, args=(g_idx, ssh_match_mon.group(1), current_gen_id), daemon=True)
                monitor_threads[g_idx] = thread; thread.start()
            else: monitor_states[g_idx] = 'error_config'
        elif '!' in item_flags_mon and not '@' in item_flags_mon:
             monitor_states.pop(g_idx, None)
    print("[INFO] Monitoring initialized.")

def load_data_and_reinit_vars():
    global items, current_session_vars, page_index, numeric_mode, numeric_var, active_device_key, toggle_keys, long_press_numeric_active, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, monitor_generations
    print("[INFO] Rebuilding database from Numbers & reloading configs...")
    try:
        py_exec = sys.executable; load_script_path = APP_DIR/"streamdeck_db.py"
        if not load_script_path.exists(): load_script_path = Path("streamdeck_db.py")
        subprocess.run([py_exec,str(load_script_path),str(DB_PATH)],check=True,capture_output=True,text=True)
    except Exception as e:
        err_out = getattr(e, 'stderr', '') or getattr(e, 'stdout', '') or str(e)
        print(f"[FATAL] DB Load Script failed: {err_out}. Exiting.", file=sys.stderr)
        if deck: deck.close()
        sys.exit(1)
    items[:] = get_items()
    initialize_session_vars_from_items(items, current_session_vars)
    page_index=0; numeric_mode=False; numeric_var=None; long_press_numeric_active=False
    active_device_key=None; toggle_keys.clear(); at_devices_to_reinit_cmd.clear()
    flash_state=False; key_to_global_item_idx_map.clear(); monitor_generations.clear()
    if not items: print("[WARNING] No items from DB.")
    if deck:
        build_page(page_index)
        start_monitoring()

def callback(deck_param, k_idx, pressed):
    global page_index, numeric_mode, numeric_var, active_device_key, labels, cmds, flags, items, toggle_keys, current_session_vars, press_times, long_press_numeric_active, up_key_idx, down_key_idx, load_key_idx, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, monitor_states, monitor_generations, web_ui_process, numeric_step_memory
    if pressed: press_times[k_idx] = time.time(); return
    duration = time.time()-press_times.pop(k_idx,time.time()); lp = duration>=LONG_PRESS_THRESHOLD
    cmd_tpl,flag_str,lbl_str = cmds.get(k_idx,""),flags.get(k_idx,""),labels.get(k_idx,"")
    nw_cb, dev_cb, _, bg_cb, _, force_local_cb, is_mobile_ssh_cb_page = parse_flags(flag_str)
    g_idx_cb = key_to_global_item_idx_map.get(k_idx)
    orig_item_cmd_from_db = cmd_tpl; db_monitor_keyword = ""; orig_flags_cb_from_db = flag_str; is_mobile_ssh_cb = is_mobile_ssh_cb_page
    if g_idx_cb is not None and g_idx_cb < len(items):
        item_dict = items[g_idx_cb]
        orig_item_cmd_from_db, orig_flags_cb_from_db, db_monitor_keyword = item_dict.get('command',''), item_dict.get('flags',''), item_dict.get('monitor_keyword','')
        _,_,_,_,_,_,is_mobile_ssh_cb = parse_flags(orig_flags_cb_from_db)
    
    if k_idx == down_key_idx and lp:
        print("[INFO] Web UI launch requested...")
        if web_ui_process is None or web_ui_process.poll() is not None:
            print(f"[INFO] Starting Web UI server from: {WEB_UI_DIR}")
            if not WEB_UI_DIR.exists() or not (WEB_UI_DIR / "package.json").exists():
                print(f"[ERROR] Web UI directory not found or is not a valid npm project at {WEB_UI_DIR}", file=sys.stderr); return
            try:
                web_ui_process = subprocess.Popen(['npm', 'run', 'dev'], cwd=WEB_UI_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                print("[INFO] Web UI server is starting... Please wait a few seconds.")
                time.sleep(5)
            except Exception as e:
                print(f"[ERROR] Failed to start Web UI server: {e}", file=sys.stderr); return
        else:
            print("[INFO] Web UI server is already running.")
        webbrowser.open(f"http://localhost:{REACT_APP_DEV_PORT}"); return
    
    if k_idx == load_key_idx and not lp: load_data_and_reinit_vars(); redraw(); return
    
    if numeric_mode and long_press_numeric_active and numeric_var:
        num_key = numeric_var['key'];
        if k_idx==num_key: numeric_mode=False; numeric_var=None; long_press_numeric_active=False; flash_state=False; toggle_keys.clear(); redraw();return
        elif k_idx in [up_key_idx,down_key_idx]:
            step = numeric_var['step']*(5 if lp else 1); curr_val=current_session_vars.get(numeric_var['name'],"0");
            try: curr=float(curr_val)
            except ValueError: curr = 0.0
            new=curr+step if k_idx==up_key_idx else curr-step; current_session_vars[numeric_var['name']]=new
            cmd_run=resolve_command_string(numeric_var['cmd_template'],current_session_vars)
            run_cmd_in_terminal(cmd_run, act_at_lbl=labels.get(active_device_key), force_local_execution=numeric_var.get('force_local', False))
            redraw(); return
        else: numeric_mode=False; numeric_var=None; long_press_numeric_active=False; flash_state=False; toggle_keys.clear()
    
    if not (numeric_mode and long_press_numeric_active) and not lp:
         if k_idx==up_key_idx: page_index-=1; build_page(page_index); redraw(); return
         if k_idx==down_key_idx: page_index+=1; build_page(page_index); redraw(); return
    
    if '#' in flag_str and lp:
        m=VAR_PATTERN.search(cmd_tpl)
        if not m: print(f"ERR:# no var {k_idx}");redraw();return
        v_n,d_v=m.group(1).strip(),m.group(3)or"0"; s_v_s=execute_applescript_dialog(f"START {v_n}:",current_session_vars.get(v_n,d_v))
        if not s_v_s or s_v_s in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]: redraw();return
        last_step = numeric_step_memory.get(k_idx, "1")
        stp_s=execute_applescript_dialog(f"STEP {v_n}:", last_step)
        if not stp_s or stp_s in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]: redraw();return
        try:
            s_v,stp_v=float(s_v_s),float(stp_s)
            numeric_step_memory[k_idx] = stp_s
        except:print("ERR:Invalid num");redraw();return
        current_session_vars[v_n]=s_v;numeric_mode=True;long_press_numeric_active=True
        numeric_var={"name":v_n,"value":s_v,"step":stp_v,"cmd_template":cmd_tpl,"key":k_idx, "force_local": force_local_cb, "is_mobile_ssh": is_mobile_ssh_cb}
        toggle_keys.clear();toggle_keys.add(k_idx);redraw();return
    elif dev_cb and not lp:
        style={"lbl":lbl_str,"bg_hex":bg_cb,"text_color_name":text_color(bg_cb)};force=k_idx in at_devices_to_reinit_cmd
        if force: at_devices_to_reinit_cmd.remove(k_idx)
        if active_device_key==k_idx and not force: active_device_key=None;toggle_keys.discard(k_idx)
        else:
            if active_device_key is not None:toggle_keys.discard(active_device_key)
            active_device_key=k_idx;toggle_keys.add(k_idx)
            cmd_r=resolve_command_string(orig_item_cmd_from_db,current_session_vars)
            if is_mobile_ssh_cb and cmd_r.lower().strip().startswith("ssh ") and not force_local_cb: cmd_r = _transform_ssh_user_for_mobile(cmd_r)
            run_cmd_in_terminal(cmd_r,is_at_act=True,at_has_n=nw_cb,btn_style_cfg=style,force_new_win_at=force, force_local_execution=force_local_cb)
        redraw();return
    elif 'V' in flag_str.upper() and lp:
        v_f=list(VAR_PATTERN.finditer(cmd_tpl))
        if not v_f:print(f"ERR:V no vars {k_idx}");redraw();return
        chg=False
        for m in v_f:
            v_n,d_v=m.group(1).strip(),m.group(3)or"";c_v=str(current_session_vars.get(v_n,d_v))
            n_v=execute_applescript_dialog(f"Val for {v_n}:",c_v)
            if n_v and n_v not in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None] and n_v!=c_v:current_session_vars[v_n]=n_v;chg=True
        if dev_cb:
            at_devices_to_reinit_cmd.add(k_idx)
            if k_idx==active_device_key and chg:active_device_key=None;toggle_keys.discard(k_idx)
        redraw();return
    
    res_cmd = resolve_command_string(orig_item_cmd_from_db, current_session_vars)
    
    run_cmd_in_terminal(res_cmd,
                        act_at_lbl=labels.get(active_device_key),
                        force_local_execution=force_local_cb)
    redraw()

# --- Main Execution Block ---
if __name__ == "__main__":
    print("[INFO] Initializing Stream Deck Driver...")
    try:
        all_decks = DeviceManager().enumerate()
        if not all_decks: print("No Stream Deck found. Exiting."); sys.exit(1)
        deck = all_decks[0]; deck.open(); deck.reset()
        print(f"[INFO] Opened Stream Deck: {deck.deck_type()} ({deck.key_count()} keys)")
    except Exception as e:
        print(f"[FATAL] Deck init error: {e}"); sys.exit(1)
    
    cnt = deck.key_count(); rows_sd, cols_sd = deck.key_layout()
    load_key_idx = 0
    up_key_idx = cols_sd if cnt >= 15 else (1 if cnt == 6 else None)
    down_key_idx = 2 * cols_sd if cnt >= 15 else (4 if cnt == 6 else None)
    print(f"[INFO] Layout: {rows_sd}r,{cols_sd}c. L:{load_key_idx},U:{up_key_idx},D:{down_key_idx}")

    flask_server_thread = threading.Thread(target=run_flask_app_thread, daemon=True)
    flask_server_thread.start()

    load_data_and_reinit_vars()
    
    deck.set_key_callback(callback)
    redraw()

    print("[INFO] Stream Deck initialized. Listening for key presses...")
    try:
        while True:
            flash_driver = False
            if numeric_mode and long_press_numeric_active:
                flash_driver = True
            else:
                for g_idx in key_to_global_item_idx_map.values():
                    if g_idx < len(items):
                        mon_state = monitor_states.get(g_idx)
                        item_flgs = items[g_idx].get('flags', '')
                        if (mon_state == 'BROKEN' or mon_state == 'PROCESS_BROKEN') and '!' in item_flgs:
                            flash_driver = True; break
                        if mon_state == 'connected' and '!' in item_flgs:
                            flash_driver = True; break
            
            if flash_driver:
                flash_state = not flash_state
            elif flash_state:
                flash_state = False
            
            redraw()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[INFO] KeyboardInterrupt: Exiting...")
    finally:
        print("[INFO] Cleaning up...")
        if web_ui_process:
            print("[INFO] Terminating Web UI server...")
            web_ui_process.terminate()
            try: web_ui_process.wait(timeout=5)
            except subprocess.TimeoutExpired: print("[WARN] Web UI server did not terminate gracefully, killing."); web_ui_process.kill()
        if deck:
            deck.reset()
            deck.close()
        print("[INFO] Exited.")

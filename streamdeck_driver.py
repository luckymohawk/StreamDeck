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
import threading

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

# --- Helper Functions ---
def applescript_escape_string(s):
    s = str(s)
    s = s.replace('“', '"').replace('”', '"')
    s = s.replace('\\', '\\\\')
    s = s.replace('\n', '\\n')
    s = s.replace('"', '\\"')
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
    
    if base_filename != template_filename and not primary_name_has_ext :
         potential_filenames.append(base_filename)

    filepath_to_use = None
    seen = set()
    unique_potential_filenames = [x for x in potential_filenames if not (x in seen or seen.add(x))]

    for fname in unique_potential_filenames:
        filepath_scripts = SCRIPTS_DIR / fname
        if filepath_scripts.exists(): filepath_to_use = filepath_scripts; break
        filepath_appdir = APP_DIR / fname
        if filepath_appdir.exists(): filepath_to_use = filepath_appdir; break
        
    if not filepath_to_use: raise FileNotFoundError(f"AS template not found from '{template_filename}' (checked variants: {unique_potential_filenames}) in {SCRIPTS_DIR} or {APP_DIR}")
    
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
    for _label, cmd, _flags, _keyword in items_list:
        if not cmd: continue
        for match in VAR_PATTERN.finditer(cmd):
            var_name, default_value = match.group(1), match.group(3) if match.group(3) is not None else ""
            if var_name not in session_vars_dict: session_vars_dict[var_name] = default_value

def resolve_command_string(command_str_template, session_vars_dict):
    resolved_cmd = command_str_template
    for var_name, var_value in session_vars_dict.items():
        resolved_cmd = re.compile(r"(\{\{)(" + re.escape(var_name) + r")(:[^}]*)?(\}\})").sub(str(var_value), resolved_cmd)
    for match in list(VAR_PATTERN.finditer(resolved_cmd)):
        full_placeholder, var_name, default_in_cmd = match.group(0), match.group(1), match.group(3) if match.group(3) is not None else ""
        if var_name not in session_vars_dict: session_vars_dict[var_name] = default_in_cmd
        resolved_cmd = resolved_cmd.replace(full_placeholder, str(default_in_cmd))
    return resolved_cmd.replace('\\"', '"')

def get_items():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT label, command, flags, monitor_keyword FROM streamdeck ORDER BY id")
        return [(lbl or "", cmd or "", flgs or "", kw or "") for lbl, cmd, flgs, kw in cur.fetchall()]

def parse_flags(flags_str):
    f = (flags_str or "").strip().upper()
    if not f or f == 'MISSING VALUE':
        return False, False, False, BASE_COLORS['K'], DEFAULT_FONT_SIZE, False, False # new_win, device, sticky, col, font_size, force_local, is_mobile_ssh

    new_win, device, sticky = 'N' in f, '@' in f, 'T' in f or '@' in f
    font_size = int(m.group(1)) if (m := re.search(r"(\d+)", f)) else DEFAULT_FONT_SIZE
    
    force_local_execution = 'K' in f
    is_mobile_ssh_flag = 'M' in f
    
    base_color_char_for_display = 'K'
    
    non_k_color_found = False
    color_priority_chars = [c for c in BASE_COLORS.keys() if c != 'K']
    for char_code in f:
        if char_code in color_priority_chars:
            base_color_char_for_display = char_code
            non_k_color_found = True
            break
            
    if not non_k_color_found and force_local_execution :
        base_color_char_for_display = 'K'

    col = BASE_COLORS.get(base_color_char_for_display, BASE_COLORS['K'])

    if 'D' in f and base_color_char_for_display != 'K':
        try:
            col = f"#{''.join(f'{int(col[i:i+2],16)//2:02X}' for i in (1,3,5))}"
        except:
            pass
            
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
    """For M-flagged SSH commands: Changes 'ssh user@host ...' to 'ssh mobile@host ...'."""
    if not command_text or not command_text.lower().strip().startswith("ssh "):
        return command_text
    
    match = SSH_USER_HOST_CMD_PATTERN.match(command_text)
    if match:
        ssh_options_part = match.group(1)
        host_part = match.group(3)
        remote_cmd_part = match.group(4) if match.group(4) else ""
        
        new_cmd = f"{ssh_options_part} mobile@{host_part}{remote_cmd_part}"
        # print(f"[INFO] M-transform (_transform_ssh_user_for_mobile): '{command_text}' -> '{new_cmd}'")
        return new_cmd
    else:
        # print(f"[WARN] M-transform (_transform_ssh_user_for_mobile): Could not parse user@host in '{command_text}' with precise regex. No transformation applied.")
        return command_text

def render_key(label, deck, bg_hex, fs, txt_override=None, status_txt=None, vars_txt=None, flash_txt=False):
    W,H = deck.key_image_format()['size']; img = PILHelper.create_image(deck); draw = ImageDraw.Draw(img)
    try: pil_bg = tuple(int(bg_hex.lstrip('#')[i:i+2],16) for i in (0,2,4))
    except: pil_bg = (0,0,0)
    draw.rectangle([(0,0),(W,H)], fill=pil_bg)
    try: font_s,font_l,font_v = ImageFont.truetype(FONT_PATH,10),ImageFont.truetype(FONT_PATH,fs),ImageFont.truetype(FONT_PATH,10)
    except IOError: font_s,font_l,font_v = ImageFont.load_default(),ImageFont.load_default(),ImageFont.load_default()
    
    final_txt_color = txt_override or text_color(bg_hex)
    
    status_text_height_reserved = 0
    actual_status_text_to_draw = ""
    if status_txt:
        if flash_txt and status_txt.upper()=="CONNECTED":
            status_text_height_reserved = (font_s.getbbox("CONNECTED",anchor="lt")[3]-font_s.getbbox("CONNECTED",anchor="lt")[1]) if hasattr(font_s,'getbbox') else font_s.getsize("Tg")[1]
            global flash_state
            if not flash_state: actual_status_text_to_draw = status_txt
        else:
            actual_status_text_to_draw = status_txt
            s_bbox_temp = font_s.getbbox(actual_status_text_to_draw,anchor="lt") if hasattr(font_s,'getbbox') else (0,0,*draw.textsize(actual_status_text_to_draw,font=font_s))
            status_text_height_reserved = (s_bbox_temp[3]-s_bbox_temp[1]) if hasattr(font_s,'getbbox') else font_s.getsize("Tg")[1]

    if actual_status_text_to_draw:
        s_bbox = font_s.getbbox(actual_status_text_to_draw,anchor="lt") if hasattr(font_s,'getbbox') else (0,0,*draw.textsize(actual_status_text_to_draw,font=font_s))
        status_text_width = s_bbox[2] - s_bbox[0]
        draw.text(((W-status_text_width)/2, 3), actual_status_text_to_draw, font=font_s, fill=final_txt_color, anchor="lt" if hasattr(draw,'textbbox') else None)

    label_y_start = 3 + (status_text_height_reserved + LINE_SPACING if status_text_height_reserved > 0 else 0)
    current_label_y = label_y_start
    
    if label:
        w = max(3,min(W//(fs//2 if fs>0 else 10), 6 if fs>=ARROW_FONT_SIZE else (8 if fs>=DEFAULT_FONT_SIZE else 10)))
        ml = 1 if fs>=ARROW_FONT_SIZE else (2 if fs>=DEFAULT_FONT_SIZE else 3)
        lines = textwrap.wrap(label,width=w,max_lines=ml)
        
        lh_bbox = font_l.getbbox("Tg",anchor="lt") if hasattr(font_l,'getbbox') else (0,0,*font_l.getsize("Tg"))
        lh = lh_bbox[3]-lh_bbox[1]
        total_label_h = len(lines)*lh + (len(lines)-1)*LINE_SPACING if lines else 0
        
        num_var_lines_to_render = 0
        if vars_txt:
            var_char_width_approx_calc = 10 * 0.55
            max_chars_calc = W // var_char_width_approx_calc if var_char_width_approx_calc > 0 else 10
            temp_wrapped_vars = []
            for v_part in vars_txt.split(): temp_wrapped_vars.extend(textwrap.wrap(v_part, width=int(max_chars_calc), max_lines=1, placeholder="…"))
            num_var_lines_to_render = min(len(temp_wrapped_vars), 2)

        max_h_for_label = H - ( (10 + VAR_LINE_SPACING) * num_var_lines_to_render + LINE_SPACING*2)
        
        y = label_y_start
        if total_label_h < (max_h_for_label - label_y_start):
             y = label_y_start + ((max_h_for_label - label_y_start - total_label_h) / 2)
        current_label_y = max(y, label_y_start)


        for line_item in lines:
            if current_label_y + lh > max_h_for_label : break
            l_bbox = font_l.getbbox(line_item,anchor="lt") if hasattr(font_l,'getbbox') else (0,0,*draw.textsize(line_item,font=font_l))
            line_width = l_bbox[2] - l_bbox[0]
            draw.text(((W-line_width)/2, current_label_y), line_item, font=font_l, fill=final_txt_color, anchor="lt" if hasattr(draw,'textbbox') else None)
            current_label_y += lh+LINE_SPACING
            
    if vars_txt:
        v_lines_raw = vars_txt.split()
        v_lines_wrapped = []
        var_char_width_approx = 10 * 0.55
        max_chars_per_var_line = W // var_char_width_approx if var_char_width_approx > 0 else 12
        
        for v_item_raw in v_lines_raw:
            v_lines_wrapped.extend(textwrap.wrap(v_item_raw, width=int(max_chars_per_var_line), max_lines=1, placeholder="…"))

        var_line_h_render = 10
        num_var_lines_to_draw = min(len(v_lines_wrapped), 2)
        
        start_y_for_vars = H - LINE_SPACING - (num_var_lines_to_draw * var_line_h_render) - ((num_var_lines_to_draw - 1) * VAR_LINE_SPACING if num_var_lines_to_draw > 1 else 0)
        min_y_after_label = current_label_y if label and lines else label_y_start
        actual_y_for_first_var = max(start_y_for_vars, min_y_after_label)

        for i in range(num_var_lines_to_draw):
            v_item_final = v_lines_wrapped[i]
            current_y_for_this_var = actual_y_for_first_var + i * (var_line_h_render + VAR_LINE_SPACING)
            
            if current_y_for_this_var + var_line_h_render > H - LINE_SPACING + 2: continue

            v_bbox = font_v.getbbox(v_item_final,anchor="lt") if hasattr(font_v,'getbbox') else (0,0,*draw.textsize(v_item_final,font=font_v))
            var_item_width = v_bbox[2] - v_bbox[0]
            draw.text(((W-var_item_width)/2, current_y_for_this_var ), v_item_final, font=font_v, fill=final_txt_color, anchor="lt" if hasattr(draw,'textbbox') else None)
            
    return PILHelper.to_native_format(deck,img)

def run_cmd_in_terminal(main_cmd, is_at_act=False, at_has_n=False, btn_style_cfg=None, act_at_lbl=None,
                        is_n_staged=False, ssh_staged="", n_staged="", prepend="", force_new_win_at=False,
                        force_local_execution=False):
    
    eff_cmd = f"{prepend}\n{main_cmd.strip()}" if prepend and main_cmd.strip() else (prepend or main_cmd.strip())
    eff_cmd = eff_cmd.replace('“','"').replace('”','"')
    esc_cmd, raw_cmd_check = applescript_escape_string(eff_cmd), applescript_escape_string(eff_cmd)
    as_script, script_vars = "", {}
    
    tpl_map = {
        "n_staged":"terminal_n_for_at_staged_keystroke.applescript",
        "at_n":"terminal_activate_new_styled_at_n.applescript",
        "at_only":"terminal_activate_found_at_only.applescript",
        "n_alone":"terminal_activate_standalone_n.applescript",
        "to_active_at":"terminal_command_to_active_at_device.applescript",
        "default":"terminal_do_script_default.applescript",
        "force_local_new_window": "terminal_force_new_window_and_do_script.applescript"
    }

    if force_local_execution:
        if eff_cmd:
            script_vars['final_script_payload_for_do_script'] = esc_cmd
            as_script = load_applescript_template(tpl_map["force_local_new_window"], **script_vars)
        else:
            return
    else:
        is_cmd_to_act_at = act_at_lbl and not is_at_act and not (btn_style_cfg and btn_style_cfg.get('is_standalone_n_button',False)) and not is_n_staged
        if not eff_cmd and not is_at_act and not is_cmd_to_act_at and not (is_n_staged and ssh_staged): return

        if is_n_staged:
            if not btn_style_cfg or not ssh_staged: print(f"[ERR] N-Staged missing info"); return
            script_vars['window_custom_title'] = applescript_escape_string(btn_style_cfg['lbl'])
            script_vars['aps_bg_color'] = hex_to_aps_color_values_str(btn_style_cfg['bg_hex'])
            script_vars['aps_text_color'] = "{65535,65535,65535}" if btn_style_cfg.get('text_color_name','white')=='white' else "{0,0,0}"
            script_vars['ssh_command_to_keystroke'] = applescript_escape_string(ssh_staged)
            script_vars['actual_n_command_to_keystroke'] = applescript_escape_string(n_staged)
            as_script = load_applescript_template(tpl_map["n_staged"], **script_vars)
        elif is_at_act:
            if not btn_style_cfg or 'lbl' not in btn_style_cfg:
                if eff_cmd:
                    script_vars['final_script_payload_for_do_script']=esc_cmd
                    as_script=load_applescript_template(tpl_map["default"],**script_vars)
                else: return
            else:
                dev_lbl = btn_style_cfg['lbl']
                script_vars['escaped_device_label'] = applescript_escape_string(dev_lbl)
                script_vars['aps_bg_color'] = hex_to_aps_color_values_str(btn_style_cfg['bg_hex'])
                script_vars['aps_text_color'] = "{65535,65535,65535}" if btn_style_cfg.get('text_color_name','white')=='white' else "{0,0,0}"
                if at_has_n:
                    script_vars['final_script_payload']=esc_cmd
                    as_script=load_applescript_template(tpl_map["at_n"],**script_vars)
                else:
                    script_vars['final_script_payload_for_do_script']=esc_cmd
                    script_vars['force_new_window']="true" if force_new_win_at else "false"
                    as_script=load_applescript_template(tpl_map["at_only"],**script_vars)
        elif btn_style_cfg and btn_style_cfg.get('is_standalone_n_button',False):
            cfg = btn_style_cfg
            script_vars['window_custom_title'] = applescript_escape_string(cfg['lbl'])
            script_vars['aps_bg_color'] = hex_to_aps_color_values_str(cfg['bg_hex'])
            script_vars['aps_text_color'] = "{65535,65535,65535}" if cfg.get('text_color_name','white')=='white' else "{0,0,0}"
            script_vars['final_script_payload_for_do_script'] = esc_cmd
            as_script = load_applescript_template(tpl_map["n_alone"],**script_vars)
        elif is_cmd_to_act_at:
            script_vars['safe_target_title'] = applescript_escape_string(act_at_lbl)
            script_vars['final_script_payload_for_do_script'] = esc_cmd
            script_vars['main_command_raw_for_emptiness_check'] = raw_cmd_check
            script_vars['command_to_type_literally_content'] = esc_cmd
            as_script = load_applescript_template(tpl_map["to_active_at"],**script_vars)
        elif eff_cmd:
            script_vars['final_script_payload_for_do_script']=esc_cmd
            as_script=load_applescript_template(tpl_map["default"],**script_vars)

    if as_script:
        proc = subprocess.run(["osascript","-"],input=as_script,text=True,capture_output=True,check=False)
        if proc.returncode!=0 and "(-128)" not in proc.stderr.lower() and "(-1712)" not in proc.stderr.lower():
            pass
        if proc.stderr.strip() and "(-128)" not in proc.stderr.lower() and not ("execution error" in proc.stderr.lower() and "(-1753)" in proc.stderr.lower()):
            pass

# --- Monitoring Functions ---
def monitor_ssh(global_idx, ssh_cmd_base, generation_id):
    chk_cmd = f"{ssh_cmd_base} exit"
    while global_idx in monitor_threads and monitor_generations.get(global_idx) == generation_id:
        time.sleep(0.05)
        if monitor_generations.get(global_idx) != generation_id: break

        new_state = 'BROKEN'
        try:
            res = subprocess.run(shlex.split(chk_cmd) if not any(c in chk_cmd for c in "|;&><") else chk_cmd,
                                 shell=any(c in chk_cmd for c in "|;&><"), capture_output=True, text=True, timeout=8)
            if res.returncode == 0: new_state = 'connected'
        except subprocess.TimeoutExpired: pass
        except Exception: pass
        
        if monitor_generations.get(global_idx) == generation_id:
            if monitor_states.get(global_idx) != new_state:
                monitor_states[global_idx] = new_state
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
        time.sleep(0.05)
        if monitor_generations.get(global_idx) != generation_id: break
        
        new_proc_state = 'PROCESS_BROKEN'
        try:
            result = subprocess.run(full_ssh_cmd_str, shell=True, capture_output=True, text=True, timeout=8)
            if result.returncode == 0 and result.stdout.strip():
                new_proc_state = 'PROCESS_RUNNING'
            elif result.returncode == 1:
                new_proc_state = 'PROCESS_BROKEN'
            else:
                new_proc_state = 'PROCESS_ERROR'
        except subprocess.TimeoutExpired: new_proc_state = 'PROCESS_ERROR'
        except Exception: new_proc_state = 'PROCESS_ERROR'

        if monitor_generations.get(global_idx) == generation_id:
            if monitor_states.get(global_idx) != new_proc_state:
                monitor_states[global_idx] = new_proc_state
        else: break
        
        sleep_duration = 3 + (global_idx % 7) * 0.1
        for _ in range(int(sleep_duration / 0.1)):
            if monitor_generations.get(global_idx) != generation_id: break
            time.sleep(0.1)
        if monitor_generations.get(global_idx) != generation_id: break


# --- Main Stream Deck Setup and Logic ---
if __name__ == "__main__":
    print("[INFO] Initializing Stream Deck Driver...")
    try:
        all_decks = DeviceManager().enumerate()
        if not all_decks: print("No Stream Deck found. Exiting."); sys.exit(1)
        deck = all_decks[0]; deck.open(); deck.reset()
        print(f"[INFO] Opened Stream Deck: {deck.deck_type()} ({deck.key_count()} keys)")
    except TransportError as e: print(f"[FATAL] TransportError: {e}\nEnsure no other SD software runs."); sys.exit(1)
    except Exception as e:
        print(f"[FATAL] Deck init error: {e}");
        if deck:
            try: deck.close()
            except: pass
        sys.exit(1)
    
    cnt = deck.key_count(); rows_sd, cols_sd = deck.key_layout()
    load_key_idx = 0
    up_key_idx = cols_sd if cnt >= 15 and cols_sd > 0 else cnt // 3
    down_key_idx = (2 * cols_sd if cnt >= 15 and cols_sd > 0 else 2 * (cnt // 3))
    if cnt == 6 and cols_sd == 3 : up_key_idx = cols_sd ; down_key_idx = cnt - 1
    print(f"[INFO] Layout: {rows_sd}r,{cols_sd}c. L:{load_key_idx},U:{up_key_idx},D:{down_key_idx}")

    def build_page(idx_param):
        global labels, cmds, flags, items, page_index, key_to_global_item_idx_map
        key_to_global_item_idx_map.clear()
        if not items: idx_param = 0 if idx_param == 0 else page_index
        
        indexed_items = [(i, item, parse_flags(item[2])) for i, item in enumerate(items)]
        sticky = [p for p in indexed_items if p[2][2]]
        normal = [p for p in indexed_items if not p[2][2]]
        
        fixed = {load_key_idx, up_key_idx, down_key_idx}
        avail_slots = [s for s in range(cnt) if s not in fixed]
        new_lbl, new_cmd, new_flg = {}, {}, {}

        s_idx = 0
        for orig_i, item_data, _ in sticky:
            if s_idx < len(avail_slots):
                key = avail_slots[s_idx]
                new_lbl[key], new_cmd[key], new_flg[key] = item_data[0],item_data[1],item_data[2]
                key_to_global_item_idx_map[key] = orig_i; s_idx+=1
            else: break
            
        norm_slots = avail_slots[s_idx:]
        num_norm_slots = len(norm_slots)
        tot_norm_pg = ceil(len(normal)/num_norm_slots) if normal and num_norm_slots>0 else 1
        
        page_index = idx_param % tot_norm_pg if tot_norm_pg > 0 else 0
        start_norm_idx = page_index * num_norm_slots
        
        for i_slot, key in enumerate(norm_slots):
            curr_norm_idx = start_norm_idx + i_slot
            if curr_norm_idx < len(normal):
                orig_i, item_data, _ = normal[curr_norm_idx]
                new_lbl[key],new_cmd[key],new_flg[key] = item_data[0],item_data[1],item_data[2]
                key_to_global_item_idx_map[key] = orig_i
            else: new_lbl[key],new_cmd[key],new_flg[key] = "","",""

        for k,l_val,c_val,f_val in [(load_key_idx,"LOAD","","W"),(up_key_idx,"▲","","W"),(down_key_idx,"▼","","W")]:
            new_lbl[k],new_cmd[k],new_flg[k]=l_val,c_val,f_val
        labels,cmds,flags = new_lbl,new_cmd,new_flg

    def redraw():
        global labels, cmds, flags, numeric_mode, numeric_var, active_device_key, current_session_vars, up_key_idx, down_key_idx, load_key_idx, cnt, deck, long_press_numeric_active, flash_state, items, key_to_global_item_idx_map, monitor_states
        if not deck: return

        for i_key in range(cnt):
            f_str_pg, cmd_str_pg, lbl_str_pg = flags.get(i_key,""), cmds.get(i_key,""), labels.get(i_key,"")
            _, dev_flag_pg, _, bg_pg, fs_pg, _, _ = parse_flags(f_str_pg)
            
            lbl_render, status_render, vars_render = lbl_str_pg, None, None
            bg_render, txt_override_render, flash_txt_render = bg_pg, None, False
            styled = False; fs_render = fs_pg

            g_idx = key_to_global_item_idx_map.get(i_key)
            if g_idx is not None and g_idx < len(items):
                item_lbl, item_cmd_db, item_flags_str, _ = items[g_idx]
                _,item_is_at,_,item_orig_bg,item_orig_fs_from_db, _, _ = parse_flags(item_flags_str)
                fs_render = item_orig_fs_from_db

                if item_is_at and '!' in item_flags_str:
                    styled=True; lbl_render=item_lbl
                    base_bg = dim_color(item_orig_bg) if active_device_key!=i_key else toggle_button_bg(item_orig_bg)
                    bg_render = base_bg
                    mon_state = monitor_states.get(g_idx)
                    if mon_state=='connected': status_render="CONNECTED"; flash_txt_render=True
                    elif mon_state=='BROKEN':
                        status_render="BROKEN"
                        if flash_state: bg_render = BASE_COLORS['R']
                    elif mon_state == 'initializing': status_render = "INIT..."
                    elif mon_state: status_render=mon_state.upper()[:10];
                    
                    if mon_state in ['error_config','error'] or ('config' in (mon_state or "")): bg_render = BASE_COLORS['R']
                    elif mon_state == 'disabled': bg_render = BASE_COLORS['E']
                    txt_override_render = text_color(bg_render)
                    vars_render = " ".join(str(current_session_vars.get(m.group(1))) for m in VAR_PATTERN.finditer(item_cmd_db) if current_session_vars.get(m.group(1)) is not None) or None

                elif not item_is_at and '!' in item_flags_str:
                    proc_state = monitor_states.get(g_idx)
                    if proc_state:
                        styled=True; lbl_render=item_lbl;
                        current_flash_for_broken_proc = False
                        if proc_state == "PROCESS_INIT": status_render="INIT..." ; bg_render=BASE_COLORS['O']
                        elif proc_state == "PROCESS_RUNNING": status_render="RUNNING"; bg_render=BASE_COLORS['G']
                        elif proc_state == "PROCESS_BROKEN":
                            status_render="BROKEN"; bg_render=BASE_COLORS['R']
                            current_flash_for_broken_proc = True
                        elif proc_state == "PROCESS_NO_AT": status_render="NO @DEV"; bg_render=BASE_COLORS['E']
                        elif proc_state == "PROCESS_NO_KW": status_render="NO TAG"; bg_render=BASE_COLORS['E']
                        elif proc_state == "PROCESS_ERROR": status_render="P_ERROR"; bg_render=BASE_COLORS['R']
                        else:
                            status_render = proc_state[:10]
                            bg_render = item_orig_bg
                        txt_override_render = text_color(bg_render)
                        if current_flash_for_broken_proc and flash_state:
                            try: r_d,g_d,b_d = [int(BASE_COLORS['R'][c:c+2],16)//2 for c in (1,3,5)]; bg_render = f"#{r_d:02X}{g_d:02X}{b_d:02X}"
                            except: pass
            
            if not styled and numeric_mode and long_press_numeric_active and numeric_var:
                num_key = numeric_var.get('key')
                if i_key==num_key or i_key==up_key_idx or i_key==down_key_idx:
                    styled=True; lbl_render=lbl_str_pg
                    fs_render = fs_pg
                    _,_,_,num_orig_bg,_,_,_ = parse_flags(flags.get(num_key,""))
                    bright_num_bg = toggle_button_bg(num_orig_bg)
                    bg_render = bright_num_bg if flash_state else (num_orig_bg if i_key==num_key else dim_color(bright_num_bg))
                    txt_override_render = text_color(bg_render)
                    if i_key==num_key:
                        vars_val = current_session_vars.get(numeric_var['name'])
                        if isinstance(vars_val,(float,int)): vars_render = f"{float(vars_val):.1f}" if not float(vars_val).is_integer() else str(int(vars_val))
                        else: vars_render = str(vars_val)
                    elif i_key in [up_key_idx,down_key_idx]:
                        step=numeric_var.get('step',1.0); op="+" if i_key==up_key_idx else "-"
                        vars_render=f"{op}{step:.1f}" if isinstance(step,float) and not float(step).is_integer() else f"{op}{int(step)}"
            
            if not styled and dev_flag_pg:
                styled=True; lbl_render=lbl_str_pg; fs_render = fs_pg
                bg_render = toggle_button_bg(bg_pg) if active_device_key==i_key else dim_color(bg_pg)
                txt_override_render = text_color(bg_render)
                vars_render = " ".join(str(current_session_vars.get(m.group(1))) for m in VAR_PATTERN.finditer(cmd_str_pg) if current_session_vars.get(m.group(1)) is not None) or None

            if not styled and not dev_flag_pg:
                is_v = 'V' in f_str_pg.upper()
                is_hash_not_num = '#' in f_str_pg and not (numeric_mode and numeric_var and i_key==numeric_var.get('key'))
                if is_v or is_hash_not_num:
                    fs_render = fs_pg
                    vals = []
                    for m in VAR_PATTERN.finditer(cmd_str_pg):
                        val = current_session_vars.get(m.group(1))
                        if val is not None:
                            if is_hash_not_num:
                                try:
                                    v_f = float(val)
                                    vals.append(f"{v_f:.1f}" if not v_f.is_integer() else str(int(v_f)))
                                except ValueError:
                                    vals.append(str(val))
                            else:
                                vals.append(str(val))
                    if vals: vars_render = " ".join(vals)
            
            final_fs_to_use = ARROW_FONT_SIZE if i_key in [up_key_idx,down_key_idx] else fs_render
            try: deck.set_key_image(i_key, render_key(lbl_render,deck,bg_render,final_fs_to_use,txt_override_render,status_render,vars_render,flash_txt_render))
            except Exception: pass

    def start_monitoring():
        global items, monitor_threads, monitor_states, current_session_vars, monitor_generations
        for g_idx in list(monitor_threads.keys()):
            monitor_generations[g_idx] = None
            if g_idx in monitor_threads: del monitor_threads[g_idx]
        
        for g_idx, item_data in enumerate(items):
            item_label_mon, item_cmd_mon, item_flags_mon, _ = item_data
            _, _, _, _, _, _, item_is_mobile_mon = parse_flags(item_flags_mon)

            if '!' in item_flags_mon and '@' in item_flags_mon:
                monitor_states.pop(g_idx, None)
                monitor_states[g_idx] = 'initializing'
                current_gen_id = time.time()
                monitor_generations[g_idx] = current_gen_id
                
                resolved_cmd_mon = resolve_command_string(item_cmd_mon, current_session_vars)
                if item_is_mobile_mon and resolved_cmd_mon.lower().strip().startswith("ssh "):
                    resolved_cmd_mon = _transform_ssh_user_for_mobile(resolved_cmd_mon)
                
                ssh_match_mon = re.match(r"^(ssh\s+[^ ]+)", resolved_cmd_mon)
                if ssh_match_mon:
                    thread = threading.Thread(target=monitor_ssh, args=(g_idx, ssh_match_mon.group(1), current_gen_id), daemon=True)
                    monitor_threads[g_idx] = thread; thread.start()
                else: monitor_states[g_idx] = 'error_config'
            elif '!' in item_flags_mon and not '@' in item_flags_mon:
                 monitor_states.pop(g_idx, None)
        print("[INFO] SSH Monitoring threads initialized (Process monitoring on demand).")


    def load_data_and_reinit_vars():
        global items, current_session_vars, page_index, numeric_mode, numeric_var, active_device_key, toggle_keys, long_press_numeric_active, deck, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, monitor_generations
        print("[INFO] Rebuilding database & reloading configs...")
        if os.path.exists(DB_PATH):
            try: os.remove(DB_PATH)
            except OSError as e: print(f"[ERR] DB remove: {e}")
        try:
            py_exec = sys.executable; load_script_path = APP_DIR/"streamdeck_db.py"
            if not load_script_path.exists(): load_script_path = Path("streamdeck_db.py")
            res = subprocess.run([py_exec,str(load_script_path),str(DB_PATH)],check=True,capture_output=True,text=True)
            if res.stdout and "✅ Database" not in res.stdout and "corrected to fetch" not in res.stdout : print(f"[DB_OUT] {res.stdout.strip()}")
            if res.stderr: print(f"[DB_ERR] {res.stderr.strip()}")
        except Exception as e:
            err_out = getattr(e, 'stderr', '') or getattr(e, 'stdout', '') or str(e)
            print(f"[FATAL] DB Load Script failed: {err_out}. Exiting.")
            if deck:
                try: deck.reset(); deck.close()
                except: pass
            sys.exit(1)

        items[:] = get_items(); initialize_session_vars_from_items(items, current_session_vars)
        page_index=0; numeric_mode=False; numeric_var=None; long_press_numeric_active=False
        active_device_key=None; toggle_keys.clear(); at_devices_to_reinit_cmd.clear()
        flash_state=False; key_to_global_item_idx_map.clear(); monitor_generations.clear()
        if not items: print("[WARNING] No items from DB.")
        if deck: build_page(page_index)
        start_monitoring()

    load_data_and_reinit_vars()
    
    def callback(deck_param, k_idx, pressed):
        global page_index, numeric_mode, numeric_var, active_device_key, labels, cmds, flags, items, toggle_keys, current_session_vars, press_times, long_press_numeric_active, up_key_idx, down_key_idx, load_key_idx, at_devices_to_reinit_cmd, flash_state, key_to_global_item_idx_map, monitor_states, monitor_generations
        if pressed: press_times[k_idx] = time.time(); return
        duration = time.time()-press_times.pop(k_idx,time.time()); lp = duration>=LONG_PRESS_THRESHOLD
        cmd_tpl,flag_str,lbl_str = cmds.get(k_idx,""),flags.get(k_idx,""),labels.get(k_idx,"")
        
        nw_cb, dev_cb, _, bg_cb, _, force_local_cb, is_mobile_ssh_cb = parse_flags(flag_str)

        g_idx_cb = key_to_global_item_idx_map.get(k_idx)
        
        orig_item_cmd_from_db = cmd_tpl
        db_monitor_keyword = ""
        orig_flags_cb_from_db = flag_str

        if g_idx_cb is not None and g_idx_cb < len(items):
            orig_item_lbl_db, orig_item_cmd_from_db, orig_flags_cb_from_db, db_monitor_keyword = items[g_idx_cb]
            
            if '!' in orig_flags_cb_from_db:
                mon_state_cb = monitor_states.get(g_idx_cb)
                if '@' in orig_flags_cb_from_db:
                    if mon_state_cb in ['BROKEN','connected'] and not lp:
                        monitor_states[g_idx_cb] = 'initializing'
                        new_gen_id_at_cb = time.time(); monitor_generations[g_idx_cb] = new_gen_id_at_cb
                        if g_idx_cb in monitor_threads: monitor_threads.pop(g_idx_cb, None)
                        
                        res_cmd_re = resolve_command_string(orig_item_cmd_from_db, current_session_vars)
                        if is_mobile_ssh_cb: # This specific @! button is also M
                            res_cmd_re = _transform_ssh_user_for_mobile(res_cmd_re)
                            
                        ssh_m_re = re.match(r"^(ssh\s+[^ ]+)", res_cmd_re)
                        if ssh_m_re:
                            new_th = threading.Thread(target=monitor_ssh, args=(g_idx_cb, ssh_m_re.group(1), new_gen_id_at_cb), daemon=True)
                            monitor_threads[g_idx_cb] = new_th; new_th.start()
                        else: monitor_states[g_idx_cb] = 'error_config'
                
                elif not '@' in orig_flags_cb_from_db :
                    if mon_state_cb in ['PROCESS_BROKEN', 'PROCESS_ERROR', 'PROCESS_NO_AT', 'PROCESS_NO_KW', None, 'PROCESS_INIT'] and not lp:
                        pass
                    elif mon_state_cb in ['error_script_missing','error_config'] and not lp :
                         print(f"[BLOCKED] Cmd for '{lbl_str}' blocked: {mon_state_cb}"); redraw(); return
        
        if k_idx==load_key_idx and not lp: load_data_and_reinit_vars(); redraw(); return
        
        current_button_force_local = force_local_cb

        if numeric_mode and long_press_numeric_active and numeric_var:
            num_key = numeric_var['key']
            force_local_for_numeric_cmd = numeric_var.get('force_local', False)
            is_mobile_for_numeric_cmd = numeric_var.get('is_mobile_ssh', False)

            if k_idx==num_key:
                numeric_mode=False; numeric_var=None; long_press_numeric_active=False; flash_state=False; toggle_keys.clear(); redraw();return
            elif k_idx in [up_key_idx,down_key_idx]:
                step = numeric_var['step']*(5 if lp else 1); curr_val=current_session_vars.get(numeric_var['name'],"0");
                try: curr=float(curr_val)
                except ValueError: curr = 0.0
                new=curr+step if k_idx==up_key_idx else curr-step; current_session_vars[numeric_var['name']]=new
                cmd_run=resolve_command_string(numeric_var['cmd_template'],current_session_vars)

                if is_mobile_for_numeric_cmd and cmd_run.lower().strip().startswith("ssh ") and not force_local_for_numeric_cmd:
                    # Numeric buttons are non-@. M-flag means transform user in its OWN ssh command
                    cmd_run = _transform_ssh_user_for_mobile(cmd_run)
                    
                run_cmd_in_terminal(cmd_run, act_at_lbl=labels.get(active_device_key), force_local_execution=force_local_for_numeric_cmd)
                redraw(); return
            else:
                numeric_mode=False; numeric_var=None; long_press_numeric_active=False; flash_state=False; toggle_keys.clear()
        
        if not (numeric_mode and long_press_numeric_active) and not lp:
             if k_idx==up_key_idx: page_index-=1; build_page(page_index); redraw(); return
             if k_idx==down_key_idx: page_index+=1; build_page(page_index); redraw(); return
        
        if '#' in flag_str and lp:
            m=VAR_PATTERN.search(cmd_tpl)
            if not m: print(f"ERR:# no var {k_idx}");redraw();return
            v_n,d_v=m.group(1),m.group(3)or"0"; s_v_s=execute_applescript_dialog(f"START {v_n}:",current_session_vars.get(v_n,d_v))
            if not s_v_s or s_v_s in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]: redraw();return
            stp_s=execute_applescript_dialog(f"STEP {v_n}:","1")
            if not stp_s or stp_s in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]: redraw();return
            try:s_v,stp_v=float(s_v_s),float(stp_s)
            except:print("ERR:Invalid num");redraw();return
            current_session_vars[v_n]=s_v;numeric_mode=True;long_press_numeric_active=True
            numeric_var={"name":v_n,"value":s_v,"step":stp_v,"cmd_template":cmd_tpl,"key":k_idx,
                         "force_local": force_local_cb, "is_mobile_ssh": is_mobile_ssh_cb}
            toggle_keys.clear();toggle_keys.add(k_idx);redraw();return
        
        elif dev_cb and not lp: # This is an @ button press
            style={"lbl":lbl_str,"bg_hex":bg_cb,"text_color_name":text_color(bg_cb)};force=k_idx in at_devices_to_reinit_cmd
            if force: at_devices_to_reinit_cmd.remove(k_idx)
            
            if active_device_key==k_idx and not force:
                active_device_key=None;toggle_keys.discard(k_idx)
            else:
                if active_device_key is not None:toggle_keys.discard(active_device_key)
                active_device_key=k_idx;toggle_keys.add(k_idx)
                cmd_r=resolve_command_string(cmd_tpl,current_session_vars)
                
                if is_mobile_ssh_cb and cmd_r.lower().strip().startswith("ssh ") and not current_button_force_local:
                    cmd_r = _transform_ssh_user_for_mobile(cmd_r)

                run_cmd_in_terminal(cmd_r,is_at_act=True,at_has_n=nw_cb,btn_style_cfg=style,force_new_win_at=force, force_local_execution=current_button_force_local)
            redraw();return
            
        elif 'V' in flag_str.upper() and lp:
            v_f=list(VAR_PATTERN.finditer(cmd_tpl))
            if not v_f:print(f"ERR:V no vars {k_idx}");redraw();return
            chg=False
            for m in v_f:
                v_n,d_v=m.group(1),m.group(3)or"";c_v=str(current_session_vars.get(v_n,d_v))
                n_v=execute_applescript_dialog(f"Val for {v_n}:",c_v)
                if n_v and n_v not in ["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None] and n_v!=c_v:current_session_vars[v_n]=n_v;chg=True
            
            if dev_cb:
                at_devices_to_reinit_cmd.add(k_idx)
                if k_idx==active_device_key and chg:active_device_key=None;toggle_keys.discard(k_idx)
                if chg and g_idx_cb is not None and items[g_idx_cb][2].count('!') and items[g_idx_cb][2].count('@'):
                    # print(f"[INFO] Vars changed for @! button {k_idx} ('{lbl_str}'). Re-initializing its monitor.")
                    monitor_states[g_idx_cb] = 'initializing'
                    new_gen_id_vlp = time.time(); monitor_generations[g_idx_cb] = new_gen_id_vlp
                    if g_idx_cb in monitor_threads: monitor_threads.pop(g_idx_cb, None)
                    
                    _ , item_cmd_re_vlp_db_v, item_flags_re_vlp_db_v, _ = items[g_idx_cb]
                    _,_,_,_,_,_, item_is_mobile_re_vlp_v = parse_flags(item_flags_re_vlp_db_v)

                    res_cmd_re_vlp = resolve_command_string(item_cmd_re_vlp_db_v, current_session_vars)
                    
                    if item_is_mobile_re_vlp_v and res_cmd_re_vlp.lower().strip().startswith("ssh "):
                        res_cmd_re_vlp = _transform_ssh_user_for_mobile(res_cmd_re_vlp)
                        
                    ssh_m_re_vlp = re.match(r"^(ssh\s+[^ ]+)", res_cmd_re_vlp)
                    if ssh_m_re_vlp:
                        new_th_vlp = threading.Thread(target=monitor_ssh, args=(g_idx_cb, ssh_m_re_vlp.group(1), new_gen_id_vlp), daemon=True)
                        monitor_threads[g_idx_cb] = new_th_vlp; new_th_vlp.start()
                    else: monitor_states[g_idx_cb] = 'error_config'
            redraw();return
            
        elif lp and cmd_tpl and not dev_cb and'#'not in flag_str and'V'not in flag_str.upper()and k_idx not in[load_key_idx,up_key_idx,down_key_idx]:
            n_cmd=execute_applescript_dialog(f"Edit cmd '{lbl_str or k_idx}':",cmd_tpl)
            if n_cmd and n_cmd not in["USER_CANCELLED_PROMPT","USER_TIMEOUT_PROMPT",None]and n_cmd!=cmd_tpl:
                cmds[k_idx]=n_cmd
                initialize_session_vars_from_items([(labels.get(i,""),cmds.get(i,""),flags.get(i,""),"")for i in range(cnt if deck else 0)],current_session_vars)
            redraw();return
        
        # ---- Final Command Execution Logic ----
        res_cmd = resolve_command_string(cmd_tpl, current_session_vars)
        main_p = res_cmd # This will be the command to execute or send, possibly transformed below

        is_at_p_final, at_n_p_final = False, False
        btn_cfg_p_final = None
        act_at_p_final = labels.get(active_device_key) if active_device_key is not None else None
        is_n_stg_p_final, ssh_stg_p_final, n_stg_p_final=False,"",""

        # M-flag transformation for non-@ buttons whose command is SSH
        if not dev_cb and is_mobile_ssh_cb and not current_button_force_local and main_p.lower().strip().startswith("ssh "):
            main_p = _transform_ssh_user_for_mobile(main_p)

        # Special handling for non-@, ! buttons (process monitor)
        if g_idx_cb is not None and '!' in orig_flags_cb_from_db and not '@' in orig_flags_cb_from_db and not lp and not current_button_force_local:
            cmd_for_process_mon = main_p # Already resolved, and M-transformed if it was a direct SSH M-button

            if not db_monitor_keyword:
                monitor_states[g_idx_cb] = 'PROCESS_NO_KW'
                if active_device_key is not None and labels.get(active_device_key):
                     run_cmd_in_terminal(cmd_for_process_mon, act_at_lbl=labels.get(active_device_key))
                else:
                     run_cmd_in_terminal(cmd_for_process_mon, force_local_execution=not cmd_for_process_mon.lower().startswith("ssh "))
                redraw(); return

            if active_device_key is None or not labels.get(active_device_key):
                monitor_states[g_idx_cb] = 'PROCESS_NO_AT'
                run_cmd_in_terminal(cmd_for_process_mon, force_local_execution=not cmd_for_process_mon.lower().startswith("ssh "))
            else:
                active_at_label_str = labels.get(active_device_key)
                active_at_cmd_template = cmds.get(active_device_key,"")
                resolved_active_at_cmd_monitor_base = resolve_command_string(active_at_cmd_template, current_session_vars)
                active_at_flags_raw = flags.get(active_device_key, "")
                _,_,_,_,_,_,active_at_is_mobile_for_monitor = parse_flags(active_at_flags_raw)

                if active_at_is_mobile_for_monitor and resolved_active_at_cmd_monitor_base.lower().strip().startswith("ssh "):
                     resolved_active_at_cmd_monitor_base = _transform_ssh_user_for_mobile(resolved_active_at_cmd_monitor_base)
                ssh_base_match = re.match(r"^(ssh\s+[^ ]+)", resolved_active_at_cmd_monitor_base)

                if not ssh_base_match:
                    monitor_states[g_idx_cb] = 'PROCESS_ERROR'
                    run_cmd_in_terminal(cmd_for_process_mon, act_at_lbl=active_at_label_str)
                else:
                    ssh_base_for_grep = ssh_base_match.group(1)
                    monitor_states[g_idx_cb] = 'PROCESS_INIT'
                    new_gen_id_proc = time.time(); monitor_generations[g_idx_cb] = new_gen_id_proc
                    if g_idx_cb in monitor_threads: monitor_threads.pop(g_idx_cb, None)
                    proc_thread = threading.Thread(target=monitor_remote_process, args=(g_idx_cb, ssh_base_for_grep, db_monitor_keyword, new_gen_id_proc), daemon=True)
                    monitor_threads[g_idx_cb] = proc_thread; proc_thread.start()
                    run_cmd_in_terminal(cmd_for_process_mon, act_at_lbl=active_at_label_str)
            redraw(); return
        
        # Handle non-@, M-flagged button that is NOT an SSH command itself, but an @-device IS active
        # This is the case: "When I'm in a root @ device window and press a M button, it should be opening a new mobile window"
        if not dev_cb and is_mobile_ssh_cb and not current_button_force_local and \
           not main_p.lower().strip().startswith("ssh ") and \
           active_device_key is not None and labels.get(active_device_key):
            
            active_at_original_cmd = cmds.get(active_device_key, "")
            active_at_resolved_cmd = resolve_command_string(active_at_original_cmd, current_session_vars)
            active_at_flags_str = flags.get(active_device_key, "")
            _, _, _, active_at_bg_color, _, _, active_at_is_mobile = parse_flags(active_at_flags_str)

            if not active_at_is_mobile and active_at_resolved_cmd.lower().strip().startswith("ssh "): # Active @ is NOT mobile
                print(f"[INFO] Plain M button '{lbl_str}' targeting active non-mobile @ device '{labels.get(active_device_key)}'. Creating new mobile session for command.")
                
                # 1. Construct the 'ssh mobile@host' command from the active @ device
                mobile_ssh_cmd_for_new_session = _transform_ssh_user_for_mobile(active_at_resolved_cmd)
                
                # 2. Define style for the new mobile window (based on original M button's style or a default)
                # For simplicity, let's use the M-button's own label for the new window, appended with "-Mobile"
                # and its original background color.
                new_mobile_window_label = f"{lbl_str}-Mobile" if lbl_str else f"MobileSession-{k_idx}"
                # Use current M button's background color for new mobile window
                _,_,_,m_button_bg,_,_,_ = parse_flags(flag_str)

                btn_cfg_for_new_mobile_session = {
                    "lbl": new_mobile_window_label,
                    "bg_hex": m_button_bg,
                    "text_color_name": text_color(m_button_bg)
                }

                # 3. This becomes an N-staged like operation
                is_n_stg_p_final = True
                ssh_stg_p_final = mobile_ssh_cmd_for_new_session # The 'ssh mobile@host' part
                n_stg_p_final = main_p # The original command of the M-button
                
                # Override other parameters for run_cmd_in_terminal for this specific case
                main_p = "" # Clear main_p as it's handled by staged execution
                btn_cfg_p_final = btn_cfg_for_new_mobile_session
                act_at_p_final = None # Not sending to an existing active @, but creating new
            else:
                # If active @ is already mobile, or some other edge case, send command as is to active @
                # (This part might need refinement if just sending main_p is not desired)
                 pass # Fall through to default execution for this M-button if active @ is already mobile or not SSH

        # N-button logic (non-@, non-K) using the potentially M-transformed main_p
        # This section should come AFTER the M-button specific logic above if that M-button was also N
        if not dev_cb and nw_cb and not current_button_force_local and not is_n_stg_p_final: # if not already handled by M->N-staged
            if act_at_p_final and active_device_key is not None:
                is_n_stg_p_final=True
                active_at_flags_str = flags.get(active_device_key,"")
                _,_,_,at_device_bg_hex_val,_,_,active_at_is_mobile = parse_flags(active_at_flags_str)
                btn_cfg_p_final={"lbl":lbl_str or "N-Staged Op",
                               "bg_hex": at_device_bg_hex_val,
                               "text_color_name":text_color(at_device_bg_hex_val)}
                
                at_cmd_tpl=cmds.get(active_device_key,"")
                if at_cmd_tpl:
                    res_at_cmd_for_n_staged=resolve_command_string(at_cmd_tpl,current_session_vars)
                    
                    if active_at_is_mobile and res_at_cmd_for_n_staged.lower().strip().startswith("ssh "):
                         res_at_cmd_for_n_staged = _transform_ssh_user_for_mobile(res_at_cmd_for_n_staged)
                         
                    m_n_staged_ssh_check = SSH_USER_HOST_CMD_PATTERN.match(res_at_cmd_for_n_staged)
                    if m_n_staged_ssh_check:
                        ssh_stg_p_final=res_at_cmd_for_n_staged
                        n_stg_p_final=main_p # main_p from N button, already M-transformed if it was M-SSH
                        main_p=""
                    else:
                        is_n_stg_p_final=False;
                        btn_cfg_p_final={'lbl':lbl_str or "N-Window", 'bg_hex':bg_cb, 'text_color_name':text_color(bg_cb), 'is_standalone_n_button':True}
                        # main_p already M-transformed if it was standalone N M SSH
                else:
                    is_n_stg_p_final=False;
                    btn_cfg_p_final={'lbl':lbl_str or "N-Window", 'bg_hex':bg_cb, 'text_color_name':text_color(bg_cb), 'is_standalone_n_button':True}
            else: # Standalone N button
                btn_cfg_p_final={"lbl":lbl_str or "N-Window","bg_hex":bg_cb,"text_color_name":text_color(bg_cb),"is_standalone_n_button":True}
        
        # Fallback for buttons that didn't get handled by specific logic above.
        if not cmd_tpl and not(k_idx in[load_key_idx,up_key_idx,down_key_idx]or dev_cb or (nw_cb and not current_button_force_local)):
            redraw(); return

        final_act_at_label_for_run_cmd = act_at_p_final if not current_button_force_local and not is_n_stg_p_final else None
        
        run_cmd_in_terminal(main_p, is_at_act=is_at_p_final, at_has_n=at_n_p_final,
                            btn_style_cfg=btn_cfg_p_final,
                            act_at_lbl=final_act_at_label_for_run_cmd,
                            is_n_staged=is_n_stg_p_final,
                            ssh_staged=ssh_stg_p_final,
                            n_staged=n_stg_p_final,
                            force_local_execution=current_button_force_local)
        redraw()

    deck.set_key_callback(callback)
    redraw()

    print("[INFO] Stream Deck initialized. Listening for key presses...")
    try:
        while True:
            flash_driver = False
            if numeric_mode and long_press_numeric_active: flash_driver=True
            else:
                for k_loop in range(cnt if deck else 0):
                    g_idx_loop = key_to_global_item_idx_map.get(k_loop)
                    if g_idx_loop is not None and g_idx_loop < len(items):
                        mon_state, item_flgs = monitor_states.get(g_idx_loop), items[g_idx_loop][2]
                        if mon_state=='BROKEN' and '!'in item_flgs and '@'in item_flgs: flash_driver=True;break
                        if mon_state=='connected' and '!'in item_flgs and '@'in item_flgs: flash_driver=True;break
                        if mon_state=='PROCESS_BROKEN' and '!' in item_flgs and not '@' in item_flgs: flash_driver=True; break
            if flash_driver: flash_state = not flash_state
            elif flash_state: flash_state=False
            redraw(); time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt: print("\n[INFO] KeyboardInterrupt: Exiting...")
    except Exception as e: print(f"[FATAL] Main loop exception: {e}"); import traceback; traceback.print_exc()
    finally:
        print("[INFO] Cleaning up threads & closing Stream Deck...")
        for t_id in list(monitor_threads.keys()):
            if t_id in monitor_threads:
                monitor_generations[t_id] = None
                del monitor_threads[t_id]
        if monitor_threads: time.sleep(0.5)
        if deck:
            try:
                deck.reset()
                deck.close()
            except Exception as e_cl:
                print(f"[ERROR] Deck close: {e_cl}")
        print("[INFO] Exited.")



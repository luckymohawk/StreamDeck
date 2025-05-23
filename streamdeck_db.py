#!/usr/bin/env python3
import sqlite3
import subprocess
import sys
import os
import re
import json
from pathlib import Path
from math import ceil

# === Application Directories & Files (Needed for default DB path) ===
APP_DIR = Path.home() / "Library" / "StreamDeckDriver"

# === Regex Patterns (Centralized) ===
VAR_PLACEHOLDER_PATTERN = re.compile(r"(\{\{)([^:}]+)([:]?)([^}]*)?(\}\})")
CLEAN_VAR_NAME_EXPECTED_FORMAT = re.compile(r"^[A-Z][A-Z0-9_]*$")
INVALID_CHARS_IN_NAME_REGEX = re.compile(r"[\s\-.!?,;:(){}\[\]<>+*/%='\"`~@$&|]+")
LEADING_INVALID_CHARS_REGEX = re.compile(r"^[^A-Z_]")

# === Helper function to clean AppleScript templates ===
def clean_applescript_template(template_string: str) -> str:
    """Strips trailing whitespace from each line and leading/trailing newlines from the block."""
    return "\n".join([line.rstrip() for line in template_string.strip().splitlines()])

def sanitize_var_name(original_name_part: str) -> str:
    s_name = original_name_part.strip()
    s_name = INVALID_CHARS_IN_NAME_REGEX.sub("_", s_name)
    s_name = s_name.upper()
    s_name = re.sub(r"_+", "_", s_name)
    s_name = s_name.strip("_")
    if not s_name: return "VAR_EMPTY"
    if LEADING_INVALID_CHARS_REGEX.match(s_name) and not s_name.startswith("V_"):
        s_name = "V_" + s_name
        s_name = re.sub(r"_+", "_", s_name); s_name = s_name.strip("_")
        if not s_name: return "V_EMPTY"
    if not CLEAN_VAR_NAME_EXPECTED_FORMAT.match(s_name):
        print(f"    --> Sanitized name '{s_name}' still does not perfectly match CLEAN_VAR_NAME_EXPECTED_FORMAT.")
        if s_name == "V_": s_name = "VAR_V_ONLY"
    return s_name

def validate_command_placeholders(command_str: str) -> str:
    offset = 0
    while True:
        match = VAR_PLACEHOLDER_PATTERN.search(command_str, offset)
        if not match: break
        original_name_part = match.group(2).strip()
        colon_part = match.group(3)
        default_value_part = match.group(4)

        if not original_name_part: return f"ERR: Empty var name in '{match.group(0)}'"
        
        if not CLEAN_VAR_NAME_EXPECTED_FORMAT.match(original_name_part):
            sanitized_for_check = sanitize_var_name(original_name_part)
            if CLEAN_VAR_NAME_EXPECTED_FORMAT.match(sanitized_for_check):
                 return f"WARN: Var '{original_name_part}' needs sanitization to '{sanitized_for_check}' in '{match.group(0)}'"
            return f"ERR: Invalid var name format '{original_name_part}' in '{match.group(0)}'"
        
        if colon_part and default_value_part is None:
            return f"ERR: Var '{original_name_part}' has colon but no default value in '{match.group(0)}'"
            
        offset = match.end(0)
    return "OK"

def correct_command_string_for_sqlite(original_cmd_str: str):
    corrected_cmd = original_cmd_str
    was_corrected_flag = False
    
    def replace_and_sanitize_match(match_obj):
        nonlocal was_corrected_flag
        opening_braces, var_name_original_raw, colon_part, default_val_part, closing_braces = match_obj.groups()
        
        var_name_stripped = var_name_original_raw.strip()
        sanitized_name = sanitize_var_name(var_name_stripped)
        
        if var_name_stripped != sanitized_name:
            was_corrected_flag = True
            
        default_val_part = default_val_part if default_val_part is not None else ""
        
        return f"{opening_braces}{sanitized_name}{colon_part}{default_val_part}{closing_braces}"

    corrected_cmd = VAR_PLACEHOLDER_PATTERN.sub(replace_and_sanitize_match, original_cmd_str)
    return corrected_cmd, was_corrected_flag


def run_applescript(script_text: str) -> str:
    try:
        p = subprocess.Popen(['osascript', '-s', 's', '-'], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = p.communicate(script_text)
        
        is_potential_error = (err and ("error" in err.lower() or "(-" in err)) or p.returncode != 0

        if is_potential_error:
            is_actual_error_for_log = p.returncode != 0 or \
                                   any(err_indicator in err.lower() for err_indicator in ["syntax error", "error:", "(-"]) or \
                                   "execution error" in err.lower()
            if is_actual_error_for_log: # Only print full script if a real error seems likely
                print(f"--- AppleScript Start (Error Detected by Python) ---\n{script_text}\n--- AppleScript End ---", file=sys.stderr)

        if err and ("error" in err.lower() or "(-" in err):
            is_actual_error = p.returncode != 0 or \
                              any(err_indicator in err.lower() for err_indicator in ["syntax error", "error:", "(-"]) or \
                              "execution error" in err.lower()
            if is_actual_error:
                print(f"AppleScript execution produced stderr (potential error):\n{err.strip()}", file=sys.stderr)
                if p.returncode != 0 or "syntax error" in err.lower() or "(-2741)" in err or "(-1712)" in err :
                    raise RuntimeError(f"AppleScript execution indicated an error: {err.strip()} (RC: {p.returncode})")
        
        if p.returncode != 0 and not ("error" in (err or "").lower()) :
             print(f"AppleScript Error (RC {p.returncode}):\n{(err or '').strip()}", file=sys.stderr)
             raise RuntimeError(f"AppleScript execution failed with RC {p.returncode}: {(err or '').strip()}")

        return out.strip()
    except FileNotFoundError:
        print("Error: 'osascript' command not found. Please ensure it's in your PATH.", file=sys.stderr)
        sys.exit(1)

def run_applescript_for_batched_writeback(list_of_tuples_for_as: list, column_to_write: str):
    """
    Generates and executes an AppleScript to write data to Numbers.
    Each item in list_of_tuples_for_as is a (row_idx_str, val_str) tuple.
    The AppleScript will execute a series of 'set value' commands.
    """
    applescript_set_value_commands_list = []
    for r_idx_str, val_str in list_of_tuples_for_as:
        escaped_val = json.dumps(val_str)
        # Create a command to set the cell value for each item
        # Ensure row index is treated as a number in AppleScript
        command = f'set value of cell {r_idx_str} of column "{column_to_write}" to {escaped_val}'
        applescript_set_value_commands_list.append(command)
    
    # Join all individual set value commands into one block, separated by newlines
    all_set_commands_string = "\n                        ".join(applescript_set_value_commands_list)

    final_script = clean_applescript_template(f"""
    tell application "Numbers"
        activate
        tell front document
            set target_sheet to missing value
            try
                repeat with s_item in sheets
                    if name of s_item is "Streamdeck" then
                        set target_sheet to s_item
                        exit repeat
                    end if
                end repeat
            on error
                log "Error accessing sheets for writeback."
                return "Error: Could not access sheets for writeback."
            end try

            if target_sheet is missing value then
                try
                    set target_sheet to active sheet
                on error
                    log "Error setting target_sheet to active sheet for writeback."
                    return "Error: Could not set active sheet for writeback."
                end try
            end if
            
            tell target_sheet to tell table 1 of it
                -- Conditional header for validation status column (Column K)
                if "{column_to_write}" is "K" then
                    try
                        set current_header to value of cell 1 of column "K"
                        if current_header is not "Var Format Check" then
                            set value of cell 1 of column "K" to "Var Format Check"
                        end if
                    on error 
                        set value of cell 1 of column "K" to "Var Format Check"
                    end try
                end if
                
                try
                    {all_set_commands_string}
                on error errMsg
                    log "Error during batch cell update for Col {column_to_write}: " & errMsg
                    -- Optionally re-raise or handle partial success/failure
                end try
            end tell
        end tell
    end tell
    return "Writeback to Col {column_to_write} attempted."
    """)
    
    return run_applescript(final_script)


FETCH_APPLESCRIPT_TEMPLATE = clean_applescript_template("""
tell application "Numbers"
    activate
    tell front document
        set target_sheet to missing value
        try
            repeat with s_item in sheets
                if name of s_item is "Streamdeck" then
                    set target_sheet to s_item
                    exit repeat
                end if
            end repeat
        on error
            return "Error: Could not access sheets. Ensure Numbers document is open."
        end try

        if target_sheet is missing value then
            try
                display dialog "Sheet 'Streamdeck' not found. Using active sheet." with icon note buttons {"OK"} default button "OK" giving up after 3
            end try
            set target_sheet to active sheet
        end if

        tell target_sheet
            set main_table to table 1
            set RS_char to ASCII character 30
            set US_char to ASCII character 31
            set output_data to ""
            set num_rows to 0
            try
                set num_rows to (count of rows of main_table)
            on error errmess
                return "Error: Could not count rows in table: " & errmess
            end try

            if num_rows < 2 then return "" 

            repeat with r_idx from 2 to num_rows 
                set current_label to ""
                set original_command to ""
                set current_flags to ""
                try
                    set current_label to (value of cell r_idx of column "A" of main_table) as text
                end try
                try
                    set original_command to (value of cell r_idx of column "D" of main_table) as text
                end try
                try
                    set current_flags to (value of cell r_idx of column "C" of main_table) as text
                end try
                
                set output_data to output_data & r_idx & US_char & current_label & US_char & original_command & US_char & current_flags & RS_char
            end repeat
            return output_data
        end tell
    end tell
end tell
""")

def create_database_from_numbers(db_path_param='streamdeck.db'):
    db_dir = os.path.dirname(db_path_param)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = sqlite3.connect(db_path_param)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS streamdeck")
    c.execute("CREATE TABLE streamdeck (id INTEGER PRIMARY KEY, label TEXT, command TEXT, newwin TEXT)")
    conn.commit()
    
    print("Fetching data from Numbers...")
    raw_data_from_numbers = run_applescript(FETCH_APPLESCRIPT_TEMPLATE)

    if raw_data_from_numbers.startswith("Error:"):
        print(raw_data_from_numbers, file=sys.stderr)
        conn.close()
        return

    rows_data_cleaned = []
    for row_str_raw in raw_data_from_numbers.split(chr(30)):
        cleaned_row_str = row_str_raw.strip()
        if cleaned_row_str and cleaned_row_str != '"' and cleaned_row_str != "'":
            rows_data_cleaned.append(cleaned_row_str)
    
    entries_for_sqlite = []
    commands_to_write_back_if_corrected = []
    validation_statuses_for_numbers = []

    print("Validating and processing commands from Numbers data...")
    for row_entry_str in rows_data_cleaned:
        parts = row_entry_str.split(chr(31))
        if len(parts) < 4:
            print(f"  Skipping malformed row (expected 4+ parts, got {len(parts)}): '{row_entry_str}'")
            continue
        
        row_idx_str = parts[0].strip().strip('"').strip("'")
        label_val = parts[1]
        original_cmd_val = parts[2]
        flags_val = parts[3].strip()

        if not row_idx_str.isdigit():
            print(f"  Skipping row with non-numeric index: '{row_idx_str}' from entry '{row_entry_str}'")
            continue
        
        validation_result = validate_command_placeholders(original_cmd_val)
        validation_statuses_for_numbers.append((row_idx_str, validation_result))
        if validation_result != "OK":
            print(f"    Validation for row {row_idx_str} (Label: '{label_val}', Cmd: '{original_cmd_val}'): {validation_result}")
        
        cmd_for_sqlite, was_cmd_structurally_corrected = correct_command_string_for_sqlite(original_cmd_val)
        if was_cmd_structurally_corrected:
            print(f"    Sanitized command for row {row_idx_str} (Label: '{label_val}') for DB. Original: '{original_cmd_val}', Sanitized: '{cmd_for_sqlite}'")
            commands_to_write_back_if_corrected.append((row_idx_str, cmd_for_sqlite))

        entries_for_sqlite.append((label_val, cmd_for_sqlite, flags_val))

    if commands_to_write_back_if_corrected:
        print(f"Writing {len(commands_to_write_back_if_corrected)} structurally corrected commands back to Numbers (Col D)...")
        try:
            run_applescript_for_batched_writeback(commands_to_write_back_if_corrected, "D")
            print("  Successfully attempted to write structurally corrected commands to Numbers Col D.")
        except Exception as e_corr_write:
            print(f"  Error writing corrected commands to Numbers Col D: {e_corr_write}", file=sys.stderr)

    if validation_statuses_for_numbers:
        print(f"Writing {len(validation_statuses_for_numbers)} validation statuses to Numbers (Col K)...")
        try:
            run_applescript_for_batched_writeback(validation_statuses_for_numbers, "K")
            print("  Successfully attempted to write validation statuses to Numbers column K.")
        except Exception as e_val_write_k:
            print(f"  Error writing validation statuses data to Numbers: {e_val_write_k}", file=sys.stderr)

    if entries_for_sqlite:
        c.executemany("INSERT INTO streamdeck (label, command, newwin) VALUES (?, ?, ?)", entries_for_sqlite)
        conn.commit()
        print(f"✅ Database '{db_path_param}' updated/created with {len(entries_for_sqlite)} rows.")
    else:
        print("No entries processed for SQLite database.")

    conn.close()

if __name__ == "__main__":
    db_file_path = sys.argv[1] if len(sys.argv) > 1 else str(APP_DIR / "streamdeck.db")
    print(f"Target database path: {db_file_path}")
    try:
        create_database_from_numbers(db_file_path)
    except Exception as e_main:
        print(f"An error occurred during database creation: {e_main}", file=sys.stderr)

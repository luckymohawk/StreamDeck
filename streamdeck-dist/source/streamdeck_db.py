#!/usr/bin/env python3
# This script fetches data from an Apple Numbers spreadsheet
# and builds an SQLite database for the Stream Deck driver.
import sqlite3
import subprocess
import sys
import os
import re
import json
from pathlib import Path
from math import ceil

# --- IMPORTS for platform-specific directories ---
from platformdirs import user_data_dir

# === Application Directories & Files (Corrected for Bundling) ===
# Use platformdirs to get the standard, safe location for user data.
APP_NAME = "StreamdeckCommander"
APP_AUTHOR = "LuckyMcNulty"
APP_DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))


# === Regex Patterns ===
VAR_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^:}]+)(:([^}]*))?\}\}")

def clean_applescript_template(template_string: str) -> str:
    """Strips extraneous whitespace from an AppleScript string."""
    return "\n".join([line.rstrip() for line in template_string.strip().splitlines()])

def validate_command_placeholders(command_str: str) -> str:
    """Validates the format of placeholders in a command string."""
    return "OK"

def correct_command_string_for_sqlite(original_cmd_str: str):
    """Prepares a command string for database insertion."""
    return original_cmd_str, False


def run_applescript(script_text: str) -> str:
    """Executes an AppleScript and returns its standard output."""
    try:
        p = subprocess.Popen(['osascript', '-s', 's', '-'], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = p.communicate(script_text)
        
        is_potential_error = (err and ("error" in err.lower() or "(-" in err)) or p.returncode != 0

        if is_potential_error:
            is_actual_error_for_log = p.returncode != 0 or \
                                   any(err_indicator in err.lower() for err_indicator in ["syntax error", "error:", "(-"]) or \
                                   "execution error" in err.lower()
            if is_actual_error_for_log:
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

# AppleScript to fetch configuration data from the "Streamdeck" sheet in Numbers.
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
                set current_flags to ""
                set original_command to ""
                set monitor_keyword to ""
                
                try
                    set current_label to (value of cell r_idx of column "A" of main_table) as text
                end try
                try
                    set current_flags to (value of cell r_idx of column "C" of main_table) as text
                end try
                try
                    set original_command to (value of cell r_idx of column "D" of main_table) as text
                end try
                try
                    set monitor_keyword to (value of cell r_idx of column "K" of main_table) as text
                end try
                
                set output_data to output_data & r_idx & US_char & current_label & US_char & original_command & US_char & current_flags & US_char & monitor_keyword & RS_char
            end repeat
            return output_data
        end tell
    end tell
end tell
""")

def create_database_from_numbers(db_path_param='streamdeck.db'):
    # Use Path object for robust path handling
    db_path_obj = Path(db_path_param)
    db_dir = db_path_obj.parent
    
    if db_dir and not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)

    if db_path_obj.exists():
        try:
            os.remove(db_path_obj)
            print(f"Removed existing database '{db_path_obj}' for fresh build.")
        except OSError as e:
            print(f"Error removing existing database '{db_path_obj}': {e}", file=sys.stderr)
            
    conn = sqlite3.connect(db_path_obj)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS streamdeck")
    c.execute("CREATE TABLE streamdeck (id INTEGER PRIMARY KEY, label TEXT, command TEXT, flags TEXT, monitor_keyword TEXT)")
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

    print("Processing commands from Numbers data for SQLite...")
    for row_entry_str in rows_data_cleaned:
        parts = row_entry_str.split(chr(31))
        if len(parts) < 5:
            print(f"  Skipping malformed row (expected 5+ parts, got {len(parts)}): '{row_entry_str}'")
            continue
        
        row_idx_str = parts[0].strip().strip('"').strip("'")
        label_val = parts[1]
        original_cmd_val = parts[2]
        flags_val = parts[3]
        monitor_keyword_val = parts[4]

        if not row_idx_str.isdigit():
            print(f"  Skipping row with non-numeric index: '{row_idx_str}' from entry '{row_entry_str}'")
            continue
        
        cmd_for_sqlite, _ = correct_command_string_for_sqlite(original_cmd_val)
        
        label_db = "" if label_val.lower() == "missing value" else label_val
        flags_db = "" if flags_val.lower() == "missing value" else flags_val.strip()
        monitor_keyword_db = "" if monitor_keyword_val.lower() == "missing value" else monitor_keyword_val.strip()

        entries_for_sqlite.append((label_db, cmd_for_sqlite, flags_db, monitor_keyword_db))

    if entries_for_sqlite:
        c.executemany("INSERT INTO streamdeck (label, command, flags, monitor_keyword) VALUES (?, ?, ?, ?)", entries_for_sqlite)
        conn.commit()
        print(f"✅ Database '{db_path_obj}' updated/created with {len(entries_for_sqlite)} rows.")
    else:
        print("No entries processed for SQLite database.")

    conn.close()

if __name__ == "__main__":
    # Ensure the standard application data directory exists.
    if not APP_DATA_DIR.exists():
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        
    # Default to the correct data directory, but allow override from command line.
    db_file_path = sys.argv[1] if len(sys.argv) > 1 else str(APP_DATA_DIR / "streamdeck.db")
    print(f"Target database path (will be rebuilt): {db_file_path}")
    try:
        create_database_from_numbers(db_file_path)
    except Exception as e_main:
        print(f"An error occurred during database creation: {e_main}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

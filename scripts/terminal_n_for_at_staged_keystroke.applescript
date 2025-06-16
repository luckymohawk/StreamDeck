-- Purpose: Handles M-flagged buttons ($ or M) when a non-mobile @-device is active.
-- NEW: It now intelligently finds an existing, correctly named window or creates one if it's missing.
-- 1. Search for a window with the custom title.
-- 2. If FOUND: Activate it and send only the final command (assumes it's already at a prompt).
-- 3. If NOT FOUND: Create a new window, style it, run the SSH command, wait, then run the final command.
-- Placeholders:
-- {{window_custom_title}} (e.g., "REC-Mobile")
-- {{ssh_command_to_keystroke}} (e.g., "ssh mobile@luckyiphone")
-- {{actual_n_command_to_keystroke}} (The button's specific command)
-- {{aps_bg_color}}, {{aps_text_color}} (For styling a new window)

tell application "Terminal"
	activate
	set target_window to missing value
	set window_was_found to false
	
	-- 1. SEARCH for an existing window with the exact custom title.
	try
		repeat with w in windows
			if custom title of w is "{{window_custom_title}}" then
				set target_window to w
				set window_was_found to true
				exit repeat
			end if
		end repeat
	on error
		-- Ignore errors, window_was_found will remain false.
	end try
	
	-- 2. IF FOUND: Activate it and send the command.
	if window_was_found then
		log "AS (Staged): Found existing window '{{window_custom_title}}'. Activating and sending command."
		
		tell target_window
			set index to 1
			activate
		end tell
		delay 0.2
		
		-- Keystroke ONLY the final command.
		tell application "System Events" to tell process "Terminal"
			set frontmost to true
			if "{{actual_n_command_to_keystroke}}" is not "" then
				keystroke "{{actual_n_command_to_keystroke}}"
				keystroke return
			end if
		end tell
		
	-- 3. IF NOT FOUND: Create a new window using the original logic.
	else
		log "AS (Staged): Window '{{window_custom_title}}' not found. Creating and staging new session."
		
		try
			do script ""
		on error err_do_script_empty
			return "AS_ERROR: N-for-@ failed initial 'do script \"\"'."
		end try
		delay 0.5
		
		set new_window to front window
		tell new_window
			set index to 1
			set background color to {{aps_bg_color}}
			set normal text color to {{aps_text_color}}
			set cursor color to {{aps_text_color}}
			set bold text color to {{aps_text_color}}
			set custom title to "{{window_custom_title}}"
		end tell
		
		-- Stage 1: Keystroke the SSH command.
		if "{{ssh_command_to_keystroke}}" is not "" then
			tell application "System Events" to tell process "Terminal"
				set frontmost to true
				delay 0.2
				keystroke "{{ssh_command_to_keystroke}}"
				keystroke return
			end tell
		end if
		
		-- Wait for SSH to connect.
		delay 1.5
		
		-- Stage 2: Keystroke the final command.
		if "{{actual_n_command_to_keystroke}}" is not "" then
			tell application "System Events" to tell process "Terminal"
				set frontmost to true
				delay 0.2
				keystroke "{{actual_n_command_to_keystroke}}"
				keystroke return
			end tell
		end if
	end if
end tell
-- Purpose: Sends a command to an already existing, active @-device window using do script.
-- Placeholders: {{safe_target_title}}, {{final_script_payload_for_do_script}}, {{main_command_raw_for_emptiness_check}}
-- Note: {{command_to_type_literally_content}} is also passed but less critical with 'do script' focus.

tell application "Terminal"
	activate
	set found_window_ref to missing value
	set window_was_found to false
	try
		repeat with w in windows
			if custom title of w is "{{safe_target_title}}" then
				set found_window_ref to w
				set window_was_found to true
				exit repeat
			end if
		end repeat
	on error find_err
		log "AS: Error finding existing window '{{safe_target_title}}' for command: " & find_err
	end try

	if not window_was_found then
		log "AS: Target window '{{safe_target_title}}' not found. Running command in new default window."
		if "{{main_command_raw_for_emptiness_check}}" is not "" then
			do script "{{final_script_payload_for_do_script}}"
		else
			log "AS: No command payload to execute in new default window (window not found branch)."
		end if
		return
	end if

	-- Window was found
	log "AS: Found window '{{safe_target_title}}' (ID: " & (id of found_window_ref as text) & "). Using 'do script'."
	
	try
		tell found_window_ref
			activate
			set index to 1 -- Bring to front
			if "{{main_command_raw_for_emptiness_check}}" is not "" then
				if (count of tabs) > 0 then
					log "AS: Executing in selected tab of '{{safe_target_title}}': {{final_script_payload_for_do_script}}"
					do script "{{final_script_payload_for_do_script}}" in selected tab
				else
					log "AS: No tabs in '{{safe_target_title}}', trying 'do script' in window context. Script: {{final_script_payload_for_do_script}}"
					do script "{{final_script_payload_for_do_script}}"
				end if
			else
				log "AS: No command payload to execute in '{{safe_target_title}}', but activating window."
			end if
		end tell
	on error do_script_err
		log "AS: Error during 'do script' attempt for '{{safe_target_title}}': " & do_script_err & ". Fallback: trying 'do script' in a new window if payload exists."
		if "{{main_command_raw_for_emptiness_check}}" is not "" then
			tell application "Terminal" -- Ensure context for fallback
				do script "{{final_script_payload_for_do_script}}"
			end tell
		end if
	end try
end tell
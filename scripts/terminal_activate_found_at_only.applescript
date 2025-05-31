-- START OF FILE: terminal_activate_found_at_only.txt (from your initial prompt)
-- Purpose: Handles regular @ buttons (not @N).
-- If window found (and not forced new): activates it.
-- If not found (or forced new): creates new, styles, and runs command.
-- Placeholders: {{escaped_device_label}}, {{final_script_payload_for_do_script}}, {{aps_bg_color}}, {{aps_text_color}}, {{force_new_window}}

tell application "Terminal"
	activate
	set target_window_ref to missing value 
	set window_was_found to false
	set local_force_new to (("{{force_new_window}}" as text) is "true")

	if local_force_new then
		log "AS: @-Button '{{escaped_device_label}}' - new window FORCED."
		set window_was_found to false 
	else
		try
			repeat with w_obj in windows
				if custom title of w_obj is "{{escaped_device_label}}" then
					set target_window_ref to w_obj 
					set window_was_found to true
					exit repeat
				end if
			end repeat
		on error find_err
			log "AS: Error finding existing window for @-Button '{{escaped_device_label}}': " & find_err
			set window_was_found to false 
		end try
	end if

	if window_was_found then
		log "AS: Window '{{escaped_device_label}}' was found. Activating only. Target ID: " & (id of target_window_ref as text)
		tell target_window_ref
			activate
			set index to 1
		end tell
		delay 0.1 
	else
		if local_force_new then
			log "AS: Proceeding with forced new window creation for '{{escaped_device_label}}'."
		else
			log "AS: @-Button '{{escaped_device_label}}' truly not found, proceeding to create new and execute command."
		end if
		
		set new_terminal_entity to missing value
		try
			set new_terminal_entity to do script "{{final_script_payload_for_do_script}}"
		on error errMsg_new
			log "AS: Error in @-only 'do script' for new window: " & errMsg_new
		end try
		delay 0.3 
		set creation_target_window to missing value 
		try
			if new_terminal_entity is not missing value then
				set new_entity_class to class of new_terminal_entity
				if new_entity_class is tab then
					try
						set creation_target_window to window of new_terminal_entity
					on error
						log "AS: Could not get window of tab directly for @-only new, using front window."
						if (count windows) > 0 then set creation_target_window to front window
					end try
				else if new_entity_class is window then
					set creation_target_window to new_terminal_entity
				else
					log "AS: Unexpected class for @-only new_terminal_entity: " & (new_entity_class as text)
					if (count windows) > 0 then set creation_target_window to front window
				end if
			else if (count of windows) > 0 then
				set creation_target_window to front window
				log "AS: @-only: 'do script' returned missing value or errored for new, using front window."
			end if
		on error errMsg_class_new
			log "AS: Error in @-only (new_terminal_entity class check): " & errMsg_class_new
			if (count windows) > 0 then set creation_target_window to front window
		end try
		
		if creation_target_window is not missing value then
			log "AS: Styling newly created window for '{{escaped_device_label}}', ID: " & (id of creation_target_window as text)
			tell creation_target_window
				set custom title to "{{escaped_device_label}}"
				set background color to {{aps_bg_color}}
				set normal text color to {{aps_text_color}}
				set cursor color to {{aps_text_color}}
				set bold text color to {{aps_text_color}}
				set index to 1
			end tell
		else
			log "AS: @-only: creation_target_window could not be determined for styling new window."
		end if
	end if
end tell
-- END OF FILE: terminal_activate_found_at_only.txt
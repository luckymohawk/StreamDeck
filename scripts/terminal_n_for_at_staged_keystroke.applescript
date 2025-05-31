-- START OF FILE: terminal_n_for_at_staged_keystroke.txt
-- Purpose: Handles N-button when @-device is active.
-- 1. Creates new window, styled like the active @-device.
-- 2. Keystrokes SSH command of @-device.
-- 3. Delays.
-- 4. Keystrokes N-button's actual command.
-- Placeholders:
-- {{window_custom_title}} (from @-device label, for new window title)
-- {{aps_bg_color}} (from @-device style)
-- {{aps_text_color}} (from @-device style)
-- {{ssh_command_to_keystroke}} (e.g., "ssh root@luckyiphone")
-- {{actual_n_command_to_keystroke}} (e.g., "while true; do date ...")

tell application "Terminal"
	activate
	-- Create a new window. "do script """ should make this new window frontmost.
	try
		do script "" 
	on error err_do_script_empty
		log "AS: N-for-@ (staged): Critical error on initial 'do script \"\"': " & err_do_script_empty
		return "AS_ERROR: N-for-@ failed initial 'do script \"\"'."
	end try
	
	delay 0.5 -- Allow window to fully form and become front.

	set target_window to missing value
	if (count windows) > 0 then
		set target_window to front window -- Assume the new window is now front
	end if

	if target_window is missing value then
		log "AS: N-for-@ (staged): Could not determine target window after 'do script \"\"'."
		return "AS_ERROR: N-for-@ could not get target window"
	end if

	log "AS: N-for-@ (staged): Styling new window (ID: " & id of target_window & ") as '{{window_custom_title}}'."
	tell target_window
		set index to 1 -- Ensure it is absolutely front.
		delay 0.1
		set background color to {{aps_bg_color}}
		set normal text color to {{aps_text_color}}
		set cursor color to {{aps_text_color}}
		set bold text color to {{aps_text_color}}
		delay 0.2
		set custom title to "{{window_custom_title}}"
		delay 0.1
		set custom title to "{{window_custom_title}}" -- Set twice for robustness
	end tell
	
	-- Stage 1: Keystroke SSH command into the new, styled, frontmost window
	log "AS: N-for-@ (staged): Keystroking SSH command: {{ssh_command_to_keystroke}}"
	try
		tell application "System Events"
			tell process "Terminal" 
				if not frontmost then
					log "AS: N-for-@ (staged): Terminal not frontmost before SSH keystroke, activating."
					tell application "Terminal" to activate
					delay 0.3
				end if
				keystroke "{{ssh_command_to_keystroke}}"
				delay 0.1
				keystroke return
			end tell
		end tell
	on error err_ssh_keystroke
		log "AS: N-for-@ (staged): Error keystroking SSH command: " & err_ssh_keystroke
		return "AS_ERROR: N-for-@ SSH keystroke failed"
	end try
	
	log "AS: N-for-@ (staged): Delaying for SSH connection..."
	delay 3.0 -- CRITICAL: Allow time for SSH connection to establish.

	-- Stage 2: Keystroke the N-button's actual command
	if "{{actual_n_command_to_keystroke}}" is not "" then
		log "AS: N-for-@ (staged): Keystroking N-command: {{actual_n_command_to_keystroke}}"
		try
			tell application "System Events"
				tell process "Terminal"
                    if not frontmost then
                        log "AS: N-for-@ (staged): Terminal not frontmost before N-CMD keystroke, activating."
                        tell application "Terminal" to activate
                        delay 0.3
                    end if
					keystroke "{{actual_n_command_to_keystroke}}"
					delay 0.1
					keystroke return
				end tell
			end tell
		on error err_n_cmd_keystroke
			log "AS: N-for-@ (staged): Error keystroking N-command: " & err_n_cmd_keystroke
		end try
	else
		log "AS: N-for-@ (staged): No N-command to keystroke after SSH."
	end if
	
end tell
-- END OF FILE: terminal_n_for_at_staged_keystroke.txt
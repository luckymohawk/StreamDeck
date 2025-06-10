-- Purpose: Creates a window, runs an SSH command, then runs a second command inside it,
-- takes a snapshot, and returns the window's ID and snapshot data.
-- Placeholders:
-- {{window_custom_title}}
-- {{aps_bg_color}}, {{aps_text_color}}
-- {{ssh_command_to_keystroke}}
-- {{actual_command_to_keystroke}}

set saved_clipboard to the clipboard

tell application "Terminal"
	activate
	try
		do script ""
	on error
		return "AS_ERROR: Could not create new window."
	end try
	delay 0.5
	
	set target_window to front window
	tell target_window
		set index to 1
		set background color to {{aps_bg_color}}
		set normal text color to {{aps_text_color}}
		set custom title to "{{window_custom_title}}"
	end tell
	
	-- Stage 1: Keystroke the SSH command from the @-device
	if "{{ssh_command_to_keystroke}}" is not "" then
		try
			tell application "System Events" to tell process "Terminal"
				set frontmost to true
				delay 0.1
				keystroke "{{ssh_command_to_keystroke}}"
				keystroke return
			end tell
		on error
			set the clipboard to saved_clipboard
			return "AS_ERROR: Failed to keystroke SSH command."
		end try
	end if
	
	-- Wait for SSH to connect.
	delay 3
	
	-- Stage 2: Keystroke the actual command from the ?-button
	if "{{actual_command_to_keystroke}}" is not "" then
		try
			tell application "System Events" to tell process "Terminal"
				set frontmost to true
				delay 0.1
				keystroke "{{actual_command_to_keystroke}}"
				keystroke return
			end tell
		on error
			set the clipboard to saved_clipboard
			return "AS_ERROR: Failed to keystroke actual command."
		end try
	end if

	-- Wait for the second command to settle
	delay 2
	
	-- Take the "before" snapshot using the clipboard method
	tell application "System Events" to tell process "Terminal"
		set frontmost to true
		keystroke "a" using command down
		delay 0.1
		keystroke "c" using command down
		delay 0.1
	end tell
	set initial_content to the clipboard
	
	set the clipboard to saved_clipboard
	
	return (id of target_window as text) & "::::" & initial_content
end tell
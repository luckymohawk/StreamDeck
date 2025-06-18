
set saved_clipboard to the clipboard

tell application "Terminal"
	activate
	set new_terminal_entity to missing value
	try
		set new_terminal_entity to do script "{{initial_command_to_run}}"
	on error
		set the clipboard to saved_clipboard
		return "AS_ERROR: Could not create new window for snapshot."
	end try
	
	delay 0.5
	
	set target_window to front window
	tell target_window
		set index to 1
		set background color to {{aps_bg_color}}
		set normal text color to {{aps_text_color}}
		set custom title to "{{window_custom_title}}"
	end tell
	
	-- Wait for the command to settle
	delay 0.5
	
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
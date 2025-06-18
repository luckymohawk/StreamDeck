tell application "Terminal"
	activate
	
	-- Create a new window with a blank command to ensure immediate window creation
	set newWindow to do script ""
	
	-- Explicitly name the window immediately for easy AppleScript access
	set custom title of newWindow to "{{window_custom_title}}"
	
	-- Set the window's background color clearly
	set background color of newWindow to {{aps_bg_color}}
	
	-- Set the window's normal text color clearly
	set normal text color of newWindow to {{aps_text_color}}
	
	delay 0.2
	
	-- Run your actual intended command clearly in the window
	do script "{{final_script_payload_for_do_script}}" in newWindow
end tell

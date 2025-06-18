-- Purpose: Gets window content via clipboard and then returns focus to the original app.
-- Placeholders: {{window_id}}

-- Remember what app is currently active.
tell application "System Events" to set front_app_name to name of first application process whose frontmost is true

set saved_clipboard to the clipboard
set output to ""

tell application "Terminal"
	if not running then
		set the clipboard to saved_clipboard
		return "WINDOW_GONE"
	end if
	
	try
		set target_window to first window whose id is {{window_id}}
		-- No need to bring the window to the front with set index,
		-- as activating the app and sending keystrokes will handle it.
	on error
		set the clipboard to saved_clipboard
		return "WINDOW_GONE"
	end try
end tell

-- Activate Terminal, do the copy, and get the content.
tell application "System Events"
	tell process "Terminal"
		set frontmost to true
		delay 0.1 -- short delay for safety
		keystroke "a" using command down
		delay 0.1
		keystroke "c" using command down
		delay 0.1
	end tell
end tell

set output to the clipboard
set the clipboard to saved_clipboard

-- IMPORTANT: Return focus to the original application.
if front_app_name is not "Terminal" then
	try
		tell application front_app_name to activate
	end try
end if

return output
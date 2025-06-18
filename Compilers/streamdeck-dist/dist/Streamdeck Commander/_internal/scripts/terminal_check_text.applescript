-- Purpose: Gets window content via clipboard by finding a window with a specific CUSTOM TITLE.
-- This version is more robust for error checking after a command.
-- Placeholders: {{safe_target_title}}

tell application "Terminal"
	if not running then return "APPLETSCRIPT_ERROR: Terminal is not running."
	
	set target_window to missing value
	try
		-- Find the window by the custom title we set, which is more reliable than 'name'.
		repeat with w in windows
			if custom title of w is "{{safe_target_title}}" then
				set target_window to w
				exit repeat
			end if
		end repeat
		
		if target_window is missing value then
			-- If not found, it might be because the script that created it just finished.
			-- Give it a moment and check the front window as a fallback.
			delay 0.2
			try
				if custom title of front window is "{{safe_target_title}}" then
					set target_window to front window
				end if
			end try
			if target_window is missing value then
				return "ERROR: Window '{{safe_target_title}}' not found."
			end if
		end if
		
		-- Bring the target window to the front to ensure it's the active one.
		set index of target_window to 1
		
	on error e
		return "APPLETSCRIPT_ERROR: Failed to find or focus window: " & e
	end try
end tell

-- Now, use the reliable clipboard method to get the window's full content.
set saved_clipboard to the clipboard
set output to ""

tell application "System Events"
	tell process "Terminal"
		set frontmost to true
		delay 0.2 -- A brief pause to ensure focus is fully set.
		keystroke "a" using command down
		delay 0.1
		keystroke "c" using command down
		delay 0.1
	end tell
end tell

set output to the clipboard
set the clipboard to saved_clipboard

return output
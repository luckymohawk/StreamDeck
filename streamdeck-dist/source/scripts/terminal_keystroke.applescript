tell application "Terminal"
	activate
	tell application "System Events"
		try
			set frontmost of process "Terminal" to true
			tell window 1 of process "Terminal" whose name contains "{{safe_target_title}}"
				keystroke "{{keystroke_content}}"
			end tell
		on error e
			-- Fallback if specific title matching fails, just send to the frontmost Terminal window
			try
				keystroke "{{keystroke_content}}"
			end try
		end try
	end tell
end tell
-- Purpose: Default command execution in Terminal's frontmost selected tab, or new window.
-- Placeholders: {{escaped_command_payload}}

tell application "Terminal"
	activate
	if "{{escaped_command_payload}}" is not "" then
		if (count windows) is 0 then
			do script "{{escaped_command_payload}}"
		else
			try
				do script "{{escaped_command_payload}}" in selected tab of front window
			on error
				try
					do script "{{escaped_command_payload}}" in front window
				on error
					do script "{{escaped_command_payload}}"
				end try
			end try
		end if
	end if
end tell
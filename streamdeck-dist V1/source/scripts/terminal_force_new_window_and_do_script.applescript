-- This script expects the command to be embedded by the Python script
-- where {{final_script_payload_for_do_script}} is.

set theCommand to "{{final_script_payload_for_do_script}}"

if theCommand is not "" then
	tell application "Terminal"
		activate
		try
			-- Create a new window explicitly by running an empty command.
			-- This makes a new window (or tab, depending on Terminal prefs for 'do script')
			-- and returns a reference to it (specifically, the tab).
			set newTerminalContext to do script ""
			
			-- A brief delay might sometimes help ensure the new context is fully ready,
			-- though ideally not strictly necessary with direct object referencing.
			delay 0.2
			
			if newTerminalContext is missing value then
				log "Warning: 'do script \"\"' did not return a valid context. Attempting fallback."
				-- This is a less ideal fallback if the above doesn't work as expected.
				-- It makes it harder to guarantee the command runs in the *newest* window
				-- if multiple new windows were somehow created rapidly.
				do script theCommand
			else
				-- Execute the actual command in that new context.
				do script theCommand in newTerminalContext
			end if
			
		on error errMsg number errorNumber
			log "AppleScript Error during K-flag execution: " & errMsg & " (Number: " & errorNumber & ")"
			-- As a last resort, try to run it without specifying context,
			-- just to see if any command can be run.
			try
				tell application "Terminal"
					activate
					do script theCommand
				end tell
			on error finalErrMsg
				log "AppleScript K-flag final fallback also failed: " & finalErrMsg
			end try
		end try
	end tell
else
	log "K-flag: No command provided to AppleScript."
end if
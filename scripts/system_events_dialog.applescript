-- START OF FILE: system_events_dialog.txt (from your initial prompt)
-- Purpose: Displays a dialog with a prompt and default answer.
-- Used for: V-flag variable edits, # flag numeric input.
-- Placeholders: {{prompt_message}}, {{default_answer}}

set prompt_msg to "{{prompt_message}}"
set default_ans to "{{default_answer}}"

tell application "System Events"
	try
		activate
		display dialog prompt_msg default answer default_ans buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel" giving up after 120
		set dialog_result to the result
		if button returned of dialog_result is "OK" then
			return text returned of dialog_result
		else
			return "USER_CANCELLED_PROMPT"
		end if
	on error errMsg number errNum
		if errNum is -128 then
			return "USER_CANCELLED_PROMPT"
		end if
		if errNum is -1712 then
			return "USER_TIMEOUT_PROMPT"
		end if
		return "APPLETSCRIPT_ERROR:" & errNum & ":" & errMsg
	end try
end tell
-- END OF FILE: system_events_dialog.txt
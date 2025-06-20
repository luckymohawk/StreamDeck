-- This script uses the standard 'display dialog' command, which is generally more stable
-- for simple input prompts than invoking System Events from a background script.

try
	-- Display the dialog. This command is part of the standard AppleScript library
	-- and avoids the conflict of telling a separate application (System Events) to do it.
	-- 'with icon 1' shows a standard application icon.
	set dialog_result to display dialog "{{prompt_message}}" with title "StreamDeck Input" default answer "{{default_answer}}" buttons {"Cancel", "OK"} default button "OK" with icon 1 giving up after 120

	-- If the user clicked "OK", return the entered text.
	if button returned of dialog_result is "OK" then
		return text returned of dialog_result
	else
		-- This case is unlikely (covered by the 'on error' block) but handled for safety.
		return "USER_CANCELLED_PROMPT"
	end if

on error errmsg number errnum
	-- Handle the different ways the dialog can be dismissed.
	if errnum is -128 then
		-- User clicked the "Cancel" button.
		return "USER_CANCELLED_PROMPT"
	else if errnum is -1712 then
		-- The dialog timed out after the "giving up after" duration.
		return "USER_TIMEOUT_PROMPT"
	else
		-- An unexpected error occurred.
		return "APPLETSCRIPT_ERROR: " & errmsg & " (" & errnum & ")"
	end if
end try
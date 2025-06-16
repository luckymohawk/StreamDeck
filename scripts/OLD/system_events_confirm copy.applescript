-- This script displays a confirmation dialog with Yes/No buttons.
-- It expects {{prompt_message}} to be replaced by the Python driver.

try
	tell application "System Events"
		activate
		display dialog "{{prompt_message}}" with title "Confirm Action" buttons {"No", "Yes"} default button "No" cancel button "No" with icon caution
	end tell
	-- If we get here, the user clicked "Yes"
	return "YES_CONFIRMED"
on error errmsg number errnum
	-- Any other action (clicking "No", pressing escape, etc.) is a cancellation.
	return "USER_CANCELLED"
end try
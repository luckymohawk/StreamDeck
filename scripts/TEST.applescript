(*
    Standalone AppleScript Test - **Snapshot Version**

    This version solves the problem of finding "10" in the SSH connection
    text by taking a snapshot of the window content *before* the monitored
    command runs, and then only searching for new text added afterwards.
*)

-- Save the user's current clipboard so we can restore it later.
set saved_clipboard to the clipboard

tell application "Terminal"
	activate
	do script ""
	delay 0.5
	set target_window to front window
	set custom title of target_window to "Monitoring Test (Snapshot)"
end tell

-- Stage 1: Run SSH command
log "Sending SSH command..."
tell application "System Events"
	keystroke "ssh root@luckyiphone"
	keystroke return
end tell

-- CRITICAL: Wait for the SSH connection to be established.
log "Waiting 5 seconds for SSH to connect..."
delay 5

-- Stage 2: Take the "Before" snapshot of the window.
log "Taking initial snapshot of window content..."
set initial_content to ""
tell application "Terminal" to set index of target_window to 1
delay 0.2
tell application "System Events"
	keystroke "a" using command down
	delay 0.1
	keystroke "c" using command down
	delay 0.1
end tell
set initial_content to the clipboard
log "Snapshot taken. Length: " & (length of initial_content) & " characters."


-- Stage 3: Run the counter command. Its output will be the "new" text.
log "Sending counter command..."
tell application "System Events"
	keystroke "i=1; while true; do echo $i; ((i++)); sleep 1; done"
	keystroke return
end tell

log "Monitoring started. Looking for '10' in NEW text only."

set was_found to false
repeat with i from 1 to 120 -- Loop for up to 4 minutes
	
	-- Bring our target window to the front.
	tell application "Terminal" to set index of target_window to 1
	delay 0.2
	
	-- Get the full current content of the window
	tell application "System Events"
		keystroke "a" using command down
		delay 0.1
		keystroke "c" using command down
		delay 0.1
	end tell
	set current_content to the clipboard
	
	-- Check if there is any new text since our snapshot.
	if (length of current_content) > (length of initial_content) then
		-- Isolate only the new text
		set new_text to text ((length of initial_content) + 1) through -1 of current_content
		
		-- Search *only* in the new text
		if new_text contains "10" then
			log "Keyword '10' FOUND in new text!"
			set was_found to true
			exit repeat
		end if
	end if
	
	delay 2 -- Wait before the next check
end repeat


-- Restore the user's original clipboard content.
set the clipboard to saved_clipboard

if was_found is true then
	tell application (path to frontmost application as text)
		display dialog "FOUND" buttons {"OK"} default button "OK"
	end tell
else
	log "Monitoring finished without finding the keyword."
end if

log "Script finished."
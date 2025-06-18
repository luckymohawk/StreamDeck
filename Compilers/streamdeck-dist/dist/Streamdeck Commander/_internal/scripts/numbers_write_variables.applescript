-- This script receives a list of update commands and applies them to the Numbers sheet.
-- Each command is in the format "row_index,column_index,new_value".

set update_data to "{{update_data}}"

if update_data is "" then
	return "No variable updates to save."
end if

set RowSeparator to ASCII character 30
set FieldSeparator to ","

set old_delimiters to AppleScript's text item delimiters
set AppleScript's text item delimiters to RowSeparator
set update_commands to every text item of update_data
set AppleScript's text item delimiters to old_delimiters

tell application "Numbers"
	activate
	tell front document
		set target_sheet to missing value
		try
			set target_sheet to first sheet whose name is "Streamdeck"
		on error
			return "Error: Could not find a sheet named 'Streamdeck'."
		end try
		
		tell table 1 of target_sheet
			-- Loop through each update command
			repeat with i from 1 to (count of update_commands)
				set command_str to (item i of update_commands) as text
				if command_str is not "" then
					set AppleScript's text item delimiters to FieldSeparator
					set command_parts to every text item of command_str
					set AppleScript's text item delimiters to old_delimiters
					
					if (count of command_parts) is 3 then
						try
							set row_idx to (item 1 of command_parts) as integer
							set col_idx to (item 2 of command_parts) as integer
							set new_val to (item 3 of command_parts)
							
							set value of cell col_idx of row row_idx to new_val
						end try
					end if
				end if
			end repeat
		end tell
	end tell
end tell

return "Variable save successful."
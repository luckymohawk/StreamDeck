-- Final Combined Script (Version 14)
-- 1. Applies the same background and text color from Column A to Column D for visual consistency.
-- 2. This formatting is applied during both the main variable processing and the final fallback step.
-- 3. All previous bug fixes are retained.

tell application "Numbers"
	activate
	
	-- Part 1: User Confirmation Prompt
	display dialog "Would you like to process the 'Streamdeck' tab for color updates and database import?" buttons {"Cancel", "OK"} default button "OK"
	if button returned of result is "Cancel" then
		return
	end if
	
	tell document 1
		tell sheet "Streamdeck"
			tell table 1
				
				-- =================================================================
				-- Part 2: Update Colors (With Fix for "missing value")
				-- =================================================================
				try
					set rowCount to (count of rows)
					repeat with i from 2 to rowCount
						set cell_value to value of cell ("C" & i)
						if cell_value is missing value then
							tell cell ("A" & i)
								set background color to missing value
								set text color to {0, 0, 0}
							end tell
						else
							set flag to cell_value as text
							tell cell ("A" & i)
								if flag contains "K" then
									set background color to {0, 0, 0}
									set text color to {65535, 65535, 65535}
								else if flag contains "R" then
									set background color to {65535, 0, 0}
									set text color to {65535, 65535, 65535}
								else if flag contains "G" then
									set background color to {0, 65535, 0}
									set text color to {0, 0, 0}
								else if flag contains "B" then
									set background color to {0, 26214, 52428}
									set text color to {65535, 65535, 65535}
								else if flag contains "O" then
									set background color to {65535, 39321, 0}
									set text color to {0, 0, 0}
								else if flag contains "Y" then
									set background color to {65535, 65535, 0}
									set text color to {0, 0, 0}
								else if flag contains "P" then
									set background color to {32896, 0, 32896}
									set text color to {65535, 65535, 65535}
								else if flag contains "S" then
									set background color to {49344, 49344, 49344}
									set text color to {0, 0, 0}
								else if flag contains "F" then
									set background color to {65535, 0, 65535}
									set text color to {0, 0, 0}
								else if flag contains "W" then
									set background color to {65535, 65535, 65535}
									set text color to {0, 0, 0}
								else if flag contains "L" then
									set background color to {65021, 63222, 58365}
									set text color to {0, 0, 0}
								else
									set background color to missing value
									set text color to {0, 0, 0}
								end if
							end tell
						end if
					end repeat
				end try
				
				
				-- =================================================================
				-- Part 3: Variable Formatting (With Column D Formatting)
				-- =================================================================
				
				set value of cell 1 of column "D" to "Formula"
				set value of cell 1 of column "E" to "Var1 Name"
				set value of cell 1 of column "F" to "Var1 Value"
				set value of cell 1 of column "G" to "Var2 Name"
				set value of cell 1 of column "H" to "Var2 Value"
				set value of cell 1 of column "I" to "Var3 Name"
				set value of cell 1 of column "J" to "Var3 Value"
				
				set q to ASCII character 34
				set colLetters to {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J"}
				
				try
					set lastRow to (count of rows of column "B")
				on error
					return
				end try
				
				repeat with i from 2 to lastRow
					set shouldProcessRowDueToColD to true
					try
						set cellD_value to (value of cell i of column "D") as text
						if cellD_value contains "{{" and cellD_value contains "}}" then
							set shouldProcessRowDueToColD to false
						end if
					on error
					end try
					
					if shouldProcessRowDueToColD then
						set origB_value to (value of cell i of column "B")
						if origB_value is missing value then
							set origB to ""
						else
							set origB to origB_value as text
						end if
						
						if origB is not "" and origB contains "{{" then
							set bgA to background color of cell i of column "A"
							set tcA to text color of cell i of column "A"
							set remaining to origB
							set rebuilt to ""
							set processedNames to {}
							set partsList to {}
							
							repeat with c from 4 to 10
								set targetCell to cell i of column c
								set value of targetCell to ""
								try
									set formula of targetCell to missing value
								end try
							end repeat
							
							repeat while remaining contains "{{"
								set openPos to offset of "{{" in remaining
								if openPos > 1 then
									set prefix to text 1 thru (openPos - 1) of remaining
								else
									set prefix to ""
								end if
								set rebuilt to rebuilt & prefix
								if prefix is not "" then
									set end of partsList to q & prefix & q
								end if
								set remaining to text (openPos + 2) thru -1 of remaining
								if remaining contains "}}" then
									set closePos to offset of "}}" in remaining
									set varContent to text 1 thru (closePos - 1) of remaining
									if (closePos + 2) ² (length of remaining) then
										set remaining to text (closePos + 2) thru -1 of remaining
									else
										set remaining to ""
									end if
								else
									set rebuilt to rebuilt & "{{" & remaining
									if remaining is not "" then
										if partsList is not {} and (((count of partsList) > 0) and (item -1 of partsList ends with q)) then
											set item -1 of partsList to (text 1 thru -2 of (item -1 of partsList)) & "{{" & remaining & q
										else
											set end of partsList to q & "{{" & remaining & q
										end if
									end if
									set remaining to ""
									exit repeat
								end if
								set vc to contents of varContent
								if vc contains ":" then
									set colonPos to offset of ":" in vc
									set varName to text 1 thru (colonPos - 1) of vc
									set varValue to text (colonPos + 1) thru -1 of vc
								else
									set cellA_val_for_name to (value of cell i of column "A")
									if cellA_val_for_name is missing value then set cellA_val_for_name to "Default"
									set varName to (cellA_val_for_name as text) & ((count of processedNames) + 1)
									set varValue to vc
								end if
								set varNameFound to false
								set idx to 0
								repeat with k from 1 to count of processedNames
									if item k of processedNames is varName then
										set idx to k
										set varNameFound to true
										exit repeat
									end if
								end repeat
								if not varNameFound then
									set end of processedNames to varName
									set idx to count of processedNames
									if idx > 3 then
										set rebuilt to rebuilt & "{{" & varName & ":" & varValue & "}}"
										if partsList is not {} and (((count of partsList) > 0) and (item -1 of partsList ends with q)) then
											set item -1 of partsList to (text 1 thru -2 of (item -1 of partsList)) & "{{" & varName & ":" & varValue & "}}" & q
										else
											set end of partsList to q & "{{" & varName & ":" & varValue & "}}" & q
										end if
									else
										set nameColIdx to 3 + 2 * idx
										set valueColIdx to nameColIdx + 1
										set value of cell i of column nameColIdx to varName
										set value of cell i of column valueColIdx to varValue
										set background color of cell i of column nameColIdx to bgA
										set text color of cell i of column nameColIdx to tcA
										set background color of cell i of column valueColIdx to bgA
										set text color of cell i of column valueColIdx to tcA
									end if
								else
									if idx = 0 then
									end if
								end if
								if idx > 0 and idx ² 3 then
									set nameColLetter to item (3 + 2 * idx) of colLetters
									set valueColLetter to item (3 + 2 * idx + 1) of colLetters
									set end of partsList to q & "{{" & q & " & " & (nameColLetter & i as text) & " & " & q & ":" & q & " & " & (valueColLetter & i as text) & " & " & q & "}}" & q
								end if
								set rebuilt to rebuilt & varValue
							end repeat
							set rebuilt to rebuilt & remaining
							set value of cell i of column "B" to rebuilt
							if (count of processedNames) > 0 then
								set background color of cell i of column "B" to bgA
								set text color of cell i of column "B" to tcA
							end if
							if (count of processedNames) > 0 then
								set origC_value to (value of cell i of column "C")
								if origC_value is missing value then
									set origC to ""
								else
									set origC to origC_value as text
								end if
								if origC does not contain "V" then
									set value of cell i of column "C" to origC & "V"
									set background color of cell i of column "C" to bgA
									set text color of cell i of column "C" to tcA
								end if
							end if
							
							if (count of processedNames) > 0 and ((count of partsList) > 0) then
								if origB contains q then
									set value of cell i of column "D" to origB
									set value of cell i of column "E" to "Check D: OrigB had quotes"
									set background color of cell i of column "E" to {65535, 50000, 0}
								else
									if remaining is not "" then
										if partsList is {} or not (((count of partsList) > 0) and (item -1 of partsList ends with q)) then
											set end of partsList to q & remaining & q
										else
											set item -1 of partsList to (text 1 thru -2 of (item -1 of partsList)) & remaining & q
										end if
									end if
									if partsList is not {} then
										set oldDels to AppleScript's text item delimiters
										set AppleScript's text item delimiters to " & "
										set formulaBody to partsList as text
										set AppleScript's text item delimiters to oldDels
										set value of cell i of column "D" to "=" & formulaBody
									else if rebuilt is not "" then
										set value of cell i of column "D" to rebuilt
									else
										set value of cell i of column "D" to origB
									end if
								end if
							else
								set value of cell i of column "D" to rebuilt
							end if
							
							-- FIX: Apply the captured row formatting to Column D
							set background color of cell i of column "D" to bgA
							set text color of cell i of column "D" to tcA
							
						end if
					end if
				end repeat
				
				-- =================================================================
				-- Part 4: Final Cleanup and Fallback for Column D
				-- =================================================================
				try
					set lastRow to (count of rows)
					repeat with i from 2 to lastRow
						try
							set cellD_value to value of cell ("D" & i)
							if cellD_value is missing value then
								set value of cell ("D" & i) to "=B" & i
								-- FIX: Apply row formatting to fallback cells too
								set bgA_fallback to background color of cell ("A" & i)
								set tcA_fallback to text color of cell ("A" & i)
								set background color of cell ("D" & i) to bgA_fallback
								set text color of cell ("D" & i) to tcA_fallback
							end if
						on error
							set value of cell ("D" & i) to "=B" & i
							-- FIX: Apply row formatting to fallback cells too
							set bgA_fallback to background color of cell ("A" & i)
							set tcA_fallback to text color of cell ("A" & i)
							set background color of cell ("D" & i) to bgA_fallback
							set text color of cell ("D" & i) to tcA_fallback
						end try
					end repeat
				end try
				
			end tell
		end tell
	end tell
	display dialog "Script finished processing." buttons {"OK"} default button "OK"
end tell
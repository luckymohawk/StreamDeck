-- Updated script to silently exit if the "Streamdeck" tab already exists.

tell application "System Events"
	set numbersRunning to (exists process "Numbers")
end tell

if not numbersRunning then
	set userChoice to button returned of (display dialog "Numbers isn't running. Launch it and create a new document?" buttons {"Cancel", "Launch"} default button "Launch")
	if userChoice is "Cancel" then return
	tell application "Numbers" to activate
	delay 1
	tell application "Numbers"
		set activeDoc to make new document
	end tell
else
	tell application "Numbers"
		set docsCount to count documents
	end tell
	
	if docsCount is 0 then
		set userChoice to button returned of (display dialog "No Numbers document open. Create one now?" buttons {"Cancel", "Create"} default button "Create")
		if userChoice is "Cancel" then return
		tell application "Numbers"
			set activeDoc to make new document
		end tell
	else
		tell application "Numbers"
			set activeDoc to front document
		end tell
	end if
end if

tell application "Numbers"
	tell activeDoc
		set tabExists to false
		repeat with s in sheets
			if name of s is "Streamdeck" then
				set tabExists to true
				exit repeat
			end if
		end repeat
	end tell
end tell

-- =================================================================
-- MODIFIED SECTION
-- The "display dialog" line has been removed.
-- =================================================================
if tabExists then
	return
end if
-- =================================================================

tell application "Numbers"
	tell activeDoc
		set newSheet to make new sheet with properties {name:"Streamdeck"}
		tell newSheet
			delay 0.5
			try
				delete (table 1 whose name is "Table 1")
			end try
			
			-- Commands Table (30 rows)
			set cmdHeaders to {"Button Name", "Terminal Command", "Feature Flags", "Commands with Variables (Generated)", "Var 1 Name", "Variable 1", "Var 2 Name", "Variable 2", "Var 3 Name", "Variable 3", "? Monitoring Keyword"}
			set cmdTable to make new table with properties {row count:31, column count:(count cmdHeaders), name:"Commands", position:{50, 50}}
			tell cmdTable
				repeat with i from 1 to count cmdHeaders
					set value of cell i of row 1 to item i of cmdHeaders
					tell cell i of row 1
						set text color to {65535, 65535, 65535} -- white text
					end tell
				end repeat
				set header row count to 1
				set background color of row 1 to {7500, 7500, 7500} -- dark gray
				repeat with r from 1 to 31
					set height of row r to 26
				end repeat
				set colWidths to {110, 160, 70, 170, 70, 100, 70, 100, 70, 100, 130}
				repeat with i from 1 to count cmdHeaders
					set width of column i to item i of colWidths
				end repeat
			end tell
			
			-- FEATURE FLAGS Table
			set legendHeaders to {"Flag Symbol (Col. 3)", "Name", "Description", "Notes"}
			set legendData to {¬
				{"@", "Device", "Marks a button as a \"target device.\" When active, other buttons will send their commands to this device's terminal window.", "Using root will allow the M flag to function for mobile, only use mobile if no root will be needed."}, ¬
				{"~", "Monitor", "Continuously monitors an @ device's SSH connection, providing \"CONNECTED\" or \"BROKEN\" feedback on the button.", "Not tested for buttons without @"}, ¬
				{"*", "Record", "Creates a stateful record button. Short-press starts/stops the command. Long-press allows editing variables.", "For full functionality including error monitoring, take incrementing, and log creation use pre-defined variables
{{RECPATH:your/default/path}}
{{SCENE:yourdefaultscene}}
{{TAKE:001}}"}, ¬
				{"?", "Keyword Monitor", "Executes a command and “?” monitors terminal output for monitor_keyword. Button turns green and sticky when keyword found.", "Polls every minute, and brings window to foreground to snapshot. May be distracting."}, ¬
				{"#", "Numeric", "Long-press to adjust numeric variables with ▲▼ keys, then re-runs command.", "Use for incrementing numbers for brightness or positioning."}, ¬
				{"V", "Variables", "Long-press opens dialogs to edit {{variables}} in command.", "Good for IP/file path updates."}, ¬
				{"T", "Top (Sticky)", "Makes button sticky at reserved top area.", "Recommended for @ devices"}, ¬
				{"N", "New Window", "Always execute command in new terminal.", "Processes needing separate windows."}, ¬
				{"K", "Keep Local", "Execute command on local machine only.", "Device key setup."}, ¬
				{"M", "Mobile SSH", "Transforms ssh command for mobile (mobile@host).", "Opens or searches mobile SSH windows."}, ¬
				{"&", "Background", "Run command silently as background toggle.", ""}, ¬
				{">", "Confirm", "Shows \"> proceed?\" dialog before command.", "not recommended for toggle buttons"}, ¬
				{"1-99", "Font Size", "Sets the font size for the button's primary label text (e.g., R20).", "16-25 recommended"}, ¬
				{"D", "Dim Background", "Dims the selected base color (e.g., GD for dim green).", ""}, ¬
				{"R", "Red", "#FF0000", ""}, ¬
				{"G", "Green", "#00FF00", ""}, ¬
				{"B", "Blue", "#0066CC", ""}, ¬
				{"O", "Orange", "#FF9900", ""}, ¬
				{"Y", "Yellow", "#FFFF00", ""}, ¬
				{"P", "Purple", "#800080", ""}, ¬
				{"S", "Silver", "#C0C0C0", ""}, ¬
				{"F", "Fuchsia", "#FF00FF", ""}, ¬
				{"W", "White", "#FFFFFF", ""}, ¬
				{"L", "Light (Cream)", "#FDF6E3", ""}, ¬
				{"", "Black (Default)", "#000000", ""}}
			
			set legendTable to make new table with properties {row count:(count legendData) + 1, column count:4, name:"FEATURE FLAGS", position:{1300, 50}}
			tell legendTable
				repeat with i from 1 to 4
					set value of cell i of row 1 to item i of legendHeaders
					tell cell i of row 1
						set text color to {65535, 65535, 65535} -- white text
					end tell
					set width of column i to item i of {100, 160, 400, 300}
				end repeat
				set header row count to 1
				set background color of row 1 to {7500, 7500, 7500} -- dark gray
				
				repeat with r from 1 to count legendData
					set rowData to item r of legendData
					repeat with c from 1 to 4
						set value of cell c of row (r + 1) to item c of rowData
					end repeat
				end repeat
				
				repeat with r from 1 to (count legendData) + 1
					set height of row r to 60
				end repeat
			end tell
		end tell
	end tell
end tell
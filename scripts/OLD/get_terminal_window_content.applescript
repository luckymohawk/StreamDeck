on run argv
	set targetWindowName to item 1 of argv
	
	tell application "Terminal"
		set matchedWindow to missing value
		set windowTitles to {}
		
		repeat with w in windows
			set currentName to name of w
			copy currentName to end of windowTitles
			
			if currentName contains targetWindowName then
				set matchedWindow to w
				exit repeat
			end if
		end repeat
		
		if matchedWindow is missing value then
			set AppleScript's text item delimiters to ", "
			set windowList to windowTitles as string
			return "WINDOW_NOT_FOUND;Available Windows: " & windowList
		else
			return contents of matchedWindow's selected tab
		end if
	end tell
end run

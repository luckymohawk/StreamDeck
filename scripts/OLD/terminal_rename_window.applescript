on run argv
    if count of argv is 2 then
        set oldTitleFragment to item 1 of argv
        set newTitleToSet to item 2 of argv

        tell application "Terminal"
            activate
            try
                set targetWindow to missing value
                repeat with w in windows
                    try
                        -- Try to match based on custom title containing the fragment,
                        -- or if the window name (often the process) matches.
                        if (custom title of w contains oldTitleFragment) or (name of w contains oldTitleFragment) then
                            set targetWindow to w
                            exit repeat
                        end if
                    on error errMsgInner
                         -- Ignore error if a window doesn't have a custom title property yet
                    end try
                end repeat

                if targetWindow is not missing value then
                    tell targetWindow
                        set custom title to newTitleToSet
                        -- Also set for the selected tab for good measure
                        try
                            set custom title of selected tab to newTitleToSet
                        end try
                    end tell
                else
                    log "Rename: Window with title fragment '" & oldTitleFragment & "' not found."
                end if
            on error errMsg
                log "Rename Error: " & errMsg
            end try
        end tell
    else
        log "Rename Script: Incorrect number of arguments. Expected oldTitleFragment and newTitle."
    end if
end run
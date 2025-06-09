on run
    tell application "Terminal"
        if not (exists window 1) then return "ERROR: No Terminal window open"
        try
            -- Get content of the frontmost window's selected tab
            -- 'history' gets all scrollback buffer, 'contents' gets visible part.
            -- 'history' is usually better for keyword searching.
            return history of selected tab of window 1
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
end run
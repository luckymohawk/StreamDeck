tell application "Terminal"
    set window_found to false
    try
        repeat with w_obj in windows
            if custom title of w_obj is "{{target_window_title}}" then
                tell w_obj
                    activate
                    set index to 1
                end tell
                set window_found to true
                exit repeat
            end if
        end repeat
    on error errMsg
        log "AS_Error (activate_window_by_title): " & errMsg
        return "false"
    end try
    if window_found then
        return "true"
    else
        log "AS: Window '{{target_window_title}}' not found for activation."
        return "false"
    end if
end tell
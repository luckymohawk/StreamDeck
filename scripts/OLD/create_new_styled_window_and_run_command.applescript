tell application "Terminal"
    activate
    set new_terminal_entity to missing value
    try
        set new_terminal_entity to do script "{{command_to_run_in_new_window}}"
    on error errMsg
        log "AS_Error (create_new_styled_window): 'do script' failed: " & errMsg
    end try
    delay 0.3
    set target_window to missing value
    try
        if new_terminal_entity is not missing value then
            set new_entity_class to class of new_terminal_entity
            if new_entity_class is tab then
                try
                    set target_window to window of new_terminal_entity
                on error
                    if (count windows) > 0 then set target_window to front window
                end try
            else if new_entity_class is window then
                set target_window to new_terminal_entity
            else
                if (count windows) > 0 then set target_window to front window
            end if
        else if (count of windows) > 0 then
            set target_window to front window
        end if
    on error class_err
        log "AS_Error (create_new_styled_window): Determining target window failed: " & class_err
        if (count windows) > 0 then set target_window to front window
    end try
    if target_window is not missing value then
        log "AS: Styling new window '{{window_custom_title}}'."
        tell target_window
            set custom title to "{{window_custom_title}}"
            set background color to {{aps_bg_color}}
            set normal text color to {{aps_text_color}}
            set cursor color to {{aps_text_color}}
            set bold text color to {{aps_text_color}}
            set index to 1
        end tell
    else
        log "AS: Could not determine window for styling '{{window_custom_title}}'."
    end if
end tell
--- Creating file: activate_terminal_window.applescript ---

-- Brings a specific Terminal window to the front.
-- Takes the target window name as a parameter.
tell application "Terminal"
    activate
    try
        set the frontmost of window "{{window_name}}" to true
    on error
        -- This error is ignored. If the window doesn't exist anymore, there's nothing to do.
    end try
end tell

--- End of file ---


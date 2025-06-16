tell application "System Events"
    activate
    try
        display dialog "{{prompt_message}}" default answer "{{default_answer}}" buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel" with icon 1 giving up after 120
        set dialog_result to the result
        if button returned of dialog_result is "OK" then
            return text returned of dialog_result
        else
            return "USER_CANCELLED_PROMPT"
        end if
    on error errMsg number errNum
        if errNum is -128 then return "USER_CANCELLED_PROMPT"
        if errNum is -1712 then return "USER_TIMEOUT_PROMPT"
        return "APPLETSCRIPT_ERROR:" & errNum & ":" & errMsg
    end try
end tell
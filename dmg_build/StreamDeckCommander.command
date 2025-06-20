#!/bin/bash
set -e
APP_DIR_LAUNCHER="$HOME/Library/StreamdeckDriver"
export DYLD_LIBRARY_PATH="${APP_DIR_LAUNCHER}/lib:${DYLD_LIBRARY_PATH}"
export PATH="${APP_DIR_LAUNCHER}/nodejs/bin:${PATH}"
WEB_UI_DIR="${APP_DIR_LAUNCHER}/browsebuttons"
LOG_FILE="${APP_DIR_LAUNCHER}/web-ui.log"
if [ -f "${APP_DIR_LAUNCHER}/nodejs/bin/npm" ]; then
    (cd "${WEB_UI_DIR}" && nohup npm run dev > "${LOG_FILE}" 2>&1 &)
fi

PYTHON_EXEC_PATH="${APP_DIR_LAUNCHER}/.venv/bin/python"
DRIVER_SCRIPT_PATH="${APP_DIR_LAUNCHER}/streamdeck_driver.py"

osascript_command="tell application \"Terminal\"
    activate
    do script \"
        export DYLD_LIBRARY_PATH='${APP_DIR_LAUNCHER}/lib';
        '${PYTHON_EXEC_PATH}' '${DRIVER_SCRIPT_PATH}';
        echo; echo '-----------------------------------------';
        echo 'Driver has exited. Press any key to close this window.';
        read -k
    \"
end tell"
/usr/bin/osascript -e "${osascript_command}"
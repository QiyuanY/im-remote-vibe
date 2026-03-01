#!/bin/bash

# Get the absolute path of current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"
LOG_DIR="$SCRIPT_DIR/logs"
MAIN_PATH="$SCRIPT_DIR/main.py"
LOG_FILE="$LOG_DIR/vibe_remote.log"

echo "vibe-remote Status"
echo "==================="

if [ -f "$SCRIPT_DIR/.env" ]; then
    PLATFORM=$(cd "$SCRIPT_DIR" && python3 - <<'PY' 2>/dev/null || true
from dotenv import load_dotenv
import os
# Use explicit path to avoid frame detection issues in Python 3.13
_project_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_project_dir, '.env'))
print(os.getenv("IM_PLATFORM", ""))
PY
)
    if [ -n "$PLATFORM" ]; then
        echo "Platform: $PLATFORM"
    fi
fi

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    
    # Check if the process exists
    if ps -p "$PID" > /dev/null 2>&1; then
        # Verify it's our python process by absolute main.py path
        PROCESS_CMD=$(ps -p "$PID" -o command= 2>/dev/null || echo "")
        if [[ "$PROCESS_CMD" == *"$MAIN_PATH"* ]]; then
            echo "Status: RUNNING"
            echo "PID: $PID"
            
            # Show process info
            echo ""
            echo "Process info:"
            ps -p "$PID" -o pid,vsz,rss,pcpu,pmem,etime,command
            
            if [ -f "$LOG_FILE" ]; then
                echo ""
                echo "Log file: $LOG_FILE"
                echo "Last 30 lines:"
                echo "---"
                tail -n 30 "$LOG_FILE"
            fi
        else
            echo "Status: STOPPED (stale PID file)"
            echo "PID file exists but process is not our bot"
        fi
    else
        echo "Status: STOPPED (stale PID file)"
        echo "Bot is not running"
    fi
else
    echo "Status: STOPPED"
    echo "Bot is not running (no PID file)"
fi

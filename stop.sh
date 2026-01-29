#!/bin/bash

# Get the absolute path of current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"
MAIN_PATH="$SCRIPT_DIR/main.py"

echo "Stopping vibe-remote..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    
    # Check if the process exists
    if ps -p "$PID" > /dev/null 2>&1; then
        # Verify it's our python process by absolute main.py path
        PROCESS_CMD=$(ps -p "$PID" -o command= 2>/dev/null || echo "")
        if [[ "$PROCESS_CMD" == *"$MAIN_PATH"* ]]; then
            echo "Found bot process (PID: $PID), stopping..."
            kill -TERM "$PID" 2>/dev/null
            
            # Wait for process to terminate gracefully
            for i in {1..10}; do
                if ! ps -p "$PID" > /dev/null 2>&1; then
                    echo "Bot stopped successfully"
                    rm -f "$PID_FILE"
                    exit 0
                fi
                sleep 1
            done
            
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Force killing process..."
                kill -KILL "$PID" 2>/dev/null
                sleep 1
            fi
            
            if ! ps -p "$PID" > /dev/null 2>&1; then
                echo "Bot stopped (force killed)"
                rm -f "$PID_FILE"
            else
                echo "ERROR: Failed to stop bot!"
                exit 1
            fi
        else
            echo "PID file exists but process is not our bot"
            echo "Removing stale PID file"
            rm -f "$PID_FILE"
        fi
    else
        echo "Bot is not running (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    echo "Bot is not running (no PID file found)"
fi

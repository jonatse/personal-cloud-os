#!/bin/bash
# Personal Cloud OS - CLI Interface

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment if exists
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# Start in CLI mode
python3 "$SCRIPT_DIR/src/main.py" --cli

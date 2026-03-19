#!/bin/bash
# Personal Cloud OS - Start Script

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment if exists
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# Check if Reticulum is installed
if ! python3 -c "import RNS" 2>/dev/null; then
    echo "Installing Reticulum..."
    pip install rns
fi

# Start with system tray
python3 "$SCRIPT_DIR/src/main.py" --tray "$@"

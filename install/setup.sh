#!/bin/bash
# Personal Cloud OS - Self-Contained Setup Script
# Run this once to set up the environment

set -e

echo "=============================================="
echo "  Personal Cloud OS - Setup"
echo "=============================================="

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.10"
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python 3.10+ required. Found: $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python version: $PYTHON_VERSION"

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Reticulum dependencies
echo "Installing Reticulum dependencies..."
pip install rns

# Create log directory
mkdir -p ~/.local/share/pcos/logs

# Create config directory
mkdir -p ~/.config/pcos

# Create Desktop entry (optional)
if [ "$1" = "--desktop" ]; then
    echo "Creating desktop entry..."
    cat > ~/.local/share/applications/pcos.desktop << DESKTOP
[Desktop Entry]
Type=Application
Name=Personal Cloud OS
Comment=Self-contained cloud OS with ZeroTrust networking
Exec=$(pwd)/start.sh
Icon=cloud
Terminal=false
Categories=Network;Utility;
StartupNotify=true
DESKTOP
    echo "✓ Desktop entry created"
fi

echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "To run Personal Cloud OS:"
echo "  ./start.sh           # Start in background with tray"
echo "  python3 src/main.py --cli    # Open CLI interface"
echo ""
echo "The app will:"
echo "  • Start automatically in background"
echo "  • Show system tray icon"
echo "  • Discover peers on your network"
echo "  • Sync files between devices"
echo ""

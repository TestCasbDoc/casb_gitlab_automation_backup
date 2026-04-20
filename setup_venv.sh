#!/bin/bash
# ============================================================
# CASB Automation — Virtual Environment Setup (Linux)
# Run this once before using the framework
# ============================================================

echo ""
echo "========================================================"
echo "  CASB Automation — Virtual Environment Setup"
echo "========================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found. Install Python 3.9+ first."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
echo "[OK] $(python3 --version) found"

# Create venv
echo ""
echo "Creating virtual environment..."
python3 -m venv .venv
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create virtual environment."
    echo "  Try: sudo apt install python3-venv"
    exit 1
fi
echo "[OK] Virtual environment created at .venv/"

# Activate and install deps
echo ""
echo "Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies."
    exit 1
fi
echo "[OK] All dependencies installed"

# Install Playwright browsers
echo ""
echo "Installing Playwright Chromium browser..."
playwright install chromium
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install Playwright Chromium."
    exit 1
fi
echo "[OK] Playwright Chromium installed"

# Install package in editable mode
echo ""
echo "Installing casb-automation CLI..."
pip install -e . --quiet
echo "[OK] casb-automation CLI installed"

echo ""
echo "========================================================"
echo "  Setup complete!"
echo ""
echo "  To activate the virtual environment:"
echo "    source .venv/bin/activate"
echo ""
echo "  To run the automation:"
echo "    casb-automation --applications 'MS_Teams' --host IP --pwd PWD --ssh-user USER"
echo ""
echo "  To deactivate:"
echo "    deactivate"
echo "========================================================"
echo ""

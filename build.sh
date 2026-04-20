#!/bin/bash
# ============================================================
# CASB Automation — Build Linux Binary
# Produces: dist/casb-automation
# Run from the casb_new_structure folder
# ============================================================

echo ""
echo "========================================================"
echo "  CASB Automation — Building Linux Binary"
echo "========================================================"
echo ""

# Activate venv if exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "[OK] Virtual environment activated"
else
    echo "WARNING: No .venv found. Run setup_venv.sh first."
    echo "Trying with system Python..."
fi

# Install PyInstaller
echo ""
echo "Installing PyInstaller..."
pip install pyinstaller --quiet
echo "[OK] PyInstaller ready"

# Clean previous build
echo ""
echo "Cleaning previous build..."
rm -f dist/casb-automation
rm -rf build/
echo "[OK] Cleaned"

# Build
echo ""
echo "Building casb-automation binary..."
pyinstaller casb-automation.spec --clean --noconfirm
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Build failed. Check output above."
    exit 1
fi

# Verify
if [ -f "dist/casb-automation" ]; then
    chmod +x dist/casb-automation
    echo ""
    echo "========================================================"
    echo "  BUILD SUCCESSFUL!"
    echo "  Binary: dist/casb-automation"
    echo ""
    echo "  Usage:"
    echo "    ./dist/casb-automation --applications 'MS_Teams' --host IP --pwd PWD --ssh-user USER"
    echo ""
    echo "  NOTE: Playwright Chromium must still be installed on"
    echo "        the target machine:"
    echo "        playwright install chromium"
    echo "========================================================"
else
    echo "ERROR: Binary not found after build."
    exit 1
fi
echo ""

@echo off
:: ============================================================
:: CASB Automation — Virtual Environment Setup (Windows)
:: Run this once before using the framework
:: ============================================================

echo.
echo ========================================================
echo   CASB Automation — Virtual Environment Setup
echo ========================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.9+ and add to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i found

:: Create venv
echo.
echo Creating virtual environment...
python -m venv .venv
if %errorLevel% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment created at .venv\

:: Activate and install deps
echo.
echo Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if %errorLevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] All dependencies installed

:: Install Playwright browsers
echo.
echo Installing Playwright Chromium browser...
playwright install chromium
if %errorLevel% neq 0 (
    echo ERROR: Failed to install Playwright Chromium.
    pause
    exit /b 1
)
echo [OK] Playwright Chromium installed

:: Install package in editable mode
echo.
echo Installing casb-automation CLI...
pip install -e .
if %errorLevel% neq 0 (
    echo ERROR: Failed to install casb-automation CLI.
    pause
    exit /b 1
)
echo [OK] casb-automation CLI installed

echo.
echo ========================================================
echo   Setup complete!
echo.
echo   To activate the virtual environment:
echo     .venv\Scripts\activate
echo.
echo   To run the automation:
echo     casb-automation --applications "MS_Teams" --host IP --pwd PWD --ssh-user USER
echo.
echo   To deactivate:
echo     deactivate
echo ========================================================
echo.
pause
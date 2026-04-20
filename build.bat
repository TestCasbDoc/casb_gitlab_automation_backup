@echo off
:: ============================================================
:: CASB Automation — Build Windows Binary
:: Produces: dist\casb-automation.exe
:: Run from the casb_new_structure folder
:: ============================================================

echo.
echo ========================================================
echo   CASB Automation — Building Windows Binary
echo ========================================================
echo.

:: Activate venv if exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] Virtual environment activated
) else (
    echo WARNING: No .venv found. Run setup_venv.bat first.
    echo Trying with system Python...
)

:: Install PyInstaller
echo.
echo Installing PyInstaller...
pip install pyinstaller --quiet
echo [OK] PyInstaller ready

:: Clean previous build
echo.
echo Cleaning previous build...
if exist "dist\casb-automation.exe" del /f "dist\casb-automation.exe"
if exist "build" rmdir /s /q build
echo [OK] Cleaned

:: Build
echo.
echo Building casb-automation.exe...
pyinstaller casb-automation.spec --clean --noconfirm
if %errorLevel% neq 0 (
    echo.
    echo ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

:: Verify
if exist "dist\casb-automation.exe" (
    echo.
    echo ========================================================
    echo   BUILD SUCCESSFUL!
    echo   Binary: dist\casb-automation.exe
    echo.
    echo   Usage:
    echo     dist\casb-automation.exe --applications "MS_Teams" --host IP --pwd PWD --ssh-user USER
    echo.
    echo   NOTE: Playwright Chromium must still be installed on
    echo         the target machine:
    echo         playwright install chromium
    echo ========================================================
) else (
    echo ERROR: Binary not found after build.
)

echo.
pause

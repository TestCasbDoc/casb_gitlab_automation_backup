@echo off
:: ============================================================
:: CASB Results Server — Windows Service Installer
:: Run this as Administrator
:: ============================================================

echo.
echo ========================================================
echo   CASB Results Server — Service Installer
echo ========================================================
echo.

:: Check admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Please run this as Administrator.
    echo Right-click install_service.bat and select "Run as administrator"
    pause
    exit /b 1
)

:: ── Config ───────────────────────────────────────────────────
set SERVICE_NAME=CASBResultsServer
set SERVICE_DISPLAY=CASB Results Server
set SERVICE_DESC=CASB Automation Results Dashboard - http://10.196.3.26:4012

:: Detect Python path
for /f "tokens=*" %%i in ('where python') do set PYTHON_PATH=%%i
if "%PYTHON_PATH%"=="" (
    echo ERROR: Python not found. Make sure Python is in PATH.
    pause
    exit /b 1
)
echo [OK] Python found: %PYTHON_PATH%

:: Detect app.py path (same folder as this bat file)
set SCRIPT_DIR=%~dp0
set APP_PATH=%SCRIPT_DIR%app.py
if not exist "%APP_PATH%" (
    echo ERROR: app.py not found at %APP_PATH%
    echo Make sure install_service.bat is in the same folder as app.py
    pause
    exit /b 1
)
echo [OK] app.py found: %APP_PATH%

:: ── Install waitress (production WSGI server) ────────────────
echo.
echo Installing waitress...
pip install waitress --quiet
echo [OK] waitress installed

:: ── Create runner script ─────────────────────────────────────
set RUNNER=%SCRIPT_DIR%run_server.py
echo import sys > "%RUNNER%"
echo sys.path.insert(0, r'%SCRIPT_DIR%') >> "%RUNNER%"
echo from waitress import serve >> "%RUNNER%"
echo from app import app >> "%RUNNER%"
echo print('CASB Results Server starting on port 4012...') >> "%RUNNER%"
echo serve(app, host='0.0.0.0', port=4012) >> "%RUNNER%"
echo [OK] Runner script created: %RUNNER%

:: ── Install using NSSM if available, else Task Scheduler ─────
where nssm >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo Installing service using NSSM...
    nssm stop %SERVICE_NAME% >nul 2>&1
    nssm remove %SERVICE_NAME% confirm >nul 2>&1
    nssm install %SERVICE_NAME% "%PYTHON_PATH%" "%RUNNER%"
    nssm set %SERVICE_NAME% DisplayName "%SERVICE_DISPLAY%"
    nssm set %SERVICE_NAME% Description "%SERVICE_DESC%"
    nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
    nssm set %SERVICE_NAME% AppStdout "%SCRIPT_DIR%server.log"
    nssm set %SERVICE_NAME% AppStderr "%SCRIPT_DIR%server.log"
    nssm start %SERVICE_NAME%
    echo [OK] Service installed and started via NSSM
) else (
    echo.
    echo NSSM not found — using Task Scheduler...
    :: Remove existing task if any
    schtasks /delete /tn "%SERVICE_NAME%" /f >nul 2>&1
    :: Create task that runs at system startup
    schtasks /create /tn "%SERVICE_NAME%" ^
        /tr "\"%PYTHON_PATH%\" \"%RUNNER%\"" ^
        /sc onstart ^
        /ru SYSTEM ^
        /rl HIGHEST ^
        /f
    :: Start immediately
    schtasks /run /tn "%SERVICE_NAME%"
    echo [OK] Task Scheduler task created and started
)

:: ── Wait and verify ───────────────────────────────────────────
echo.
echo Waiting for server to start...
timeout /t 5 /nobreak >nul

:: Check if port 4012 is listening
netstat -an | findstr ":4012" | findstr "LISTENING" >nul
if %errorLevel% equ 0 (
    echo.
    echo ========================================================
    echo   SUCCESS! CASB Results Server is running.
    echo   Dashboard: http://10.196.3.26:4012
    echo   Auto-starts every time Windows boots.
    echo ========================================================
) else (
    echo.
    echo WARNING: Server may not have started yet.
    echo Check server.log in this folder for errors.
    echo Try opening http://10.196.3.26:4012 in a browser.
)

echo.
pause

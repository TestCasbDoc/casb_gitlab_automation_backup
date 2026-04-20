@echo off
:: ============================================================
:: CASB — Start server + run automation with one command
::
:: Usage:
::   casb_server_start.bat [casb-automation args...]
::
:: Example:
::   casb_server_start.bat --applications ms_teams_personal --host 10.0.0.1 --pwd secret --ssh-user admin --user amruta
::
:: NOTE: Automatically detects this machine's IP and passes it
::       as --server-url so results are stored on YOUR RDP.
::       Server keeps running after automation finishes.
::       To stop manually: taskkill /IM python.exe /F
:: ============================================================

set SCRIPT_DIR=%~dp0
set SERVER_DIR=%SCRIPT_DIR%casb_server

:: ── Activate venv if present ─────────────────────────────────
if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
    echo [OK] Virtual environment activated
)

:: ── Auto-detect this machine's IP ────────────────────────────
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| find "IPv4" ^| find "10."') do (
    set MY_IP=%%a
    goto :ip_found
)
:ip_found
:: Trim leading space from IP
set MY_IP=%MY_IP: =%
set SERVER_URL=http://%MY_IP%:4012
echo [OK] Detected RDP IP: %MY_IP%
echo [OK] Server URL will be: %SERVER_URL%

:: ── Start CASB server (only if not already running) ──────────
echo.
echo ========================================================
echo   Starting CASB Results Server on port 4012...
echo ========================================================
netstat -aon | find ":4012" | find "LISTENING" >nul 2>&1
if %errorLevel%==0 (
    echo [OK] Server already running on port 4012
) else (
    start "CASB-Server" /B python "%SERVER_DIR%\run_server.py"
    timeout /t 2 /nobreak >nul
    echo [OK] Server started in background
)

:: ── Run CASB automation (inject --server-url automatically) ──
echo.
echo ========================================================
echo   Running CASB Automation...
echo   Uploading results to: %SERVER_URL%
echo ========================================================
python "%SCRIPT_DIR%run.py" --server-url %SERVER_URL% %*
set AUTOMATION_EXIT=%errorLevel%

:: ── Automation done — server stays alive ─────────────────────
echo.
echo ========================================================
echo   Automation finished!
echo   Results available at: %SERVER_URL%
echo   Server is still running. To stop it manually:
echo     taskkill /IM python.exe /F
echo ========================================================
echo.

exit /b %AUTOMATION_EXIT%

@echo off
:: ============================================================
:: CASB — Start server + run automation with one command
::
:: Usage:
::   casb_server_start.bat [casb-automation args...]
::
:: Examples:
::   Auto-detect RDP IP (default):
::     casb_server_start.bat --applications ms_teams_personal --host 10.0.0.1 --pwd secret --ssh-user admin --user amruta
::
::   Store results on a different server (manual override):
::     casb_server_start.bat --applications ms_teams_personal --host 10.0.0.1 --pwd secret --ssh-user admin --user amruta --server-url http://10.196.3.27:4012
::
:: NOTE: Server keeps running after automation finishes.
::       To stop manually: taskkill /IM python.exe /F
:: ============================================================

set SCRIPT_DIR=%~dp0
set SERVER_DIR=%SCRIPT_DIR%casb_server
set MY_IP=
set MANUAL_SERVER_URL=

:: ── Check if --server-url was manually passed ─────────────────
set ALL_ARGS=%*
echo %ALL_ARGS% | find /i "--server-url" >nul 2>&1
if %errorLevel%==0 (
    echo [OK] Using manually provided --server-url
    set MANUAL_SERVER_URL=1
)

:: ── Activate venv if present ─────────────────────────────────
if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
    echo [OK] Virtual environment activated
)

:: ── Auto-detect RDP IP only if --server-url not provided ─────
if defined MANUAL_SERVER_URL goto :start_server

for /f "tokens=2" %%a in ('netstat -n ^| find ":3389" ^| find "ESTABLISHED"') do (
    for /f "tokens=1 delims=:" %%b in ("%%a") do (
        set MY_IP=%%b
        goto :ip_found
    )
)

:: Fallback: pick 10.196.x.x from ipconfig
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| find "IPv4" ^| find "10.196."') do (
    set MY_IP=%%a
    goto :ip_found
)

:: Last resort: pick first 10.x.x.x
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| find "IPv4" ^| find "10."') do (
    set MY_IP=%%a
    goto :ip_found
)

:ip_found
set MY_IP=%MY_IP: =%
set SERVER_URL=http://%MY_IP%:4012
echo [OK] Detected RDP IP: %MY_IP%
echo [OK] Server URL: %SERVER_URL%
goto :start_server

:start_server
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

:: ── Run CASB automation ───────────────────────────────────────
echo.
echo ========================================================
echo   Running CASB Automation...
if defined MANUAL_SERVER_URL (
    echo   Uploading results to: manually provided --server-url
) else (
    echo   Uploading results to: %SERVER_URL%
)
echo ========================================================

if defined MANUAL_SERVER_URL (
    python "%SCRIPT_DIR%run.py" %*
) else (
    python "%SCRIPT_DIR%run.py" --server-url %SERVER_URL% %*
)
set AUTOMATION_EXIT=%errorLevel%

:: ── Automation done — server stays alive ─────────────────────
echo.
echo ========================================================
echo   Automation finished!
if defined MANUAL_SERVER_URL (
    echo   Results available at: your provided --server-url
) else (
    echo   Results available at: %SERVER_URL%
)
echo   Server is still running. To stop it manually:
echo     taskkill /IM python.exe /F
echo ========================================================
echo.

exit /b %AUTOMATION_EXIT%

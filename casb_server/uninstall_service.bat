@echo off
:: ============================================================
:: CASB Results Server — Service Uninstaller
:: Run this as Administrator
:: ============================================================

echo.
echo ========================================================
echo   CASB Results Server — Service Uninstaller
echo ========================================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Please run as Administrator.
    pause
    exit /b 1
)

set SERVICE_NAME=CASBResultsServer

:: Try NSSM first
where nssm >nul 2>&1
if %errorLevel% equ 0 (
    nssm stop %SERVICE_NAME% >nul 2>&1
    nssm remove %SERVICE_NAME% confirm >nul 2>&1
    echo [OK] Service removed via NSSM
) else (
    schtasks /end /tn "%SERVICE_NAME%" >nul 2>&1
    schtasks /delete /tn "%SERVICE_NAME%" /f >nul 2>&1
    echo [OK] Task Scheduler task removed
)

echo.
echo ========================================================
echo   CASB Results Server service has been removed.
echo   Your result files are still safe on disk.
echo ========================================================
echo.
pause

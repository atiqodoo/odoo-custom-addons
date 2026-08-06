@echo off
setlocal EnableExtensions

set SERVICE_NAME=OdooPOSPrintBridge
set BRIDGE_DIR=%~dp0
set BRIDGE_DIR=%BRIDGE_DIR:~0,-1%
set LOG_DIR=%BRIDGE_DIR%\logs
set NSSM=%BRIDGE_DIR%\nssm.exe
set BRIDGE_EXE=%BRIDGE_DIR%\pos_print_bridge.exe

if not exist "%NSSM%" (
    echo nssm.exe was not found in %BRIDGE_DIR%
    pause
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if exist "%BRIDGE_EXE%" (
    set APP_EXE=%BRIDGE_EXE%
    set APP_ARGS=--host 127.0.0.1 --port 9109
) else (
    where py.exe >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set APP_EXE=py.exe
        set APP_ARGS=-3 "%BRIDGE_DIR%\pos_print_bridge.py" --host 127.0.0.1 --port 9109
    ) else (
        where python.exe >nul 2>nul
        if %ERRORLEVEL% NEQ 0 (
            echo Neither pos_print_bridge.exe nor Python was found. Replace this folder with the latest bridge package.
            pause
            exit /b 1
        )
        set APP_EXE=python.exe
        set APP_ARGS="%BRIDGE_DIR%\pos_print_bridge.py" --host 127.0.0.1 --port 9109
    )
)

"%NSSM%" status "%SERVICE_NAME%" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Service %SERVICE_NAME% already exists. Updating settings...
) else (
    "%NSSM%" install "%SERVICE_NAME%" "%APP_EXE%"
)

"%NSSM%" set "%SERVICE_NAME%" Application "%APP_EXE%"
"%NSSM%" set "%SERVICE_NAME%" AppParameters %APP_ARGS%
"%NSSM%" set "%SERVICE_NAME%" AppDirectory "%BRIDGE_DIR%"
"%NSSM%" set "%SERVICE_NAME%" DisplayName "Odoo POS Print Bridge"
"%NSSM%" set "%SERVICE_NAME%" Description "Local RAW ESC/POS print bridge for Odoo POS receipts."
"%NSSM%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%NSSM%" set "%SERVICE_NAME%" AppStdout "%LOG_DIR%\bridge.out.log"
"%NSSM%" set "%SERVICE_NAME%" AppStderr "%LOG_DIR%\bridge.err.log"
"%NSSM%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM%" set "%SERVICE_NAME%" AppRotateOnline 1
"%NSSM%" set "%SERVICE_NAME%" AppRotateBytes 1048576
"%NSSM%" set "%SERVICE_NAME%" AppThrottle 1500

"%NSSM%" start "%SERVICE_NAME%"

echo.
echo Installed and started %SERVICE_NAME%.
echo Test in Chrome: http://127.0.0.1:9109/health
echo Logs: %LOG_DIR%
pause

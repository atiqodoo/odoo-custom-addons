@echo off
setlocal
set SERVICE_NAME=OdooPOSPrintBridge
set NSSM=%~dp0nssm.exe

if not exist "%NSSM%" (
    echo nssm.exe was not found.
    pause
    exit /b 1
)

"%NSSM%" stop "%SERVICE_NAME%"
"%NSSM%" remove "%SERVICE_NAME%" confirm

echo Removed %SERVICE_NAME%.
pause

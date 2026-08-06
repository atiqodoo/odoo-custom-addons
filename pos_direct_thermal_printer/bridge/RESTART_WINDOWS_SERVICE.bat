@echo off
setlocal
set SERVICE_NAME=OdooPOSPrintBridge
set NSSM=%~dp0nssm.exe

"%NSSM%" restart "%SERVICE_NAME%"
pause

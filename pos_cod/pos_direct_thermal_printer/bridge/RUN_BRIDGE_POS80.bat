@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0pos_print_bridge.exe" (
    "%~dp0pos_print_bridge.exe" --host 127.0.0.1 --port 9109
) else (
    python pos_print_bridge.py --host 127.0.0.1 --port 9109
)
pause

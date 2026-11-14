@echo off
setlocal
cd /d "%~dp0"

if exist "ScreenAnswer.exe" (
    start "" "ScreenAnswer.exe" %*
    exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app.py" %*
    exit /b 0
)

where pythonw.exe >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please run ScreenAnswer.exe or install Python 3.10+.
    pause
    exit /b 1
)

start "" pythonw.exe "app.py" %*

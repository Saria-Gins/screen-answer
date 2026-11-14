@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "app.py" %*
) else (
    python "app.py" %*
)

echo.
echo App exited. Check the messages above.
pause

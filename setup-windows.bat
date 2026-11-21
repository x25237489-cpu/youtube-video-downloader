@echo off
setlocal
cd /d "%~dp0"
echo.
echo  FRAME - First-time setup
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 (
    echo Setup could not find Python. Install Python 3.10 or newer from python.org and try again.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo  Setup complete! Double-click START-FRAME.bat to launch.
echo  For 1080p+ and MP3, install FFmpeg and add it to PATH.
pause
exit /b 0
:failed
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1

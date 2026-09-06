@echo off
setlocal

cd /d "%~dp0\.."

py -3.12 -m venv .venv
if errorlevel 1 (
  echo Python 3.12 is required. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -e ".[ui]"
if errorlevel 1 goto :failed

echo Setup complete. You can now run ui\launch_windows.bat.
pause
exit /b 0

:failed
echo Setup failed. Review the error messages above.
pause
exit /b 1

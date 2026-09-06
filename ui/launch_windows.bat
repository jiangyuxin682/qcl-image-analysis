@echo off
setlocal

cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ui\app.py
  goto :eof
)

where conda >nul 2>nul
if %errorlevel% equ 0 (
  conda run -n qcl python ui\app.py
  goto :eof
)

echo QCL UI environment was not found. Run ui\setup_windows.bat first.
pause

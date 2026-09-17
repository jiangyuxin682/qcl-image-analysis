@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build_windows.ps1"
if errorlevel 1 (
  echo Build failed. Review the error above.
  pause
  exit /b 1
)
echo The Windows application ZIP is ready in the dist folder.
pause

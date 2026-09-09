@echo off
rem Launch the independent processing interface with the existing project environment.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ui\app_processing.py
) else (
  conda run --no-capture-output -n qcl python ui\app_processing.py
)
if errorlevel 1 pause

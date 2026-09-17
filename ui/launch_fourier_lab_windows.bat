@echo off
rem Launch the independent Fourier laboratory in the existing environment.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ui\app_fourier_lab.py
) else (
  conda run --no-capture-output -n qcl python ui\app_fourier_lab.py
)
if errorlevel 1 pause

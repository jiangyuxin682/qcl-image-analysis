#!/bin/zsh

set -e

QCL_UI_DIR="${0:A:h}"
QCL_PROJECT_DIR="${QCL_UI_DIR:h}"
cd "$QCL_PROJECT_DIR"

if command -v python3.12 >/dev/null 2>&1; then
  QCL_PYTHON=python3.12
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
  QCL_PYTHON=python3
else
  echo "Python 3.12 is required. Install it from https://www.python.org/downloads/"
  read -r "?Press Return to close."
  exit 1
fi

"$QCL_PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[ui]"

echo "Setup complete. You can now run ui/launch_macos.command."
read -r "?Press Return to close."

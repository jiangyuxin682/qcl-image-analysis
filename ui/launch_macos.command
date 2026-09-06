#!/bin/zsh

set -e

QCL_UI_DIR="${0:A:h}"
QCL_PROJECT_DIR="${QCL_UI_DIR:h}"
QCL_MPL_DIR="${TMPDIR:-/tmp}/qcl-ui-matplotlib"

mkdir -p "$QCL_MPL_DIR"
export MPLCONFIGDIR="$QCL_MPL_DIR"
cd "$QCL_PROJECT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  exec .venv/bin/python ui/app.py
fi

if command -v conda >/dev/null 2>&1; then
  exec conda run -n qcl python ui/app.py
fi

echo "QCL UI environment was not found. Run ui/setup_macos.command first."
read -r "?Press Return to close."
exit 1

#!/bin/zsh
# Launch the independent processing workbench using the existing project environment.
set -e
QCL_PROCESS_UI_DIR="${0:A:h}"
cd "${QCL_PROCESS_UI_DIR:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python ui/app_processing.py
fi
if command -v conda >/dev/null 2>&1; then
  exec conda run --no-capture-output -n qcl python ui/app_processing.py
fi
# Finder may not inherit the shell's conda initialization.
for QCL_PROCESS_PYTHON in "$HOME/miniconda3/envs/qcl/bin/python" "$HOME/anaconda3/envs/qcl/bin/python" "$HOME/miniforge3/envs/qcl/bin/python"; do
  if [[ -x "$QCL_PROCESS_PYTHON" ]]; then
    exec "$QCL_PROCESS_PYTHON" ui/app_processing.py
  fi
done
echo "Activate the qcl environment, then run: python ui/app_processing.py"
read -r "?Press Return to close."

#!/bin/zsh
set -e
QCL_FOURIER_UI_DIR="${0:A:h}"
cd "${QCL_FOURIER_UI_DIR:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python ui/app_fourier_lab.py
fi
if command -v conda >/dev/null 2>&1; then
  exec conda run --no-capture-output -n qcl python ui/app_fourier_lab.py
fi
for QCL_FOURIER_PYTHON in "$HOME/miniconda3/envs/qcl/bin/python" "$HOME/anaconda3/envs/qcl/bin/python" "$HOME/miniforge3/envs/qcl/bin/python"; do
  if [[ -x "$QCL_FOURIER_PYTHON" ]]; then
    exec "$QCL_FOURIER_PYTHON" ui/app_fourier_lab.py
  fi
done
echo "Activate the qcl environment, then run: python ui/app_fourier_lab.py"
read -r "?Press Return to close."

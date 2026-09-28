# QCL Image Analysis

Process QCL microscopy images, compare datasets, and save reproducible processing projects locally. The current **QCL Processing Workbench** (`ui/app_processing.py`) runs in your browser, with computation and files on your own computer.

## Start here

Read these guides in order:

1. **[Beginner installation guide: macOS / Windows](ui/INSTALLATION.md)**: obtaining the source, installing Python 3.12, creating an environment, installing dependencies, launching, FFmpeg, and troubleshooting.
2. **[User guide](ui/QUICKSTART.md)**: raw CSV input, Sections 1–10, CNR, timelapse, folder comparison, exporting, and reproducing an analysis.
3. **[Processing reference](ui/README_PROCESSING.md)**: detailed parameters, algorithms, output files, and verification.

## Installation and updates

Follow [the installation guide](ui/INSTALLATION.md) in order:

1. Fork the upstream repository into your GitHub account.
2. Prepare Git in the VS Code terminal and clone your fork.
3. Install Python 3.12 using WinGet on Windows or Homebrew on macOS.
4. Create the project-local `.venv`, install `.[ui]`, and run `pip check`.
5. Launch using the explicit environment path below.

The guide includes every command, first-time package-manager setup, optional
FFmpeg installation, troubleshooting, and **Sync fork → git pull** updates.
Python must be **>=3.12 and <3.13**. Do not copy `.venv` between computers.

After installation, launch from the project root:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe ui\app_processing.py
```

macOS:

```bash
.venv/bin/python ui/app_processing.py
```

Open **http://127.0.0.1:8766** if the browser does not open automatically.
Keep the terminal running. Export before pressing Ctrl+C to stop the app;
sessions are not saved automatically. Closing the last UI tab normally stops the
CLI server after 10 seconds. Ctrl+C also stops it; automatic tab closure depends
on browser permissions, with a stopped-server message as fallback. Subsequent sessions require only the
launch command. A processing project ZIP is an analysis archive, not an installer.

## Current processing workflow

```text
Raw intensity → optional gold normalization → on-MS crop
→ optional Fourier → optional rolling-ball → absorbance
→ optional baseline correction per center → CNR
→ optional timelapse → processing project ZIP
```

Inputs are normally `lineScan_<integer wavenumber>_0invcm.csv` files in pattern folders. Select a local acquisition/stacks/pattern folder, or multiple CSV bands from one pattern. Section 8 provides stage images, independent colorbars, CNR, display flips, line profiles, and PNG downloads.

In the multi-folder workspace, double-click a tab to rename it and use its × button to remove it. Parameter sharing defaults off in Sections 2 and 5, and on in Sections 3 and 6; spatial ROIs remain independent. Final comparison defaults to a separate wavenumber for each folder and offers optional shared color limits for the current stage, including manual limits. If comparison is blocked, diagnostics identify the affected folders and sections.

**Exports default to lightweight projects without full raw image arrays.** Reproduction requires matching external raw data unless you include raw inputs in the export. Stage CSVs and auxiliary arrays are optional; required reproduction settings always remain included. Saved settings can also be applied to new raw data, with new spatial selections. Project import limits are 1 GiB compressed and 4 GiB expanded. Download PNGs and MP4s separately as needed.

## Other interfaces

- [Original Image Workbench (legacy)](ui/README.md): `ui/app.py`, default port 8765, with the older independent on-MS/out-MS workflow.
- [Fourier Image Lab](ui/README_FOURIER_LAB.md): `ui/app_fourier_lab.py`, default port 8767, for experiments and filter inspection.

## Development and notebooks

| Directory | Contents |
| --- | --- |
| `src/qcl_analysis/` | Numerical processing functions |
| `ui/` | Local interfaces, import/export, launchers, and user documentation |
| `notebooks/` | Exploration and validation |
| `tests/` | Numerical, API, and browser-state helper tests |
| `packaging/` | Internal build tooling; not part of user installation |

For development, install `python -m pip install -e ".[dev,ui]"` in a Python 3.12 environment and run `python -m pytest`. When using the environment above, replace `python` with `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` on Windows.

Browser helper tests are in `tests/test_*.cjs`. With Node.js installed, run each using `node tests/<test_filename>.cjs`. **Node.js is not needed to run the workbench.**

Notebook users can install `python -m pip install -e ".[notebook,ui]"` and select this Python environment in their notebook editor. This extra installs kernel/widget dependencies, not the JupyterLab application; install JupyterLab separately if needed. First-time image analysis users should start with the Processing UI.

Keep research inputs and exported results outside the source folder, or in the Git-ignored `data/` and `outputs/` directories. [pyproject.toml](pyproject.toml) defines the Python dependency requirements.

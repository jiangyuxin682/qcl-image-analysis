# QCL Image Workbench

A local, browser-based UI for the `03_raw_to_absorbance.ipynb` workflow. It
uses the existing `qcl_analysis` package for indexing, QC, reflectance, cropping,
R0, and absorbance calculations.

## First-time setup

- macOS: double-click `setup_macos.command`.
- Windows: double-click `setup_windows.bat`.

The setup creates a project-local `.venv` and installs the project with its UI
dependencies. Python 3.12 is required.

## Run

- macOS: double-click `launch_macos.command`.
- Windows: double-click `launch_windows.bat`.

Or, from the repository root:

```bash
python ui/app.py
```

The app opens at <http://127.0.0.1:8765>. All processing stays on the local
computer. Press `Ctrl+C` in the terminal to stop it.

## Workflow

1. Index a `stacks` folder and calculate gold-reference QC.
2. Inspect raw MCT images, brightest reference pixels, and reference stability.
3. Select non-overlapping on-MS and out-MS regions.
4. Select independent cell-free R0 regions inside both crops.
5. Calculate, review, and sanity-check absorbance results.
6. Build a timelapse for a selected region, wavenumber, and pattern range.
7. Export the analysis results.

The downloaded ZIP contains reflectance and absorbance CSV arrays, QC tables,
R0 values, reference-region checks, ROI coordinates, and processing metadata.

The last successfully indexed stacks path is remembered only in the local
browser. Set `QCL_STACKS_DIR` before launching to provide a machine-specific
default without committing personal paths to Git.

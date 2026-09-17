# QCL Image Analysis

Python tools and a local browser interface for processing QCL microscopy
images from raw MCT intensity to reflectance and absorbance.

## Processing model

The current workflow follows:

```text
I_raw -> I_goldref -> R -> on-MS / out-MS -> R0 -> A
```

where each pattern and wavenumber receives its own gold-reference signal and
its own region-specific reference reflectance. Absorbance is calculated as:

```text
A = -log10(R / R0)
```

The on-MS and out-MS regions are normalized independently.

## Project layout

- `src/qcl_analysis/`: reusable image-processing functions.
- `notebooks/`: step-by-step exploration and validation notebooks.
- `ui/`: local QCL Image Workbench and cross-platform launchers.
- `tests/`: automated tests for processing and UI helpers.

## QCL Image Workbench

### Current Processing UI and Windows app

For an independent synthetic-image and Fourier-filter experiment interface,
run `python ui/app_fourier_lab.py` (port 8767). It supports constant-width letters
with square/rounded corners, noise, imported images, interactive notch selection,
and before/after spectra. See [Fourier Image Lab](ui/README_FOURIER_LAB.md).

The current eight-section processing interface is `ui/app_processing.py`.
After selecting spectral bands, choose whether a gold patch reference is
available. With gold, inspect the normalization pixels and reflectance preview;
without gold, crop and correct raw intensity directly before absorbance.
For source installs on Windows, run `ui/setup_windows.bat` once, then
`ui/launch_processing_windows.bat`. It opens at `http://127.0.0.1:8766`.

For a standalone Windows application requiring no Python or VS Code on the
user's computer, see [Windows packaging](packaging/README.md). A Windows builder
can double-click `build_windows.bat`, or use the **Build Windows app** GitHub
Actions workflow to produce the tested application ZIP.

The instructions below describe the original `ui/app.py` interface.

The UI runs locally and opens in a web browser. Images and results remain on
the computer; `127.0.0.1` is not a public internet address.

### Existing Conda environment

If the `qcl` environment is already installed:

```bash
conda activate qcl
python ui/app.py
```

Then open <http://127.0.0.1:8765>.

### First-time setup on macOS

1. Install Python 3.12 if it is not already available.
2. Double-click `ui/setup_macos.command` once.
3. Double-click `ui/launch_macos.command` whenever you want to use the UI.

### First-time setup on Windows

1. Install Python 3.12 from Python.org and enable the Python launcher.
2. Double-click `ui/setup_windows.bat` once.
3. Double-click `ui/launch_windows.bat` whenever you want to use the UI.

The setup scripts create a `.venv` inside the repository and install
`.[ui]`. This environment is excluded from Git.

## UI workflow

1. Select a `stacks` directory and run dataset indexing/QC.
2. Inspect raw MCT images, brightest gold-reference pixels, and reference
   stability.
3. Draw non-overlapping on-MS and out-MS regions.
4. Draw independent cell-free R0 regions inside the two crops.
5. Calculate absorbance and review the reference-region checks.
6. Build an on-MS or out-MS timelapse for a chosen wavenumber and pattern
   range, with playback speed and QC-frame controls.
7. Download the results ZIP.

The ZIP contains reflectance and absorbance arrays, QC flags, R0 summaries,
reference-region checks, ROI coordinates, and processing metadata.

## Development

Install development and UI dependencies:

```bash
python -m pip install -e ".[dev,ui]"
```

Run the test suite:

```bash
pytest
```

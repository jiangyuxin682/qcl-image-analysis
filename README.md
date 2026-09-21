# QCL Image Analysis

Local tools for processing QCL microscopy images, comparing datasets, and
exporting self-contained processing projects that can be reproduced later.
Images and processing remain on your computer; the browser connects to a local
server, not a hosted service.

## Start here

The current **QCL Processing Workbench** is `ui/app_processing.py`, with ten
sections from import to export.

- **[New-user quick start](ui/QUICKSTART.md)** — installation, first dataset,
  comparison, saving and reopening a project, and troubleshooting.
- **[Processing reference](ui/README_PROCESSING.md)** — scientific parameters,
  selection rules, CNR, line profiles, and reproduction details.
- **[Windows desktop distribution](packaging/README.md)** — using and building
  the standalone application, which requires no Python installation.

### Run from source

Python **3.12** is required. From a complete checkout:

| Platform | First-time setup | Start the current workbench |
| --- | --- | --- |
| macOS | `ui/setup_macos.command` | `ui/launch_processing_macos.command` |
| Windows | `ui/setup_windows.bat` | `ui/launch_processing_windows.bat` |

The setup scripts create a repository-local `.venv` and install UI dependencies.
Alternatively, in an activated Python 3.12 environment, from the repository root:

```bash
python -m pip install -e ".[ui]"
python ui/app_processing.py
```

Open <http://127.0.0.1:8766>. Keep the server terminal open while using the app.
Export your project before stopping the server or reloading the workspace.

## Processing workflow

```text
Raw intensity → optional gold normalization → on-MS crop
→ optional Fourier filtering → optional rolling-ball correction
→ absorbance → spectral baseline correction → CNR
→ optional timelapse → reproducible project ZIP
```

Without gold, processing uses raw intensity. Absorbance uses each corrected
image's own analyte-free reference mean. Section 8 compares the processing
stages and provides horizontal or vertical line profiles.

Choose a local data folder with the system folder chooser; it is read directly
without a browser upload size limit. Selected CSV files are streamed to disk. For multiple
folders, open the dataset-tab workspace; spectral mappings, gold normalization,
filter settings, and analyte-free selection methods are shared by default.
Spatial selections remain independent between folders. Final comparison uses
independent color scales and offers a line profile for each folder.

Section 10 exports numerical results, full raw inputs for the selected
patterns/bands, effective parameters, reference selections, and environment
information. Choose a ZIP filename before downloading. Use **Import processing
ZIP → Reproduce processing** to recalculate and verify a saved project without
the original source directory. Multi-folder exports can be imported into the
comparison workspace. See the quick start for what is and is not restored.

## Other interfaces

- [Original Image Workbench](ui/README.md): `python ui/app.py`, port 8765;
  the legacy workflow with independent on-MS/out-MS regions.
- [Fourier Image Lab](ui/README_FOURIER_LAB.md):
  `python ui/app_fourier_lab.py`, port 8767; synthetic-image and filter experiments.

## Development

- `src/qcl_analysis/`: reusable numerical processing functions.
- `ui/`: local interfaces, project import/export, and launchers.
- `notebooks/`: exploration and validation workflows.
- `tests/`: processing, API, and browser-state helper tests.
- `packaging/`: standalone Windows build and runtime checks.

Install development dependencies and run Python tests:

```bash
python -m pip install -e ".[dev,ui]"
python -m pytest
```

With Node.js available, also run the browser helper tests directly:

```bash
node tests/test_line_profile_ui.cjs
node tests/test_processing_sharing.cjs
node tests/test_reproduction_ui.cjs
node tests/test_uploads_ui.cjs
```

Node.js is only needed for these tests, not to run the workbench. Save research
inputs and exported projects outside the checkout or in the ignored `data/`
and `outputs/` directories. Windows application builds have separate checks;
see the packaging guide before distributing an EXE.

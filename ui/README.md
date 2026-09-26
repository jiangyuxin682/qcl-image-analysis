# Original QCL Image Workbench (legacy)

For new analyses, use the current ten-section **Processing Workbench** on port
8766: [quick start](QUICKSTART.md) · [processing reference](README_PROCESSING.md).
This page documents the original `ui/app.py` on port 8765, including its separate
on-MS/out-MS workflow. Its result ZIPs are not the current reproducible project format.

A local, browser-based UI for the `03_raw_to_absorbance.ipynb` workflow. It
uses the existing `qcl_analysis` package for indexing, QC, reflectance, cropping,
R0, and absorbance calculations.

## Setup and launch

Complete the same [Fork/Clone installation guide](INSTALLATION.md) used by the
Processing Workbench. This interface reuses that `.venv`; no separate setup is needed.
From the project root, launch the legacy interface with:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe ui\app.py
```

macOS:

```bash
.venv/bin/python ui/app.py
```

The app opens at <http://127.0.0.1:8765>. Processing stays on the local computer.
Export before pressing Ctrl+C in the terminal to stop it.

## Workflow

1. Index a `stacks` folder and calculate gold-reference QC.
2. Inspect raw MCT images, brightest reference pixels, and reference stability.
3. Select non-overlapping on-MS and out-MS regions.
4. Select independent cell-free R0 regions inside both crops.
5. Calculate, review, and sanity-check absorbance results.
6. Build a timelapse for a selected region, wavenumber, and pattern range. The
   player shows the first and last file creation times, the median interval
   between selected frames, and the current frame's elapsed time from the first
   frame.
7. Export the analysis results.

The downloaded ZIP contains reflectance and absorbance CSV arrays, QC tables,
R0 values, reference-region checks, ROI coordinates, and processing metadata.

The last successfully indexed stacks path is remembered only in the local
browser. Set `QCL_STACKS_DIR` before launching to provide a machine-specific
default without committing personal paths to Git.

Timelapse acquisition times use the filesystem birth/creation time on macOS and
Windows. On filesystems that do not expose creation time, file modification time
is used as a fallback.

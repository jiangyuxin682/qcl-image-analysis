# Windows desktop distribution

The user distribution is a ZIP containing `QCL Processing.exe` and `_internal/`.
Users extract the whole ZIP and double-click the EXE. No Python, VS Code,
Conda, FFmpeg, or installation of Python packages is needed on their computers.
The EXE starts a small native controller and opens the existing processing UI
in the default browser. Use **Quit** in the controller to stop the application;
export results before quitting. Analysis sessions are held in memory.

## Using the workbench

Follow the [new-user quick start](../ui/QUICKSTART.md) for file-chooser imports,
the ten processing sections, multi-folder comparison, and exporting/reproducing
projects. The [processing reference](../ui/README_PROCESSING.md) explains the
numerical controls and verification report.

The **application distribution ZIP** contains the executable and must be extracted
to launch the app. A **processing project ZIP** is created inside the app by
Section 10 (or Export all datasets); import it with the processing ZIP chooser
to reproduce an analysis. These are different files. Updating the source does
not update an existing EXE: build a new Windows distribution for new features.

## Build on Windows

The builder needs Windows x64, Python 3.12 x64 with the `py` launcher, this entire
repository, and an internet connection for the first dependency installation.
End users do not need these build tools.

Double-click `build_windows.bat` at the project root. Or, from PowerShell:

```powershell
.\build_windows.bat
```

It creates a separate `.venv-build` environment, runs the source tests, builds
the directory bundle with PyInstaller, tests the actual EXE from a different
working directory, then writes:

```text
dist/QCL-Processing-Windows-x64-<timestamp>.zip
dist/QCL-Processing-Windows-x64-<timestamp>.zip.sha256
```

Every build uses a new output directory. A failed test prevents ZIP creation.
The packaged check exercises Tcl/Tk, all static pages, a Unicode CSV path,
the image pipeline (including rolling ball), ROI spectral filters, CNR,
PNG/ZIP export, and the bundled H.264 encoder. `BUILD_CHECK.json` and
`BUILD_DEPENDENCIES.txt` accompany the application.

## Build with GitHub Actions

Once these files are committed and pushed to GitHub:

1. Open **Actions → Build Windows app → Run workflow**.
2. Wait for the Windows job to pass.
3. Download the **QCL-Processing-Windows-x64** artifact.
4. Extract the artifact wrapper to obtain the application ZIP and checksum.
5. Give the application ZIP to the Windows user.

The workflow runs on manual request or a push to the dedicated
`build/windows-app` branch; it does not publish a release.
Its token has read-only repository permission. A source ZIP downloaded from
GitHub is not the compiled application.

## Runtime details

- The server binds only to `127.0.0.1`. If port 8766 is busy, it selects a free
  port and displays the new address. Existing sessions are not displaced.
- Each launched process owns an independent session. Closing the browser alone
  leaves it running; the controller can reopen it.
- Static resources use bundled module-relative paths, independent of the
  current directory. Matplotlib uses Agg; its cache and rotating application
  log are written to `%LOCALAPPDATA%/QCL Processing`.
- FFmpeg is bundled from the `imageio-ffmpeg` wheel. It is resolved from the
  bundle first; source installs retain their system-FFmpeg behavior.
- NumPy, SciPy, pandas, Matplotlib, Pillow and scikit-image are collected.
  scikit-image's lazy imports and stub files are included explicitly.
- The package is unsigned. Code signing and an installer are not configured.

Windows binaries must be built and tested on Windows. A successful macOS
source test is not a successful Windows EXE test. No Windows binary exists
until the Windows build finishes and produces the ZIP above.

To transfer the build sources from this Mac to a Windows builder, run
`python packaging/make_build_kit.py`. It creates
`dist/QCL-Processing-Windows-BuildKit.zip`, containing source code and build
tools (not an EXE). Extract it on Windows and run `build_windows.bat`.

References: [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html),
[bundled resource paths](https://pyinstaller.org/en/stable/runtime-information.html),
[FFmpeg wheels](https://github.com/imageio/imageio-ffmpeg).

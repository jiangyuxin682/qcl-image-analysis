# Install QCL Processing Workbench from scratch: macOS / Windows

After installation, follow the [user guide](QUICKSTART.md) to process your first dataset. This guide covers the current ten-section interface and assumes no programming experience. Button names match the English interface.

## 1. Identify the files you received

| What you received | How to use it |
| --- | --- |
| Source folder containing `pyproject.toml`, `src`, and `ui` | Follow the macOS or Windows source installation below |
| Windows application ZIP containing `QCL Processing.exe` and `_internal` | Follow Section 4; no Python installation is needed |
| A processing project ZIP exported from the app | This is an analysis project, not an installer; start the app before importing it |
| `QCL-Processing-Windows-BuildKit.zip` | This contains build sources, not a ready-to-run EXE; you can run it using the Windows source instructions |

Obtain the **complete source ZIP** from the maintainer, or choose **Code → Download ZIP** in the [project repository](https://github.com/jiangyuxin682/qcl-image-analysis) if you have access. Extract everything before continuing. Do not download only one `.py` file. You can keep the project under Documents; keep raw data and exported results in separate folders.

Paths below are examples: substitute the actual location of your extracted project. Copy commands one line at a time and press Enter. Continue only after the preceding command finishes without an error. Do not copy surrounding explanatory text. A terminal is the operating system's command window, not a web page or Python's `>>>` prompt. If you see `>>>`, enter `exit()` before running these commands.

## 2. macOS source installation

### 2.1 Install Python 3.12

This project requires **Python >=3.12 and <3.13**. Python 3.13/3.14 cannot substitute for 3.12. Do not modify the Python supplied with macOS.

1. Open the [official Python 3.12.10 download page](https://www.python.org/downloads/release/python-31210/). Under Files, select **macOS 64-bit universal2 installer**, which supports Intel and Apple Silicon Macs. Version 3.12.10 provides a traditional installer; it is not the latest security revision. If you already have a newer 3.12.x environment, you can use it.
2. Open the downloaded `.pkg` and complete the installation wizard.
3. Press Command + Space, search for **Terminal**, and open it. Enter:

```bash
python3.12 --version
```

Continue when you see `Python 3.12.x`. If the command is not found, reopen Terminal and check that installation completed.

### 2.2 Open the project folder in Terminal

Type `cd `, including the trailing space, drag the extracted project folder from Finder into Terminal, and press Enter. Alternatively, enter its actual path, for example:

```bash
cd "$HOME/Documents/qcl-image-analysis"
ls
```

The listing should contain `pyproject.toml`, `src`, and `ui`. If it does not, correct the folder path before continuing.

### 2.3 Create the environment and install dependencies

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[ui]"
.venv/bin/python -m pip check
```

`.venv` is a dedicated Python environment for this project. Finder may hide it by default; that is normal. The first installation downloads dependencies, so wait for the command prompt to return. The final command should report `No broken requirements found.`

Alternatively, run `zsh ui/setup_macos.command` from the same project folder instead of the four commands above. You only need one installation method.

### 2.4 Start the app

```bash
.venv/bin/python ui/app_processing.py
```

Your browser should open **http://127.0.0.1:8766** automatically. If it does not, paste that address into your browser. The **QCL Processing Workbench** import screen indicates a successful launch. It is normal for Terminal to remain occupied by server logs; keep it open while using the app.

For later sessions, return to the same folder and run the launch command again, or use `zsh ui/launch_processing_macos.command`. Reinstallation is not required. If double-clicking the `.command` file fails because it is not executable, run `chmod +x ui/launch_processing_macos.command` from the project root and retry. Launching through `zsh` does not require that step.

## 3. Windows source installation

These instructions target Windows 10/11 on Intel/AMD 64-bit computers. Windows ARM has not been validated for this project's application distribution.

### 3.1 Install Python 3.12

1. Open the [official Python 3.12.10 download page](https://www.python.org/downloads/release/python-31210/). In the **Files table**, choose **Windows installer (64-bit)**, not the embeddable package or source tarball. Version 3.12.10 provides a traditional installer; an existing newer 3.12.x environment also works.
2. Open the installer, select **Add python.exe to PATH**, and retain the pip, Python launcher (`py`), and Tcl/Tk components. Complete installation.
3. Search for **PowerShell** in the Start menu and open a new window. Enter:

```powershell
py -3.12 --version
```

You should see `Python 3.12.x`. If `py` is not found, reopen PowerShell. If it still fails, use the installer's Modify/Repair options to check the launcher. Do not substitute a `python` command without checking its version.

### 3.2 Open the project folder in PowerShell

Right-click the source ZIP and choose **Extract All**. In File Explorer, open the extracted folder containing `pyproject.toml`. Click the address bar and copy its path. In PowerShell, enter the following, replacing the quoted path:

```powershell
Set-Location "C:\Users\YourName\Documents\qcl-image-analysis"
Get-ChildItem
```

The listing should contain `pyproject.toml`, `src`, and `ui`. Documents may be under OneDrive on your computer; use the actual path shown in File Explorer.

### 3.3 Create the environment and install dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[ui]"
.\.venv\Scripts\python.exe -m pip check
```

The last command should report `No broken requirements found.` These commands call the environment's Python directly: **you do not need Activate.ps1 or a change to PowerShell execution policy**. See the [Python virtual environment documentation](https://docs.python.org/3.12/library/venv.html).

Alternatively, double-click `setup_windows.bat` in the project's `ui` folder. Resolve any errors before proceeding; a Done message alone does not establish that every installation step succeeded.

### 3.4 Start the app

```powershell
.\.venv\Scripts\python.exe ui\app_processing.py
```

Your browser should open **http://127.0.0.1:8766**. Open that address manually if necessary. Keep PowerShell open while working.

For subsequent sessions, double-click `ui\launch_processing_windows.bat`, or return to the project folder and run the launch command above. You do not need to reinstall each time.

## 4. Using an existing Windows application package

If the maintainer supplied a **built and checked Windows application ZIP**:

1. Right-click it and choose Extract All into a normal folder.
2. Keep `QCL Processing.exe` beside the entire `_internal` folder. Do not copy just the EXE.
3. Double-click the EXE. A small controller opens your browser and displays the current address. If the default port is occupied, the packaged app selects another port.
4. Use **Open analysis UI** to reopen the browser. Export your work before choosing **Quit**.

This package includes Python, runtime dependencies, and FFmpeg. Updating source files does not update an older EXE; obtain a new build from the maintainer. The package may be unsigned; proceed through an operating-system warning only after confirming its trusted source. Maintainer instructions are in [Windows packaging](../packaging/README.md).

## 5. What the dependencies do

`pip install -e ".[ui]"` installs the dependencies declared in [pyproject.toml](../pyproject.toml). You do not need to install these packages individually.

| Dependency | Purpose |
| --- | --- |
| NumPy, SciPy | Arrays, scientific calculations, and filtering |
| pandas | Tables and result export |
| Matplotlib | Plotting |
| PyYAML | Configuration input/output |
| scikit-image (>=0.25, <0.27) | Image processing, including rolling-ball |
| Pillow (`ui` extra) | Image input/output and PNG generation |
| Tcl/Tk (Python installation component) | Native windows such as the Windows folder chooser |
| FFmpeg executable (optional) | MP4 export; not required for ordinary image processing |

Normal use does not require Node.js, VS Code, Git, Jupyter, or Conda. See the root [README](../README.md) for development and notebook extras. Do not copy `.venv` from another computer or operating system; create it on the current computer.

## 6. Install FFmpeg when you need MP4 export

Source installation does not install the FFmpeg executable automatically. You can process images first and install FFmpeg later. Running `pip install ffmpeg` alone does not replace this step.

### macOS

If Homebrew is installed, run:

```bash
brew install ffmpeg
ffmpeg -version
```

Otherwise, open the [Homebrew website](https://brew.sh/), copy its installation command into Terminal, and follow its prompts. Complete the installer's **Next steps**, including adding Homebrew to PATH. Reopen Terminal and run the two commands above. See the [Homebrew FFmpeg page](https://formulae.brew.sh/formula/ffmpeg).

### Windows

1. Open the [official FFmpeg download page](https://www.ffmpeg.org/download.html) and follow one of its **Windows EXE Files** provider links.
2. Download a precompiled ZIP for x64 Windows containing `ffmpeg.exe`, such as an essentials build. Do not download the source-code archive.
3. Extract the ZIP. Locate `ffmpeg.exe` in its `bin` folder, for example `C:\Tools\ffmpeg\bin\ffmpeg.exe`.
4. Search the Start menu for **Edit environment variables for your account**. Under user variables, select **Path → Edit → New** and enter the actual `bin` folder path, for example `C:\Tools\ffmpeg\bin`. Keep existing entries. Confirm each dialog with OK.
5. Close and reopen PowerShell, then run:

```powershell
ffmpeg -version
```

Once version information appears, restart QCL. If QCL still cannot find FFmpeg, verify the command works in a new terminal and launch QCL from that terminal.

## 7. Stopping, updating, and troubleshooting

Export a processing ZIP and keep the original raw data. For the source app, press **Ctrl+C** in its terminal to stop it; for the packaged app, choose **Quit**. Sessions are held in memory and are not automatically saved when you close the browser. Avoid refreshing the workspace or launching multiple instances during an analysis.

| Symptom | What to check |
| --- | --- |
| `requires a different Python` | Check that `.venv` was created with Python 3.12. If it uses another version, stop the app, rename `.venv` as a backup, and create a new environment using these instructions |
| `pyproject.toml` or another file is not found | Run commands from the project root; inspect `ls` or `Get-ChildItem` output |
| `ModuleNotFoundError` | Use the explicit `.venv` Python path and rerun `-m pip install -e ".[ui]"` |
| pip cannot download packages | Check network/proxy settings and retain the full error. Do not disable certificate verification. For certificate errors with the official macOS Python installer, try its `Install Certificates.command` under Applications/Python 3.12 |
| Browser cannot connect | Check the terminal is still running without startup errors and that the address matches its output. Enter the full `http://127.0.0.1:8766` address |
| `Address already in use` / `WinError 10048` | Another instance may be running. Use it, or export and stop it. Alternatively, use a different port as shown below |
| Choose folder does not show a dialog | Check behind the browser. On Windows, check the Python Tcl/Tk component. Alternatively, use CSV input and select all required bands |
| Slow processing or insufficient memory | Start with fewer patterns and necessary bands. Large images, rolling-ball, and multiple datasets require more memory and computation |
| Downloaded files are missing | Check browser download history and the Downloads folder. The browser controls the destination |

To launch on another port, use the command for your operating system:

```bash
# macOS
.venv/bin/python ui/app_processing.py --port 8776
```

```powershell
# Windows PowerShell
.\.venv\Scripts\python.exe ui\app_processing.py --port 8776
```

Then open **http://127.0.0.1:8776**. The source Processing UI does not automatically switch away from an occupied port.

Export before updating the source. Install dependencies from the new source root and launch there. Recreate `.venv` after moving or renaming the source folder. Keep older results and inspect the reproduction report; similar-looking images alone do not establish identical results.

When requesting help, include your operating system, Python version, source/application version or acquisition date, current Section, exact error text, the terminal's final error output, and minimal reproduction steps. Windows application logs are at `%LOCALAPPDATA%\QCL Processing\app.log`. You do not need to send your entire research dataset initially.

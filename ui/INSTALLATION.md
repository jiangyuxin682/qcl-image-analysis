# Install and update QCL Processing Workbench

Use this single workflow on both systems: **Fork → Clone → install Python 3.12 in a terminal → create `.venv` → install dependencies → launch**. Windows uses PowerShell and WinGet; macOS uses zsh and Homebrew. All commands below are run locally, not on GitHub.

You need a GitHub account, VS Code, an internet connection for installation, and access to the [upstream repository](https://github.com/jiangyuxin682/qcl-image-analysis). Install VS Code from its [official website](https://code.visualstudio.com/) if necessary. A processing ZIP exported by the app contains analysis settings/results, not the software.

Copy commands one line at a time. Wait for each to finish successfully before continuing. Do not type commands at a Python `>>>` prompt; enter `exit()` first if you see one. Skip installation steps for tools that are already installed at the required version. Do not copy another computer's `.venv`.

## 1. Fork the repository (both systems)

1. Sign in to your GitHub account and open the upstream repository above.
2. Click **Fork → Create a new fork**.
3. Choose your account as Owner, keep the repository name, and click **Create fork**.
4. In your fork, click **Code → HTTPS** and copy its URL. It should look like `https://github.com/YOUR-USERNAME/qcl-image-analysis.git`.

If the repository is private, you need access and permission to fork. Only code pushed to GitHub is available to you; unpublished changes on another computer are not included.

## 2. Prepare Git in the VS Code terminal

Open VS Code and choose **Terminal → New Terminal**. Use PowerShell on Windows and zsh on macOS. If installing a tool changes PATH, close all VS Code windows and reopen the app before checking it again.

### Windows

Check Git:

```powershell
git --version
```

If Git is not found, check WinGet:

```powershell
winget --version
```

If WinGet is missing, install or update **App Installer** in Microsoft Store, then restart VS Code. WinGet is distributed with App Installer; see [Microsoft's instructions](https://learn.microsoft.com/en-us/windows/package-manager/winget/). If your organization blocks installation, ask its IT administrator to enable it.

Install Git if needed:

```powershell
winget install --id Git.Git --exact --source winget
```

Complete any prompts, restart VS Code, and run `git --version` again.

### macOS

Check Homebrew:

```bash
brew --version
```

If it is not installed, run the installation command from the [Homebrew website](https://brew.sh/):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Read and follow the prompts, including any Command Line Tools installation. When prompted for your Mac login password, typing may show no characters; this is normal. Run the exact **Next steps** commands printed by the installer to add Homebrew to your shell environment. The installation prefix differs between Apple Silicon and Intel Macs, so do not guess the path. Restart VS Code and verify `brew --version`. Check Homebrew's current macOS requirements if installation reports an unsupported system.

Check Git:

```bash
git --version
```

If Git is unavailable, install it, then verify:

```bash
brew install git
git --version
```

## 3. Clone your fork (both systems)

1. In VS Code, press **Ctrl + Shift + P** on Windows or **Command + Shift + P** on macOS.
2. Select **Git: Clone** and paste your fork's HTTPS URL from step 1.
3. Select a parent folder such as Documents; Git creates a `qcl-image-analysis` subfolder.
4. Complete GitHub sign-in if requested, then click **Open** when cloning finishes.
5. If VS Code shows Restricted Mode, trust the folder only after confirming this is the intended repository.

The Explorer should show `pyproject.toml`, `src`, and `ui`. If you already cloned this fork, open that folder rather than cloning it again.

## 4. Install Python 3.12

Open **Terminal → New Terminal** in the project. The project requires **Python >=3.12 and <3.13**. A VS Code Python extension does not install the interpreter, and a different Python version is not a substitute.

### Windows

Check the required version:

```powershell
py -3.12 --version
```

If unavailable, install it:

```powershell
winget install --id Python.Python.3.12 --exact --source winget
```

Finish installation prompts, close all VS Code windows, reopen the project, and open a new terminal. Verify again:

```powershell
py -3.12 --version
```

Continue only when it prints `Python 3.12.x`. If the launcher is still unavailable after restarting, retain the installation output and resolve that problem before proceeding. The package identifier is recorded in [Microsoft's WinGet manifests](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/12).

### macOS

Check the required version:

```bash
python3.12 --version
```

If unavailable, install it through Homebrew:

```bash
brew install python@3.12
```

Restart VS Code, reopen the project, and verify:

```bash
python3.12 --version
```

Continue only when it prints `Python 3.12.x`. Use the versioned command, not the macOS system Python. See the [Homebrew Python 3.12 formula](https://formulae.brew.sh/formula/python@3.12).

## 5. Create the project environment and install dependencies

Run commands from the **project root containing `pyproject.toml`**, not inside `ui`. Each command must succeed before the next one. `.venv` keeps the project's dependencies separate; activation is not needed.

### Windows PowerShell

Confirm the folder contents:

```powershell
Get-ChildItem
```

Then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[ui]"
.\.venv\Scripts\python.exe -m pip check
```

### macOS terminal

Confirm the folder contents:

```bash
ls
```

Then run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[ui]"
.venv/bin/python -m pip check
```

The final command should report **No broken requirements found.** There is no need to run Activate.ps1 or change PowerShell execution policy. Finder may hide `.venv`; that is normal.

The install command uses [pyproject.toml](../pyproject.toml) to install NumPy, SciPy, pandas, Matplotlib, PyYAML, scikit-image, and Pillow. Do not install these individually. Conda, Node.js, and Jupyter are not needed for normal use. Development/notebook extras are described in the [README](../README.md).

## 6. Launch and use the workbench

Windows:

```powershell
.\.venv\Scripts\python.exe ui\app_processing.py
```

macOS:

```bash
.venv/bin/python ui/app_processing.py
```

The browser normally opens **http://127.0.0.1:8766** automatically. If it does not, open that address manually. Seeing the import screen confirms startup. Keep the terminal running while using the app; ongoing server output is normal.

Follow the [user guide](QUICKSTART.md) for Sections 1–10. Export before stopping the app or refreshing the workspace. **Lightweight exports require matching original raw data for reproduction**, so keep the original files. Sessions live in memory and are not automatically saved.

## 7. Start again and stop

For later sessions, open the same project in VS Code, open its terminal, and run only the launch command from step 6. No new fork, clone, environment, or dependency installation is needed.

Use the explicit `.venv` interpreter path. A bare `python ui/app_processing.py` may use another environment and fail with `ModuleNotFoundError`.

After exporting, press **Ctrl+C** in the running terminal on either system to stop the server. Closing only the browser does not stop it.

## 8. Install FFmpeg only for MP4 export

Image processing and PNG export do not require FFmpeg. For video export, install its executable in the same terminal workflow.

Windows:

```powershell
winget install --id Gyan.FFmpeg --exact --source winget
```

macOS:

```bash
brew install ffmpeg
```

Restart VS Code, then verify:

```text
ffmpeg -version
```

Launch the app again from the new terminal. Installing a Python package named `ffmpeg` does not replace the executable. Package references: [WinGet FFmpeg](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg), [Homebrew FFmpeg](https://formulae.brew.sh/formula/ffmpeg).

## 9. Update after the maintainer publishes changes

1. Export your current work and stop the app.
2. Open your fork on GitHub and choose **Sync fork → Update branch** for the branch you use. The maintainer must first push updates to the upstream repository.
3. In your local project terminal, run `git status`.
4. If it reports a clean working tree, run the appropriate commands below. If there are local changes or conflicts, preserve and resolve them first; do not force-overwrite them.

Windows:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[ui]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe ui\app_processing.py
```

macOS:

```bash
git pull --ff-only
.venv/bin/python -m pip install -e ".[ui]"
.venv/bin/python -m pip check
.venv/bin/python ui/app_processing.py
```

A new clone or environment is normally unnecessary. If the Python requirement changes, follow the updated guide. Moving/renaming the project or switching computers may require recreating `.venv`. Software updates do not recalculate archived results automatically; import the project to reproduce and inspect the verification report.

## 10. Troubleshooting

| Symptom | Action |
| --- | --- |
| Repository not found / Fork unavailable | Check the URL, signed-in account, and repository access/fork permissions |
| `winget` or `brew` not found | Complete the package-manager setup in step 2 and restart VS Code; on Mac, run the installer's shell-environment Next steps |
| Python 3.12 not found | Complete step 4 and restart VS Code; do not create the environment with an arbitrary Python version |
| `pyproject.toml` not found | Open the cloned project root and check `Get-ChildItem` / `ls` |
| `.venv` interpreter not found | Complete step 5 in this project folder |
| `ModuleNotFoundError: No module named 'numpy'` | Use the `.venv` interpreter and rerun its `-m pip install -e ".[ui]"` command |
| Wrong Python version in `.venv` | Stop the app, rename the old environment as a backup, and recreate it using Python 3.12 |
| Dependency download fails | Check network/proxy access and retain the error output; do not disable certificate verification |
| Browser cannot connect | Check the terminal for startup errors and use the address printed by the server |
| `Address already in use` / `WinError 10048` | Use the existing instance, or stop it after exporting. To use another port, append `--port 8776` to the launch command and visit `http://127.0.0.1:8776` |
| Folder chooser seems absent | Check behind other windows; alternatively select all required bands through CSV input |
| Slow processing / insufficient memory | Start with fewer patterns and required bands; large images and rolling-ball increase memory and computation |
| Download not found | Check the browser's download history and Downloads folder |

When asking for help, include your operating system, `git log -1 --oneline`, Python version, current Section, exact command, and complete error output. Do not send the entire research dataset unless needed.

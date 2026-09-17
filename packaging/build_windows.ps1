param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows app on Windows, using 64-bit Python 3.12.' }
$Project = Split-Path $PSScriptRoot -Parent
Set-Location $Project
$Python = Join-Path $Project '.venv-build\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    & py -3.12 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.12 with the Python Launcher, then try again.' }
}
& $Python -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, '64-bit Python 3.12 required'"
if ($LASTEXITCODE -ne 0) { throw 'Incorrect build interpreter.' }
if (-not $SkipInstall) {
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
    & $Python -m pip install -e '.[ui]' -r packaging/requirements-windows.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
# Every build gets its own output folder, preserving previous distributions.
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$Output = Join-Path $Project "dist\windows-$Stamp"
$Work = Join-Path $Project "build\windows-$Stamp"
$env:PYTHONPATH = "$Project;$Project\src"
& $Python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw 'Source tests failed; no application was distributed.' }
& $Python -m PyInstaller --noconfirm --distpath $Output --workpath $Work packaging/windows.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$App = Join-Path $Output 'QCL Processing'
Copy-Item packaging/START_HERE.txt $App
& $Python packaging/bundle_notices.py $App
if ($LASTEXITCODE -ne 0) { throw 'Could not collect dependency notices.' }
# Test the frozen EXE from an unrelated directory to catch accidental source paths.
$Report = Join-Path $Output 'self-test.json'
$Process = Start-Process -FilePath (Join-Path $App 'QCL Processing.exe') -ArgumentList @('--self-test', "`"$Report`"") -WorkingDirectory $env:TEMP -PassThru
if (-not $Process.WaitForExit(180000)) {
    Stop-Process -Id $Process.Id
    throw 'The packaged application self-test timed out.'
}
if ($Process.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw "Packaged self-test failed. See $Report and LOCALAPPDATA\QCL Processing\app.log." }
$Check = Get-Content $Report -Raw | ConvertFrom-Json
if (-not $Check.ok -or -not $Check.frozen -or $Check.platform -ne 'win32') { throw 'The Windows EXE did not pass self-test.' }
Copy-Item $Report (Join-Path $App 'BUILD_CHECK.json')
& $Python -m pip freeze | Out-File (Join-Path $App 'BUILD_DEPENDENCIES.txt') -Encoding utf8
$Zip = Join-Path $Project "dist\QCL-Processing-Windows-x64-$Stamp.zip"
& $Python -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'QCL Processing')" ($Zip -replace '\.zip$','') $Output
if ($LASTEXITCODE -ne 0) { throw 'Could not create ZIP.' }
(Get-FileHash $Zip -Algorithm SHA256).Hash | Out-File "$Zip.sha256" -Encoding ascii
Write-Host "Application ready: $Zip"

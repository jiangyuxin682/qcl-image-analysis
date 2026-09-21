"""Browser-selected raw inputs, staged locally without trusting client paths."""
from __future__ import annotations

import json
import math
import re
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from ui.reproduction import MAX_UPLOAD


def zip_filename(value, fallback='qcl-processing'):
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', str(value or '').strip())
    name = re.sub(r'(?:\.zip)+$', '', name, flags=re.IGNORECASE).strip('. ')
    name = name or fallback
    if re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', name, re.IGNORECASE):
        name = '_' + name
    return name[:120].rstrip('. ') + '.zip'


def raw_upload(body, content_type):
    from ui.app_processing import ProcessingState

    if not body or len(body) > MAX_UPLOAD or not content_type.startswith('multipart/form-data;'):
        raise ValueError('Choose a data folder or spectral CSV files (up to 1 GiB).')
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    if not message.is_multipart():
        raise ValueError('Invalid file upload.')
    metadata, files = None, {}
    for part in message.iter_parts():
        field = part.get_param('name', header='content-disposition')
        if field == 'metadata':
            if metadata is not None:
                raise ValueError('Duplicate upload metadata.')
            metadata = json.loads(part.get_payload(decode=True))
        elif field == 'files':
            name = part.get_filename()
            if name in files:
                raise ValueError('Duplicate uploaded filename.')
            files[name] = part.get_payload(decode=True)
        else:
            raise ValueError('Unexpected upload field.')
    if not isinstance(metadata, dict) or not isinstance(metadata.get('files'), list) or not metadata['files']:
        raise ValueError('No spectral CSV files were selected.')
    if metadata.get('kind') not in {'folder', 'files'}:
        raise ValueError('Choose folder or CSV file input.')
    entries = metadata['files']
    if len(entries) > 100000 or len(entries) != len(files):
        raise ValueError('Upload file count does not match metadata.')
    work = tempfile.TemporaryDirectory(prefix='qcl-upload-')
    seen, roots, times = set(), set(), {}
    try:
        for index, item in enumerate(entries):
            relative = item['path']
            path = PurePosixPath(relative)
            if (not isinstance(relative, str) or path.is_absolute() or '..' in path.parts
                    or '\\' in relative or ':' in relative or not path.parts
                    or not re.fullmatch(r'lineScan_\d+_0invcm\.csv', path.name, re.IGNORECASE)):
                raise ValueError('Invalid spectral CSV relative path.')
            canonical = str(path)
            if canonical.casefold() in seen:
                raise ValueError('Duplicate spectral CSV path. Choose files from one pattern, or choose its parent folder.')
            seen.add(canonical.casefold())
            filename = f'image_{index}.csv'
            if filename not in files or not files[filename]:
                raise ValueError('Missing or empty uploaded CSV.')
            target = Path(work.name).joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[filename])
            timestamp = float(item['last_modified']) / 1000
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError('Invalid file modification time.')
            times[str(target.resolve())] = timestamp
            roots.add(path.parts[0])
        folder_mode = metadata.get('kind') == 'folder'
        if folder_mode:
            if len(roots) != 1 or any(len(PurePosixPath(i['path']).parts) < 2 for i in entries):
                raise ValueError('Choose one data folder at a time.')
            source = Path(work.name) / next(iter(roots))
            label = next(iter(roots))
        else:
            if any(len(PurePosixPath(i['path']).parts) != 1 for i in entries):
                raise ValueError('CSV selection must contain files from one pattern.')
            source = Path(work.name)
            label = 'Selected CSVs'
        state = ProcessingState()
        state.discover({'path': str(source)})
        if not folder_mode:
            state.dataset['pattern'] = 'pattern0'
        state.dataset['created_timestamp'] = state.dataset.path.map(lambda p: times[str(p)])
        state.dataset['timestamp_source'] = 'browser_last_modified'
        state._uploaded_inputs = work
        state.import_name = str(metadata.get('name', '')).strip() or label
        return state, state.discovery_state()
    except Exception:
        work.cleanup()
        raise


def copy_upload(stream, target, length):
    """Copy a bounded request segment without allocating the entire upload."""
    remaining = length
    while remaining:
        chunk = stream.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ValueError('Incomplete file upload.')
        target.write(chunk)
        remaining -= len(chunk)


def streamed_raw_upload(stream, length):
    """Read metadata followed by CSV bytes, staged on disk one file at a time."""
    import io

    from ui.app_processing import ProcessingState

    if length <= 8:
        raise ValueError('Invalid upload size.')
    header = stream.read(8)
    if len(header) != 8:
        raise ValueError('Incomplete upload header.')
    count = int.from_bytes(header, 'big')
    if not 0 < count <= min(8 * 1024**2, length - 8):
        raise ValueError('Invalid upload metadata size.')
    metadata_bytes = io.BytesIO()
    copy_upload(stream, metadata_bytes, count)
    metadata = json.loads(metadata_bytes.getvalue())
    entries = metadata.get('files')
    if metadata.get('kind') != 'files' or not isinstance(entries, list) or not 1 <= len(entries) <= 100000:
        raise ValueError('Choose spectral CSV files from one pattern.')
    seen = set()
    for item in entries:
        name, size = item['path'], item['size']
        if (not isinstance(name, str) or not re.fullmatch(r'lineScan_\d+_0invcm\.csv', name, re.IGNORECASE)
                or name.casefold() in seen or type(size) is not int or size <= 0):
            raise ValueError('Invalid or duplicate spectral CSV file.')
        seen.add(name.casefold())
        timestamp = float(item['last_modified']) / 1000
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError('Invalid file modification time.')
    if 8 + count + sum(item['size'] for item in entries) != length:
        raise ValueError('Upload size does not match metadata.')
    work = tempfile.TemporaryDirectory(prefix='qcl-upload-')
    try:
        times = {}
        for item in entries:
            target = Path(work.name) / item['path']
            with target.open('wb') as output:
                copy_upload(stream, output, item['size'])
            times[str(target.resolve())] = float(item['last_modified']) / 1000
        state = ProcessingState()
        state.discover({'path': work.name})
        state.dataset['pattern'] = 'pattern0'
        state.dataset['created_timestamp'] = state.dataset.path.map(lambda p: times[str(p)])
        state.dataset['timestamp_source'] = 'browser_last_modified'
        state._uploaded_inputs = work
        state.import_name = str(metadata.get('name', '')).strip() or 'Selected CSVs'
        return state
    except Exception:
        work.cleanup()
        raise


def choose_local_folder():
    """Run the OS picker outside HTTP threads (Tk requires a GUI main thread)."""
    import subprocess
    import sys

    if sys.platform == 'darwin':
        command = ['osascript', '-e', 'try\nPOSIX path of (choose folder with prompt "Choose QCL data folder")\non error number -128\nreturn ""\nend try']
        encoding = 'utf-8'
    elif sys.platform == 'win32':
        script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                  "Add-Type -AssemblyName System.Windows.Forms; "
                  "$picker = New-Object System.Windows.Forms.FolderBrowserDialog; "
                  "$picker.Description = 'Choose QCL data folder'; "
                  "if ($picker.ShowDialog() -eq 'OK') { [Console]::Write($picker.SelectedPath) }; $picker.Dispose()")
        command = ['powershell.exe', '-NoProfile', '-STA', '-Command', script]
        encoding = 'utf-8-sig'
    else:
        command = [sys.executable, '-c', 'import tkinter as t; from tkinter import filedialog; r=t.Tk(); r.withdraw(); print(filedialog.askdirectory(title="Choose QCL data folder")); r.destroy()']
        encoding = 'utf-8'
    try:
        result = subprocess.run(command, capture_output=True, timeout=300, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Could not open the system folder chooser. Run the app on a local desktop, or use Spectral CSV files.') from exc
    return result.stdout.decode(encoding).strip()

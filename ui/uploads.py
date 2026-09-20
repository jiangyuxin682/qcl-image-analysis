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

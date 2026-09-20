"""Browser file selection, multipart staging and comparison project imports."""
import io
import json
import zipfile

import pytest
from test_app_processing import acquisition as acquisition_fixture
from test_app_processing import complete

from ui.app_processing import ComparisonSession, Handler, ProcessingState
from ui.uploads import raw_upload


@pytest.fixture
def acquisition(tmp_path):
    return acquisition_fixture.__wrapped__(tmp_path)


def multipart(paths, kind='folder', name=''):
    boundary = 'qcl-test-boundary'
    metadata = {'kind': kind, 'name': name, 'files': [
        {'path': path, 'last_modified': 1700000000123} for path in paths]}
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'.encode()
             + json.dumps(metadata).encode() + b'\r\n']
    for index in range(len(paths)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="image_{index}.csv"\r\nContent-Type: text/csv\r\n\r\n1,2\n3,4\r\n'.encode())
    return b''.join(parts) + f'--{boundary}--\r\n'.encode(), f'multipart/form-data; boundary={boundary}'


@pytest.mark.parametrize('root', ['stacks', 'acquisition/stacks'])
def test_folder_upload_preserves_patterns_and_browser_timestamps(root):
    data, mime = multipart([f'{root}/pattern{i}/lineScan_{wn}_0invcm.csv'
                            for i in (0, 1) for wn in (1601, 1658, 1702)], name='Uploaded data')
    state, discovery = raw_upload(data, mime)
    assert discovery['files'] == 6
    assert [p['pattern'] for p in discovery['availability']] == ['pattern0', 'pattern1']
    assert state.import_name == 'Uploaded data'
    assert (state.dataset.timestamp_source == 'browser_last_modified').all()
    assert (state.dataset.created_timestamp == 1700000000.123).all()
    state.configure({'mapping': {1658: [1601, 1702]}, 'patterns': ['pattern0', 'pattern1']})
    assert len(state.raw) == 6
    state._uploaded_inputs.cleanup()


def test_multiple_csv_selection_is_one_pattern():
    data, mime = multipart([f'lineScan_{wn}_0invcm.csv' for wn in (1601, 1658, 1702)], 'files')
    state, discovery = raw_upload(data, mime)
    assert discovery['availability'] == [{'pattern': 'pattern0', 'wavenumbers': [1601, 1658, 1702]}]
    state._uploaded_inputs.cleanup()


@pytest.mark.parametrize('paths', [
    ['../lineScan_1601_0invcm.csv'], ['/tmp/lineScan_1601_0invcm.csv'],
    ['a/lineScan_1601_0invcm.csv', 'a/lineScan_1601_0invcm.csv'],
    ['a/lineScan_1601_0invcm.csv', 'b/lineScan_1658_0invcm.csv'],
    ['a/not-spectral.csv'],
])
def test_invalid_upload_paths_are_rejected(paths):
    with pytest.raises(ValueError):
        raw_upload(*multipart(paths))


def test_upload_and_bootstrap_routes():
    from ui.app_processing import COMPARISON
    data, mime = multipart(['stacks/pattern0/lineScan_1601_0invcm.csv'])
    handler = Handler.__new__(Handler)
    handler.path = '/api/datasets/upload'
    handler.headers = {'Content-Length': str(len(data)), 'Content-Type': mime}
    handler.rfile = io.BytesIO(data)
    results = []
    handler.json = lambda result, status=200: results.append((status, result))
    handler.do_POST()
    assert results[-1][0] == 200
    dataset_id = results[-1][1]['id']
    handler.path = '/api/bootstrap?dataset=' + dataset_id
    handler.do_GET()
    assert results[-1][1]['kind'] == 'raw'
    assert results[-1][1]['state']['files'] == 1
    COMPARISON.datasets.pop(dataset_id)._uploaded_inputs.cleanup()
    COMPARISON.names.pop(dataset_id)


def test_import_comparison_bundle_is_atomic(acquisition):
    original = complete(acquisition)
    source = ComparisonSession()
    one = source.register(original, 'A')['id']
    two = source.register(original, 'B')['id']
    package = source.export([one, two])
    target = ComparisonSession()
    restored = target.import_projects(package)
    assert [d['name'] for d in restored['datasets']] == ['A', 'B']
    assert all(d['reproduced'] for d in restored['datasets'])
    for d in restored['datasets']:
        state = target.get(d['id'])
        assert state.reproduction_report['summary']['mismatch'] == 0
        state._reproduction_inputs.cleanup()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    files['dataset_2/results.zip'] = b'invalid ZIP'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for key, value in files.items():
            archive.writestr(key, value)
    before = set(target.datasets)
    with pytest.raises(zipfile.BadZipFile):
        target.import_projects(out.getvalue())
    assert set(target.datasets) == before


def test_adopt_releases_previous_uploaded_inputs():
    data, mime = multipart(['lineScan_1601_0invcm.csv'], 'files')
    uploaded, _ = raw_upload(data, mime)
    work = uploaded._uploaded_inputs
    state = ProcessingState()
    state.adopt(uploaded)
    assert state._uploaded_inputs is work
    state.adopt(ProcessingState())
    from pathlib import Path
    assert not Path(work.name).exists()

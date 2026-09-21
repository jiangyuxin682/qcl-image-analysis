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


def stream_request(entries=None):
    entries = entries or [{'path': 'lineScan_1601_0invcm.csv', 'size': 8, 'last_modified': 123000}]
    header = json.dumps({'kind': 'files', 'files': entries}).encode()
    return len(header).to_bytes(8, 'big') + header + b'1,2\n3,4\n'


def test_streamed_csv_import_and_incomplete_cleanup():
    from ui.uploads import streamed_raw_upload
    data = stream_request()
    state = streamed_raw_upload(io.BytesIO(data), len(data))
    assert state.discovery_state()['files'] == 1
    assert (state.dataset.created_timestamp == 123).all()
    state._uploaded_inputs.cleanup()
    with pytest.raises(ValueError, match='Incomplete'):
        streamed_raw_upload(io.BytesIO(data[:-1]), len(data))
    data = stream_request([{'path': '../lineScan_1601_0invcm.csv', 'size': 8, 'last_modified': 0}])
    with pytest.raises(ValueError, match='Invalid'):
        streamed_raw_upload(io.BytesIO(data), len(data))


def test_copy_upload_bounds_memory_and_accepts_large_total():
    from ui.uploads import copy_upload
    class Source:
        def read(self, size):
            assert size <= 1024**2
            return b'x' * size
    class Sink:
        count = 0
        def write(self, data):
            self.count += len(data)
    sink = Sink()
    copy_upload(Source(), sink, 1024**3 + 17)
    assert sink.count == 1024**3 + 17


def test_local_folder_import_does_not_upload_or_copy(acquisition, monkeypatch):
    session = ComparisonSession()
    monkeypatch.setattr('ui.app_processing.COMPARISON', session)
    handler = Handler.__new__(Handler)
    results = []
    handler.json = lambda result, status=200: results.append((status, result))
    def post(path, payload):
        body = json.dumps(payload).encode()
        handler.path = path
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.do_POST()
        return results[-1]
    monkeypatch.setattr('ui.app_processing.choose_local_folder', lambda: '')
    assert post('/api/choose-folder', {}) == (200, {'path': ''})
    assert post('/api/import-local', {'path': str(acquisition)})[0] == 200
    state = session.get('default')
    assert state._uploaded_inputs is None
    assert all(p.is_relative_to(acquisition) for p in state.dataset.path)
    previous = state.discovery_state()
    assert post('/api/import-local', {'path': str(acquisition / 'missing')})[0] != 200
    assert state.discovery_state() == previous
    result = post('/api/datasets', {'path': str(acquisition), 'name': 'Direct'})
    assert result[0] == 200
    assert session.get(result[1]['id'])._uploaded_inputs is None


def test_file_backed_zip_reproduction(acquisition, tmp_path):
    from ui.reproduction import reproduce
    original = complete(acquisition)
    path = tmp_path / 'project.zip'
    path.write_bytes(original.export())
    with path.open('rb') as stream:
        state, report = reproduce(stream)
    assert report['summary']['mismatch'] == 0
    state._reproduction_inputs.cleanup()
    source = ComparisonSession()
    one = source.register(original, 'A')['id']
    two = source.register(original, 'B')['id']
    path.write_bytes(source.export([one, two]))
    target = ComparisonSession()
    with path.open('rb') as stream:
        result = target.import_projects(stream)
    for dataset in result['datasets']:
        restored = target.get(dataset['id'])
        assert restored.reproduction_report['summary']['mismatch'] == 0
        restored._reproduction_inputs.cleanup()


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_system_folder_chooser_cancel_unicode_and_failure(monkeypatch, platform):
    import subprocess
    import sys
    from types import SimpleNamespace

    from ui.uploads import choose_local_folder
    monkeypatch.setattr(sys, 'platform', platform)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 300
        return SimpleNamespace(stdout='C:/研究 data\n'.encode())
    monkeypatch.setattr(subprocess, 'run', run)
    assert choose_local_folder() == 'C:/研究 data'
    assert isinstance(calls[0], list)
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=b''))
    assert choose_local_folder() == ''
    def fail(*args, **kwargs):
        raise OSError('No desktop')
    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(ValueError, match='system folder chooser'):
        choose_local_folder()


def test_streaming_http_routes(acquisition, monkeypatch):
    session = ComparisonSession()
    monkeypatch.setattr('ui.app_processing.COMPARISON', session)
    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 1024**2
            return super().read(size)
    handler = Handler.__new__(Handler)
    results = []
    handler.json = lambda result, status=200: results.append((status, result))
    def post(path, body):
        handler.path = path
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = BoundedReader(body)
        handler.do_POST()
        assert results[-1][0] == 200, results[-1]
        return results[-1][1]
    imported = post('/api/datasets/upload-csv', stream_request())
    session.get(imported['id'])._uploaded_inputs.cleanup()
    original = complete(acquisition)
    restored = post('/api/reproduce', original.export())
    assert restored['report']['summary']['mismatch'] == 0
    session.get('default')._reproduction_inputs.cleanup()

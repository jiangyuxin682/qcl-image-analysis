"""Verify self-contained, recomputed project round trips and hostile/corrupt inputs."""
import hashlib
import io
import json
import zipfile

import numpy as np
import pytest
from test_app_processing import acquisition as acquisition_fixture
from test_app_processing import complete, configured

from ui.app_processing import ProcessingState
from ui.reproduction import compare_array, reproduce, validated_archive


@pytest.fixture
def acquisition(tmp_path):
    return acquisition_fixture.__wrapped__(tmp_path)


def rewrite(package, updates, *, rehash=False):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files.update(updates)
    if rehash:
        manifest = json.loads(files['manifest.json'])
        manifest['files'] = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                             for name, data in files.items() if name != 'manifest.json'}
        files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize('gold', [True, False])
@pytest.mark.parametrize('method', ['roi', 'brightest', 'darkest'])
def test_project_round_trip_without_source_files(acquisition, gold, method, monkeypatch):
    original = configured(acquisition)
    original.normalize({'has_gold': gold, 'n_pixels': 5})
    original.crop({'roi': {'x_min': 2, 'x_max': 18, 'y_min': 1, 'y_max': 15}})
    original.process({'fourier': {'mode': 'combined', 'centers': [[.2, .1]], 'pad_pixels': 2},
                      'rolling': {'radius': 3, 'pad_pixels': 2}})
    original.calculate({'method': method, 'roi': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3},
                        'search_roi': {'x_min': 0, 'x_max': 4, 'y_min': 0, 'y_max': 4},
                        'count': 5, 'reference_bands': {'pattern0': 1601, 'pattern1': 1702}})
    original.correct_baseline({})
    original.cnr({'background_source': 'analyte_free',
                  'target': {'x_min': 8, 'x_max': 11, 'y_min': 8, 'y_max': 11}, 'low': 5, 'high': 95})
    package = original.export()
    with validated_archive(package) as archive:
        meta = json.loads(archive.read('recipe.json'))
        image = np.load(io.BytesIO(archive.read(meta['inputs'][0]['file'])), allow_pickle=False)
        assert image.shape == (16, 20)
        assert meta['processing']['fourier']['preserve_mean'] is True
        assert meta['processing']['rolling']['min_background'] == 1e-6
    (acquisition / 'stacks').rename(acquisition / 'originals-unavailable')
    def no_reselection(*args, **kwargs):
        raise AssertionError('Must reuse committed coordinates, not select pixels again')
    monkeypatch.setattr('ui.app_processing.get_brightest_pixel_indices', no_reselection)
    monkeypatch.setattr('ui.app_processing.select_cell_free_pixels', no_reselection)
    replay, report = reproduce(package)
    assert report['status'] in {'exact', 'within_tolerance'}, [c for c in report['checks'] if c['status'] == 'mismatch']
    for key in original.crops:
        np.testing.assert_array_equal(replay.raw[key], original.raw[key])
        np.testing.assert_array_equal(replay.r0_pixels[key], original.r0_pixels[key])
        for name, array in original.stage_arrays(key).items():
            if array is not None:
                np.testing.assert_array_equal(replay.stage_arrays(key)[name], array)
    assert replay.raw_inspection({'pattern': 'pattern0', 'wavenumber': 1658, 'mode': 'image'})
    # A reproduced project can itself be exported and reproduced again.
    again, next_report = reproduce(replay.export())
    assert next_report['summary']['mismatch'] == 0
    again._reproduction_inputs.cleanup()
    replay._reproduction_inputs.cleanup()


def test_corruption_and_legacy_packages_leave_session_unchanged(acquisition):
    state = complete(acquisition)
    before = state.absorbance
    package = state.export()
    bad = rewrite(package, {'recipe.json': b'{}'})
    with pytest.raises(ValueError, match='checksum'):
        state.restore_project(bad)
    assert state.absorbance is before
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('metadata.json', '{}')
    with pytest.raises(ValueError, match='legacy'):
        state.restore_project(output.getvalue())
    with pytest.raises(ValueError, match='unsafe'):
        validated_archive(rewrite(package, {'../escape': b'data'}))
    with pytest.raises(ValueError, match='version'):
        manifest = json.loads(zipfile.ZipFile(io.BytesIO(package)).read('manifest.json'))
        manifest['version'] = 99
        validated_archive(rewrite(package, {'manifest.json': json.dumps(manifest).encode()}))
    assert state.absorbance is before


def test_changed_reference_results_report_mismatch(acquisition):
    state = complete(acquisition)
    package = state.export()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        name = 'pattern0/1658cm-1/[5]_Abs_uncorrected.csv'
        array = np.loadtxt(io.BytesIO(archive.read(name)), delimiter=',')
    array[0, 0] += .01
    output = io.StringIO()
    np.savetxt(output, array, delimiter=',')
    replay, report = reproduce(rewrite(package, {name: output.getvalue().encode()}, rehash=True))
    assert report['status'] == 'mismatch'
    check = next(c for c in report['checks'] if c['item'] == name)
    assert check['max_abs_error'] == pytest.approx(.01)
    replay._reproduction_inputs.cleanup()


def test_numeric_verification_tolerance_and_invalid_positions():
    assert compare_array('x', [1], [1])['status'] == 'exact'
    assert compare_array('x', [1 + 1e-11], [1])['status'] == 'within_tolerance'
    assert compare_array('x', [1.01], [1])['status'] == 'mismatch'
    assert compare_array('x', [np.nan, 1], [1, np.nan])['status'] == 'mismatch'
    assert compare_array('x', [[1]], [1])['status'] == 'mismatch'


def test_manual_background_and_atomic_restore(acquisition):
    state = complete(acquisition)
    state.cnr({'background': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3},
               'target': {'x_min': 6, 'x_max': 9, 'y_min': 6, 'y_max': 9}})
    destination = ProcessingState()
    result = destination.restore_project(state.export())
    assert result['stage'] == 'complete'
    assert result['report']['summary']['mismatch'] == 0
    assert result['cnr_rois']['background_source'] == 'manual'
    assert result['discovery']['files'] == 6
    destination._reproduction_inputs.cleanup()


def test_saved_coordinates_reject_fractional_or_out_of_bounds():
    from ui.reproduction import coordinates
    for pixels in ([[1.5, 2]], [[0, 10]], [[0, 0], [0, 0]], [[np.nan, 0]]):
        with pytest.raises(ValueError, match='coordinates'):
            coordinates(pixels, (10, 10))


def test_binary_upload_route_and_get_assets(acquisition, monkeypatch):
    from ui.app_processing import COMPARISON, Handler
    state = complete(acquisition)
    package = state.export()
    target = ProcessingState()
    monkeypatch.setitem(COMPARISON.datasets, 'reproduction-test', target)
    handler = Handler.__new__(Handler)
    handler.path = '/api/reproduce?dataset=reproduction-test'
    handler.headers = {'Content-Length': str(len(package)), 'Content-Type': 'application/zip'}
    handler.rfile = io.BytesIO(package)
    responses = []
    handler.json = lambda data, status=200: responses.append((status, data))
    handler.do_POST()
    assert responses[0][0] == 200
    assert responses[0][1]['report']['summary']['mismatch'] == 0
    handler.rfile = io.BytesIO(package)
    handler.headers['Origin'] = 'https://other.example'
    handler.headers['Host'] = '127.0.0.1:8766'
    handler.do_POST()
    assert responses[-1][0] == 403
    target._reproduction_inputs.cleanup()


def test_raw_array_header_validated_before_allocation():
    from ui.reproduction import read_raw_array
    data = io.BytesIO()
    np.lib.format.write_array_header_1_0(data, {'descr': '<f8', 'fortran_order': False, 'shape': (1000000000, 1000000000)})
    with pytest.raises(ValueError, match='byte length'):
        read_raw_array(data.getvalue(), [1000000000, 1000000000])


def test_previous_result_names_remain_reproducible(acquisition):
    from ui.reproduction import RESULT_FILENAMES, result_filename
    original = complete(acquisition)
    with zipfile.ZipFile(io.BytesIO(original.export())) as archive:
        files = {}
        for name in archive.namelist():
            old_name = name
            for stage, filename in RESULT_FILENAMES.items():
                if name.endswith('/' + result_filename(stage)):
                    old_name = name.rsplit('/', 1)[0] + '/' + stage + '.csv'
                    break
            files[old_name] = archive.read(name)
    manifest = json.loads(files['manifest.json'])
    manifest['files'] = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                         for name, data in files.items() if name != 'manifest.json'}
    files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    replay, report = reproduce(output.getvalue())
    assert report['status'] in {'exact', 'within_tolerance'}


def test_old_grouped_cnr_is_verified_then_migrated_to_individual_scales(acquisition):
    original = complete(acquisition)
    payload = {'background': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3},
               'target': {'x_min': 6, 'x_max': 9, 'y_min': 6, 'y_max': 9}, 'low': 10, 'high': 90}
    original.cnr(payload, scale_policy='legacy_grouped')
    package = original.export()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        recipe = json.loads(archive.read('recipe.json'))
    del recipe['configuration']['cnr_contrast']['scale_policy']
    package = rewrite(package, {'recipe.json': json.dumps(recipe).encode()}, rehash=True)
    replay, report = reproduce(package)
    assert report['summary']['mismatch'] == 0
    assert 'cnr_scale_migration' in report
    assert replay.cnr_scale_policy == 'per_image'
    expected = original.cnr(payload)['records']
    assert replay.cnr_records == expected
    again, next_report = reproduce(replay.export())
    assert next_report['summary']['mismatch'] == 0
    assert 'cnr_scale_migration' not in next_report
    replay._reproduction_inputs.cleanup()
    again._reproduction_inputs.cleanup()


@pytest.mark.parametrize('mixed', [False, True])
def test_optional_baseline_round_trip(acquisition, mixed):
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    mapping = {'1080': []}
    enabled = {'1080': False}
    if mixed:
        mapping['1658'] = [1601, 1702]
        enabled['1658'] = True
    state.configure({'mapping': mapping, 'baseline_enabled': enabled, 'patterns': ['pattern0', 'pattern1']})
    state.normalize({'has_gold': False})
    state.crop({'roi': {'x_min': 2, 'x_max': 18, 'y_min': 1, 'y_max': 15}})
    state.process({'fourier': {'enabled': False}, 'rolling': {'enabled': False}})
    result = state.calculate({'roi': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3}})
    assert result['stage'] == ('absorbed' if mixed else 'complete')
    if mixed:
        state.correct_baseline({})
        assert set(state.baselines) == {('pattern0', 1658), ('pattern1', 1658)}
    else:
        assert state.bands == [1080]
        assert not state.baselines
    assert state.stage_arrays(('pattern0', 1080))['baseline'] is None
    state.cnr({'background_source': 'analyte_free',
               'target': {'x_min': 8, 'x_max': 11, 'y_min': 8, 'y_max': 11}})
    skipped = [r for r in state.cnr_records if r['stage'] == 'baseline' and r['wavenumber'] == 1080]
    assert all(r['status'] == 'unavailable' and not np.isfinite(r['cnr']) for r in skipped)
    movie = state.timelapse({'kind': 'absorbance', 'wavenumber': 1080})
    assert len(movie['frames']) == 2
    assert movie['baseline_applied'] is False
    package = state.export()
    with validated_archive(package) as archive:
        config = json.loads(archive.read('recipe.json'))['configuration']
        assert config['baseline_enabled'] == enabled
        assert not any('1080' in name and 'baseline' in name.lower() for name in archive.namelist())
    replay, report = reproduce(package)
    assert report['status'] in {'exact', 'within_tolerance'}
    assert replay.baseline_enabled == state.baseline_enabled
    assert replay.mapping == state.mapping
    assert set(replay.baselines) == set(state.baselines)
    np.testing.assert_array_equal(replay.absorbance[('pattern0', 1080)], state.absorbance[('pattern0', 1080)])


def test_legacy_project_defaults_to_baseline_enabled(acquisition):
    state = complete(acquisition)
    package = state.export()
    with validated_archive(package) as archive:
        recipe = json.loads(archive.read('recipe.json'))
    del recipe['configuration']['baseline_enabled']
    package = rewrite(package, {'recipe.json': json.dumps(recipe).encode()}, rehash=True)
    replay, report = reproduce(package)
    assert replay.baseline_enabled == {1658: True}
    assert set(replay.baselines) == set(state.baselines)
    assert report['status'] in {'exact', 'within_tolerance'}


def test_lightweight_export_requires_matching_external_raw_and_reproduces(acquisition):
    original = complete(acquisition)
    options = {'raw_inputs': False, 'stages': [], 'auxiliary': False, 'tables': False}
    package = original.export(options)
    with validated_archive(package) as archive:
        names = archive.namelist()
        assert 'verification.json' in names and 'recipe.json' in names
        assert not any(name.endswith('.npy') or name.endswith('Abs_uncorrected.csv') for name in names)
        assert 'quality_control.csv' not in names
    with pytest.raises(ValueError, match='excludes raw'):
        reproduce(package)
    external = ProcessingState()
    external.discover({'path': str(acquisition)})
    replay, report = reproduce(package, external=external)
    assert report['status'] == 'exact'
    assert any('fingerprint' in c.get('reason', '') for c in report['checks'])
    np.testing.assert_array_equal(replay.baselines[('pattern0', 1658)].corrected, original.baselines[('pattern0', 1658)].corrected)
    # New raw values must not be presented as reproduction of the old input.
    path = external.dataset[external.dataset.wavenumber == 1601].iloc[0].path
    data = np.loadtxt(path, delimiter=',');np.savetxt(path, data + 1, delimiter=',')
    with pytest.raises(ValueError, match='differs'):
        reproduce(package, external=external)


def test_apply_saved_settings_does_not_copy_old_spatial_selections(acquisition):
    original = complete(acquisition)
    external = ProcessingState();external.discover({'path': str(acquisition)})
    external.dataset['pattern'] = external.dataset.pattern.str.replace('pattern', 'newpattern')
    applied, report = reproduce(original.export({'raw_inputs': False}), external=external, mode='apply')
    assert report is None and applied.reproduction_report is None
    assert applied.stage == 'configured'
    assert applied.patterns == ['newpattern0', 'newpattern1']
    assert applied.mapping == original.mapping
    assert not applied.absorbance and not applied.gold_pixels and not applied.r0_pixels
    assert applied.on_roi is None and applied.cnr_rois is None
    bootstrap = applied.applied_state()
    assert bootstrap['applied_settings'] and bootstrap['parameters']['fourier']['mode'] == original.parameters['fourier']['mode']
    assert 'reference_bands' not in bootstrap['r0_selection']
    assert all(row.path.exists() for row in applied.dataset.itertuples())


def test_selective_export_and_fingerprint_verification_level(acquisition):
    original = complete(acquisition)
    package = original.export({'raw_inputs': True, 'stages': ['baseline'], 'auxiliary': False, 'tables': True})
    with validated_archive(package) as archive:
        names = archive.namelist()
        assert any(name.endswith('Abs_baseline_corrected.csv') for name in names)
        assert not any(name.endswith('Abs_uncorrected.csv') for name in names)
        verification = json.loads(archive.read('verification.json'))
    item = next(k for k in verification['arrays'] if k.endswith('Abs_uncorrected.csv'))
    verification['arrays'][item]['sha256'] = '0'*64
    altered = rewrite(package, {'verification.json': json.dumps(verification).encode()}, rehash=True)
    _, report = reproduce(altered)
    assert report['status'] == 'unverified' and report['summary']['unverified'] == 1


def test_version_one_project_remains_importable(acquisition):
    package = complete(acquisition).export()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if name not in {'manifest.json', 'verification.json'}}
    recipe = json.loads(files['recipe.json']);recipe['version'] = 1;recipe.pop('export_options')
    for item in recipe['inputs']:item.pop('fingerprint')
    files['recipe.json'] = json.dumps(recipe).encode()
    files['manifest.json'] = json.dumps({'format': recipe['format'], 'version': 1, 'files': {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()}}).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():archive.writestr(name, data)
    _, report = reproduce(output.getvalue())
    assert report['status'] in {'exact', 'within_tolerance'}


@pytest.mark.parametrize('lightweight', [False, True])
def test_unnumbered_v2_projects_still_reproduce(acquisition, lightweight):
    import re
    state = complete(acquisition)
    options = {'raw_inputs': True, 'stages': [], 'auxiliary': False} if lightweight else None
    with zipfile.ZipFile(io.BytesIO(state.export(options))) as archive:
        files = {re.sub(r'/\[\d+\]_', '/', name): archive.read(name)
                 for name in archive.namelist()}
    verification = json.loads(files['verification.json'])
    verification['arrays'] = {re.sub(r'/\[\d+\]_', '/', key): value
                              for key, value in verification['arrays'].items()}
    files['verification.json'] = json.dumps(verification).encode()
    manifest = json.loads(files['manifest.json'])
    manifest['files'] = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                         for name, data in files.items() if name != 'manifest.json'}
    files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    restored, report = reproduce(output.getvalue())
    assert report['status'] in {'exact', 'within_tolerance'}
    restored._reproduction_inputs.cleanup()

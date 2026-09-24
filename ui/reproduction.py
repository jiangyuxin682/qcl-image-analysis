"""Versioned, data-only reproduction packages. Archive code is never executed."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
import platform
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

FORMAT = 'qcl-processing-project'
VERSION = 1
RESULT_FILENAMES = {
    'raw': 'Intensity_raw', 'reflectance': 'Reflectance_gold_normalized',
    'fourier': 'Signal_Fourier_filtered', 'rolling': 'Signal_flat_field_corrected',
    'absorbance': 'Abs_uncorrected', 'baseline': 'Abs_baseline_corrected',
    'linear_baseline': 'Abs_fitted_linear_baseline',
    'background': 'Rolling_ball_background', 'gain': 'Flat_field_gain',
}


def result_filename(stage):
    return RESULT_FILENAMES.get(stage, stage) + '.csv'

MAX_UPLOAD = 1024**3
MAX_EXPANDED = 4 * 1024**3
RTOL, ATOL = 1e-10, 1e-12


def resolved_parameters(parameters):
    f, r = parameters['fourier'], parameters['rolling']
    sigma = f.get('sigma', .01)
    return {
        'fourier': {'enabled': True, 'mode': 'notch', 'centers': [],
                    'sigma_x': f.get('sigma_x', sigma), 'sigma_y': f.get('sigma_y', sigma),
                    'strength': .9, 'protect_radius': .02, 'cutoff_x': .15,
                    'cutoff_y': .15, 'pad_pixels': 0, 'preserve_mean': True, **f},
        'rolling': {'enabled': True, 'radius': 30, 'kernel_height': .05,
                    'feature_polarity': 'dark', 'smooth_sigma': 1, 'pad_pixels': 0,
                    'min_background': 1e-6, 'reference_level': None, **r},
    }


def coordinates(value, shape, count=None):
    pixels = np.asarray(value)
    if (pixels.ndim != 2 or pixels.shape[1] != 2 or not pixels.size
            or not np.issubdtype(pixels.dtype, np.number)
            or np.iscomplexobj(pixels) or not np.isfinite(pixels).all()
            or not np.equal(pixels, np.floor(pixels)).all()):
        raise ValueError('Saved pixel coordinates must be a nonempty integer (N, 2) array.')
    if ((pixels < 0).any() or (pixels[:, 0] >= shape[0]).any()
            or (pixels[:, 1] >= shape[1]).any()
            or len(np.unique(pixels, axis=0)) != len(pixels)
            or (count is not None and len(pixels) != count)):
        raise ValueError('Saved pixel coordinates are out of bounds, duplicated, or have the wrong count.')
    return pixels.astype(int)


def environment():
    root = Path(__file__).resolve().parents[1]
    versions = {}
    for name in ('numpy', 'scipy', 'pandas', 'scikit-image', 'matplotlib', 'qcl-image-analysis'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    files = [*sorted((root / 'src/qcl_analysis').glob('*.py')),
             root / 'ui/app_processing.py', root / 'ui/reproduction.py']
    fingerprints = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in files if p.is_file()}
    git = {'commit': None, 'dirty': None}
    try:
        git['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                               stderr=subprocess.DEVNULL, timeout=3).decode().strip()
        git['dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root,
                                                   stderr=subprocess.DEVNULL, timeout=3).strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {'python': platform.python_version(), 'platform': platform.platform(),
            'packages': versions, 'git': git, 'source_sha256': fingerprints}


def write_project(archive, state, metadata, clean_json):
    """Add full inputs and a verification manifest to the human-readable results."""
    inputs = []
    for index, (key, array) in enumerate(state.raw.items()):
        name = f'inputs/image_{index:06d}.npy'
        output = io.BytesIO()
        np.save(output, array, allow_pickle=False)
        archive.writestr(name, output.getvalue())
        row = state.dataset[(state.dataset.pattern == key[0]) & (state.dataset.wavenumber == key[1])].iloc[0]
        inputs.append({'pattern': key[0], 'wavenumber': key[1], 'file': name,
                       'shape': list(array.shape), 'dtype': str(array.dtype),
                       'source_path': str(row.path), 'frame': int(row.frame),
                       'created_timestamp': float(row.created_timestamp),
                       'timestamp_source': row.timestamp_source})
    recipe = {'format': FORMAT, 'version': VERSION,
              'selection_policy': 'reuse_committed_pixel_coordinates_and_crop_positions',
              'inputs': inputs, 'configuration': metadata,
              'processing': resolved_parameters(state.parameters),
              'scope': 'Sections 2–8 numerical processing; view, spectrum and video state excluded'}
    archive.writestr('recipe.json', json.dumps(clean_json(recipe), indent=2, allow_nan=False))
    archive.writestr('environment.json', json.dumps(environment(), indent=2))
    if getattr(state, 'reproduction_report', None):
        archive.writestr('reproduction_report.json', json.dumps(clean_json(state.reproduction_report), indent=2, allow_nan=False))
    archive.writestr('REPRODUCE.txt', 'Open QCL Processing Workbench, choose Import processing ZIP in Section 1, then Reproduce.\n'
                     'Full loaded raw image arrays are included losslessly in inputs/*.npy. Original CSV formatting is not retained.\n'
                     'Results use the original CSV layout. No original source path is needed.\n'
                     'Version 1 restores numerical Sections 2–8 only, not videos, line plots or multi-folder workspace settings.\n')
    inventory = {name: {'size': archive.getinfo(name).file_size,
                        'sha256': hashlib.sha256(archive.read(name)).hexdigest()}
                 for name in archive.namelist()}
    archive.writestr('manifest.json', json.dumps({'format': FORMAT, 'version': VERSION,
                                                'files': inventory}, indent=2))


def archive_source(data):
    if isinstance(data, (bytes, bytearray)):
        size = len(data)
        source = io.BytesIO(data)
    else:
        data.seek(0, 2)
        size = data.tell()
        data.seek(0)
        source = data
    if not 0 < size <= MAX_UPLOAD:
        raise ValueError('Project ZIP exceeds the 1 GiB limit.')
    return source


def validated_archive(data):
    try:
        archive = zipfile.ZipFile(archive_source(data))
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 100000:
            raise ValueError('Archive contains duplicate names or too many files.')
        if sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
            raise ValueError('Archive expands beyond the 4 GiB limit.')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('Archive contains an unsafe file path.')
        if 'manifest.json' not in names:
            raise ValueError('This is a legacy results ZIP, not a reproduction project. Re-export using the current app. For a multi-folder ZIP, select one inner results.zip.')
        if archive.getinfo('manifest.json').file_size > 32 * 1024**2:
            raise ValueError('Project manifest is too large.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != FORMAT or manifest.get('version') != VERSION:
            raise ValueError('Unsupported reproduction package format or version.')
        inventory = manifest['files']
        if set(inventory) != set(names) - {'manifest.json'}:
            raise ValueError('Manifest does not match the archive file list.')
        for name, entry in inventory.items():
            digest = hashlib.sha256()
            with archive.open(name) as member:
                while chunk := member.read(1024 * 1024):
                    digest.update(chunk)
            if archive.getinfo(name).file_size != entry['size'] or digest.hexdigest() != entry['sha256']:
                raise ValueError(f'File checksum mismatch: {name}')
        return archive
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, NotImplementedError) as exc:
        raise ValueError('Invalid or corrupted reproduction archive.') from exc


def read_raw_array(payload, shape):
    """Validate NPY dimensions and byte length before NumPy allocates its array."""
    stream = io.BytesIO(payload)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        stored_shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        stored_shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ValueError('Unsupported raw array encoding.')
    if (len(stored_shape) != 2 or min(stored_shape) < 1 or dtype != np.float64
            or list(stored_shape) != shape
            or math.prod(stored_shape) * dtype.itemsize != len(payload) - stream.tell()):
        raise ValueError('Invalid full raw input array dimensions or byte length.')
    stream.seek(0)
    array = np.load(stream, allow_pickle=False)
    if not np.isfinite(array).all():
        raise ValueError('Invalid full raw input array values.')
    return array


def compare_array(name, actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    record = {'item': name, 'status': 'mismatch', 'max_abs_error': None, 'max_rel_error': None}
    if actual.shape != expected.shape:
        return {**record, 'reason': 'shape differs'}
    if not (np.array_equal(np.isnan(actual), np.isnan(expected))
            and np.array_equal(np.isposinf(actual), np.isposinf(expected))
            and np.array_equal(np.isneginf(actual), np.isneginf(expected))):
        return {**record, 'reason': 'invalid-pixel positions differ'}
    finite = np.isfinite(expected)
    error = np.abs(actual[finite] - expected[finite])
    record['max_abs_error'] = float(error.max()) if error.size else 0.0
    record['max_rel_error'] = float(np.max(error / np.maximum(np.abs(expected[finite]), ATOL))) if error.size else 0.0
    if np.array_equal(actual, expected, equal_nan=True):
        record['status'] = 'exact'
    elif np.allclose(actual, expected, rtol=RTOL, atol=ATOL, equal_nan=True):
        record['status'] = 'within_tolerance'
    return record


def compare_records(name, actual, expected):
    """Compare numeric fields with tolerance and categorical fields exactly."""
    checks = []
    def visit(a, b, path):
        if isinstance(b, dict):
            if not isinstance(a, dict) or set(a) != set(b):
                checks.append({'item': path, 'status': 'mismatch', 'reason': 'fields differ'})
            else:
                for key in b:
                    visit(a[key], b[key], path + '/' + str(key))
        elif isinstance(b, list):
            if not isinstance(a, list) or len(a) != len(b):
                checks.append({'item': path, 'status': 'mismatch', 'reason': 'record count differs'})
            else:
                for i, (aa, bb) in enumerate(zip(a, b)):
                    visit(aa, bb, path + '/' + str(i))
        elif isinstance(b, (int, float)) and not isinstance(b, bool) and isinstance(a, (int, float)):
            checks.append(compare_array(path, [a], [b]))
        elif a != b:
            checks.append({'item': path, 'status': 'mismatch', 'reason': 'value differs'})
    visit(actual, expected, name)
    if not checks:
        checks.append({'item': name, 'status': 'exact'})
    return checks


def reproduce(data, progress=lambda **values: None):
    """Build an isolated new session; callers commit only after successful completion."""
    from qcl_analysis.cropping import crop_image
    from ui.app_processing import ProcessingState, clean_json, roi_from

    progress(status='Validating project', completed=0, total=7)
    archive = validated_archive(data)
    work = tempfile.TemporaryDirectory(prefix='qcl-reproduce-')
    try:
        recipe = json.loads(archive.read('recipe.json'))
        if recipe.get('format') != FORMAT or recipe.get('version') != VERSION:
            raise ValueError('Unsupported processing recipe version.')
        if recipe.get('selection_policy') != 'reuse_committed_pixel_coordinates_and_crop_positions':
            raise ValueError('Unsupported spatial-selection policy.')
        meta = recipe['configuration']
        current_environment = environment()
        saved_environment = json.loads(archive.read('environment.json'))
        differences = [key for key in ('python', 'packages', 'source_sha256')
                       if saved_environment.get(key) != current_environment.get(key)]
        state = ProcessingState()
        rows = []
        keys = set()
        for index, item in enumerate(recipe['inputs']):
            key = (item['pattern'], item['wavenumber'])
            if key in keys:
                raise ValueError('Duplicate input pattern/wavenumber.')
            keys.add(key)
            # Pattern names are later used in ZIP member names, never as input paths.
            if not isinstance(key[0], str) or not key[0] or key[0] in {'.', '..'} or any(c in key[0] for c in '/\\:'):
                raise ValueError('Invalid pattern name in recipe.')
            array = read_raw_array(archive.read(item['file']), item['shape'])
            path = Path(work.name) / f'image_{index:06d}.csv'
            np.savetxt(path, array, delimiter=',')
            rows.append({'pattern': key[0], 'wavenumber': key[1], 'path': path,
                         'frame': item['frame'], 'created_timestamp': item['created_timestamp'],
                         'timestamp_source': item['timestamp_source']})
        state.dataset = pd.DataFrame(rows)
        state.path = Path(work.name)
        state.stage = 'discovered'
        state.configure({'mapping': meta['centers_and_references'], 'patterns': meta['patterns']})
        if set(state.raw) != keys:
            raise ValueError('Recipe inputs do not match the configured patterns and bands.')
        progress(status='Recalculating normalization', completed=1, total=7)
        gold = {}
        cell = {}
        for key in state.raw:
            folder = f'{key[0]}/{key[1]}cm-1'
            if meta['has_gold_patch_reference']:
                gold[key] = np.loadtxt(io.BytesIO(archive.read(f'{folder}/gold_reference_pixels.csv')),
                                       delimiter=',', skiprows=1, ndmin=2)
            cell[key] = np.loadtxt(io.BytesIO(archive.read(f'{folder}/cell_free_pixels.csv')),
                                   delimiter=',', skiprows=1, ndmin=2)
        qc = meta['qc_settings']
        state.normalize({'has_gold': meta['has_gold_patch_reference'], 'n_pixels': meta['n_reference_pixels'],
                         'robust_z_threshold': qc.get('robust_z_threshold', 5),
                         'relative_threshold': qc.get('min_relative_deviation', .1)}, saved_pixels=gold)
        # Use the committed crop positions; do not rerun a potentially changed tracker.
        progress(status='Restoring committed crops', completed=2, total=7)
        state.on_roi = roi_from(meta['on_ms_roi'])
        state.on_rois = {p: roi_from(meta['on_ms_rois_by_pattern'][p]) for p in state.patterns}
        state.crops = {key: crop_image(array, state.on_rois[key[0]]) for key, array in state.processing_images().items()}
        if len({a.shape for a in state.crops.values()}) != 1 or min(next(iter(state.crops.values())).shape) < 2:
            raise ValueError('Saved crops must have matching shapes of at least 2 × 2.')
        state.drift = meta['drift_correction']
        state.stage = 'cropped'
        progress(status='Reprocessing Fourier and rolling ball', completed=3, total=7)
        state.process(recipe['processing'])
        progress(status='Recalculating absorbance and baseline', completed=4, total=7)
        state.calculate({**meta['cell_free_selection'], 'roi': meta['cell_free_roi_local']}, saved_pixels=cell)
        state.correct_baseline({})
        progress(status='Recalculating CNR', completed=5, total=7)
        cnr = meta['cnr_contrast']['records']
        scale_policy = meta['cnr_contrast'].get('scale_policy', 'legacy_grouped')
        if cnr:
            state.cnr({**meta['cnr_rois'], 'low': cnr[0]['contrast_low_percentile'],
                       'high': cnr[0]['contrast_high_percentile']}, scale_policy=scale_policy)
        progress(status='Verifying results', completed=6, total=7)
        checks = []
        for key in state.crops:
            folder = f'{key[0]}/{key[1]}cm-1'
            arrays = state.stage_arrays(key)
            arrays.update(fourier_mask=state.ff[key].mask, background=state.flat[key].background,
                          gain=state.flat[key].gain, flat_valid_mask=state.flat[key].valid_mask.astype(int))
            cell_mask = np.zeros(state.crops[key].shape, dtype=int)
            points = state.r0_pixels[key]
            cell_mask[points[:, 0], points[:, 1]] = 1
            arrays['cell_free_pixel_mask'] = cell_mask
            if key in state.baselines:
                arrays.update(linear_baseline=state.baselines[key].baseline,
                              baseline_valid_mask=state.baselines[key].valid_mask.astype(int))
            for stage, array in arrays.items():
                if array is None:
                    continue
                name = f'{folder}/{result_filename(stage)}'
                if name not in archive.namelist():
                    name = f'{folder}/{stage}.csv'  # Earlier project exports.
                expected = np.loadtxt(io.BytesIO(archive.read(name)), delimiter=',', ndmin=2)
                checks.append(compare_array(name, array, expected))
        checks += compare_records('CNR', clean_json(state.cnr_records), cnr)
        checks += compare_records('R0', clean_json(state.r0_records), meta['r0'])
        checks += compare_records('flat_reference_levels',
                                  [{'pattern': k[0], 'wavenumber': k[1], 'level': f.reference_level}
                                   for k, f in state.flat.items()], meta['flat_reference_levels'])
        expected_qc = pd.read_csv(io.BytesIO(archive.read('quality_control.csv')))
        qc_columns = [c for c in expected_qc if c not in {'path'}]
        # Normalize pandas missing values to strict JSON nulls on both sides.
        checks += compare_records('QC', json.loads(state.qc[qc_columns].to_json(orient='records', double_precision=15)),
                                  json.loads(expected_qc[qc_columns].to_json(orient='records', double_precision=15)))
        summary = {status: sum(c['status'] == status for c in checks)
                   for status in ('exact', 'within_tolerance', 'mismatch')}
        report = {'status': 'mismatch' if summary['mismatch'] else 'within_tolerance' if summary['within_tolerance'] else 'exact',
                  'summary': summary, 'rtol': RTOL, 'atol': ATOL, 'checks': checks,
                  'environment_differences': differences, 'saved_environment': saved_environment,
                  'current_environment': current_environment,
                  'selection_policy': recipe['selection_policy']}
        if cnr and scale_policy == 'legacy_grouped':
            # Verify the archive under its historical rule, then use independent
            # image ranges for the current UI and subsequent project exports.
            state.cnr({**meta['cnr_rois'], 'low': cnr[0]['contrast_low_percentile'],
                       'high': cnr[0]['contrast_high_percentile']})
            report['cnr_scale_migration'] = 'Historical CNR verified with grouped scales; current CNR recalculated with per-image scales.'
        state.reproduction_report = report
        state._reproduction_inputs = work  # Keep generated CSVs available for all inspectors.
        progress(status='Reproduction complete', completed=7, total=7)
        return state, report
    except Exception:
        work.cleanup()
        raise
    finally:
        archive.close()


def project_members(data, name=''):
    """Accept a single project or the app's multi-dataset export; never extract ZIPs."""
    with zipfile.ZipFile(archive_source(data)) as archive:
        names = archive.namelist()
        if 'manifest.json' in names:
            yield name or 'Imported project', data
            return
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
            raise ValueError('Invalid or oversized multi-dataset ZIP.')
        if 'datasets.json' not in names:
            raise ValueError('Choose a reproducible project ZIP or a multi-dataset export from this app.')
        if archive.getinfo('datasets.json').file_size > 32 * 1024**2:
            raise ValueError('Dataset summary is too large.')
        datasets = json.loads(archive.read('datasets.json'))
        if not isinstance(datasets, list) or not 1 <= len(datasets) <= 1000:
            raise ValueError('Invalid dataset summary.')
        expected = {f'dataset_{i}/results.zip' for i in range(1, len(datasets) + 1)} | {'datasets.json'}
        if set(names) != expected:
            raise ValueError('Multi-dataset archive does not match its dataset summary.')
        expanded = 0
        for i, item in enumerate(datasets, 1):
            with tempfile.TemporaryFile() as package:
                with archive.open(f'dataset_{i}/results.zip') as member:
                    import shutil
                    shutil.copyfileobj(member, package, 1024 * 1024)
                package.seek(0)
                with zipfile.ZipFile(package) as inner:
                    expanded += sum(info.file_size for info in inner.infolist())
                    if expanded > MAX_EXPANDED:
                        raise ValueError('Combined projects expand beyond the 4 GiB limit.')
                label = str(item.get('name') or f'Dataset {i}')
                yield f'{name} · {label}' if name else label, package

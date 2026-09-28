"""Section 1 spectrum recipes and verification within processing projects."""
from __future__ import annotations

import copy
import io
from pathlib import Path

import numpy as np
import pandas as pd

from qcl_analysis.io import load_qcl_csv


def save_spectrum(state, settings):
    from ui.reproduction import array_fingerprint

    settings = copy.deepcopy(settings)
    result = state.raw_roi_spectrum(settings['selection'])
    filters = settings.get('filters', {})
    filtered = None
    if filters.get('fourier_enabled') or filters.get('sg_enabled'):
        filtered = state.filter_roi_spectrum({**filters,
            'wavenumbers': [p['wavenumber'] for p in result['points']],
            'absorbance': [p['absorbance'] for p in result['points']]})
    inputs = []
    for row in state.dataset[state.dataset.pattern == result['pattern']].sort_values('wavenumber').itertuples(index=False):
        array = load_qcl_csv(row.path)
        inputs.append({'pattern': row.pattern, 'wavenumber': int(row.wavenumber),
                       'shape': list(array.shape), 'fingerprint': array_fingerprint(array),
                       'source_path': str(row.path), 'frame': int(row.frame),
                       'created_timestamp': float(row.created_timestamp), 'timestamp_source': row.timestamp_source})
    state.spectrum_project = {'version': 1, 'settings': settings, 'inputs': inputs,
                              'result': result, 'filtered': filtered,
                              'formula': '-log10(mean(analyte ROI) / mean(analyte-free ROI))',
                              'coordinates': 'full raw image, zero-based, half-open rectangles',
                              'filter_order': 'Fourier with reflected padding, then SG mode=interp'}
    return {'saved': True, 'bands': len(inputs)}


def write_spectrum(archive, state, mode, processing_inputs):
    from ui.reproduction import array_fingerprint

    if mode == 'none' or not state.spectrum_project:
        return None
    saved = copy.deepcopy(state.spectrum_project)
    saved['raw_included'] = mode == 'raw'
    shared = {(i['pattern'], i['wavenumber']): i for i in processing_inputs}
    rows = {(r.pattern, int(r.wavenumber)): r for r in state.dataset.itertuples(index=False)}
    for index, item in enumerate(saved['inputs']):
        key = (item['pattern'], item['wavenumber'])
        existing = shared.get(key)
        if existing and existing['fingerprint'] != item['fingerprint']:
            raise ValueError('Spectrum and processing used different raw data. Recalculate before export.')
        item['file'] = existing.get('file') if existing else None
        if mode == 'raw' and not item['file']:
            array = load_qcl_csv(rows[key].path)
            if array_fingerprint(array) != item['fingerprint']:
                raise ValueError('Spectrum source files changed. Recalculate the spectrum before export.')
            name = f'inputs/spectrum_{index:06d}.npy'
            output = io.BytesIO()
            np.save(output, array.astype(np.float64), allow_pickle=False)
            archive.writestr(name, output.getvalue())
            item['file'] = name
            if existing is not None:
                existing['file'] = name
    table = pd.DataFrame(saved['result']['points'])
    for field in ('absorbance_fourier', 'absorbance_sg', 'absorbance_filtered'):
        values = (saved.get('filtered') or {}).get(field)
        if values is not None:
            table[field] = values
    archive.writestr('spectrum/[1]_full_spectrum.csv', table.to_csv(index=False))
    return saved


def restore_spectrum(state, saved, archive, work, external):
    from ui.reproduction import array_fingerprint, compare_array, read_raw_array

    if saved.get('version') != 1:
        raise ValueError('Unsupported spectrum recipe version.')
    expected = saved['result']
    expected_bands = [p['wavenumber'] for p in expected['points']]
    if [i['wavenumber'] for i in saved['inputs']] != expected_bands or len(set(expected_bands)) != len(expected_bands):
        raise ValueError('Spectrum input bands do not match saved results.')
    current = {(r.pattern, int(r.wavenumber)): r for r in state.dataset.itertuples(index=False)}
    external_rows = {(r.pattern, int(r.wavenumber)): r for r in external.dataset.itertuples(index=False)} if external is not None else {}
    extra = []
    for index, item in enumerate(saved['inputs']):
        key = (item['pattern'], item['wavenumber'])
        if key[0] != expected['pattern']:
            raise ValueError('Spectrum input pattern does not match its recipe.')
        if key in current:
            array = load_qcl_csv(current[key].path)
        elif external is not None:
            if key not in external_rows:
                raise ValueError(f'Full spectrum requires the original raw file for {key}. Select all measured bands.')
            array = load_qcl_csv(external_rows[key].path)
        elif item.get('file'):
            array = read_raw_array(archive.read(item['file']), item['shape'])
        else:
            raise ValueError('Full spectrum parameters require original raw data. Select its source folder or all spectral CSVs.')
        if array_fingerprint(array) != item['fingerprint']:
            raise ValueError(f'Full spectrum source data differs at {key}.')
        if key not in current:
            path = Path(work.name) / f'spectrum_{index:06d}.csv'
            np.savetxt(path, array, delimiter=',')
            extra.append({k: item[k] for k in ('pattern', 'wavenumber', 'frame', 'created_timestamp', 'timestamp_source')} | {'path': path})
    if extra:
        state.dataset = pd.concat([state.dataset, pd.DataFrame(extra)], ignore_index=True)
    # Compute only the recorded measured bands, even if other data is present.
    save_spectrum(state, saved['settings'])
    actual = state.spectrum_project
    checks = []
    for field in ('wavenumber', 'I', 'I_bg', 'ratio', 'absorbance'):
        values = lambda result, field=field: np.array([p[field] if p[field] is not None else np.nan for p in result['points']], dtype=float)
        checks.append(compare_array('Full spectrum/' + field, values(actual['result']), values(expected)))
    checks.append({'item': 'Full spectrum/validity', 'status': 'exact' if [p['status'] for p in actual['result']['points']] == [p['status'] for p in expected['points']] else 'mismatch'})
    for field in ('absorbance_fourier', 'absorbance_sg', 'absorbance_filtered'):
        if (saved.get('filtered') or {}).get(field) is not None:
            checks.append(compare_array('Full spectrum/' + field, (actual['filtered'] or {}).get(field, []), saved['filtered'][field]))
    return checks
